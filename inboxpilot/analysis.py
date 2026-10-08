"""Local, deterministic email analysis. Every output is derived from text actually
present in the message; nothing is invented. Priority always comes with reasons."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from email.utils import getaddresses

NO_DEADLINE = "No deadline identified."
FREEMAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com",
            "proton.me", "protonmail.com", "live.com", "aol.com", "msn.com"}
AUTOMATED_ADDR = re.compile(r"no[-_.]?reply|do[-_.]?not[-_.]?reply|notification|mailer|bounce|alerts?@|newsletter|digest", re.I)
BULK_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_FORUMS"}

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DAY = r"(?:mon|tues?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?"
_WHEN = (rf"(?:end of (?:the )?(?:day|week|month)|eod|eow|cob|tomorrow|today|tonight|next week|{_DAY}"
         rf"|{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}(?:,?\s+\d{{4}})?"
         rf"|\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?|\d{{4}}-\d{{2}}-\d{{2}})")
DEADLINE_RES = [
    re.compile(rf"\b(?:by|before|until|due(?: on| by)?|deadline(?: is| of)?|no later than|on or before)\s+{_WHEN}\b", re.I),
    re.compile(r"\b(?:deadline|due date)\s*[:\-]\s*[^.\n]{3,40}", re.I),
    re.compile(r"\bwithin\s+\d+\s+(?:hours?|days?|weeks?)\b", re.I),
]
ACTION_RE = re.compile(r"\b(please|could you|can you|would you|will you|need(?:s)? (?:you )?to|action required|"
                       r"let me know|kindly|make sure|don't forget|remember to|send me|confirm)\b", re.I)
URGENT_RE = re.compile(r"\b(urgent|asap|immediately|time[- ]sensitive|as soon as possible|critical)\b", re.I)
RECEIPT_RE = re.compile(r"receipt|invoice|order confirmation|your order|payment (?:received|confirmation|successful)|"
                        r"thank you for your (?:order|purchase|payment)", re.I)
KEYWORDS = {
    "Finance": r"invoice|receipt|payment|statement|bank|transaction|tax\b|billing|refund|credit card",
    "Shopping": r"order|shipped|shipping|delivery|tracking|purchase|your package|cart",
    "Travel": r"flight|booking|reservation|itinerary|hotel|boarding|check-in|airbnb",
    "Social": r"facebook|linkedin|twitter|instagram|friend request|tagged you|followed you|connection request",
    "Work": r"meeting|project|report|client|proposal|agenda|sprint|budget|team|schedule|review",
}
KEYWORDS = {k: re.compile(v, re.I) for k, v in KEYWORDS.items()}


def _addrs(h: str):
    return [a.lower() for _, a in getaddresses([h or ""]) if a]


def _domain(a: str) -> str:
    return a.split("@")[-1].lower() if "@" in a else ""


def clean_body(text: str) -> str:
    out = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if re.match(r"^On .{5,200} wrote:$", s) or s.startswith("-----Original Message"):
            break
        if s.startswith(">"):
            continue
        out.append(ln)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def sentences(text: str):
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", flat) if len(s.strip()) >= 15]


def find_questions(body: str):
    no_urls = re.sub(r"https?://\S+", " ", body)
    return [q.strip() for q in re.findall(r"[^.!?\n]{8,}\?", no_urls)]


def find_deadline(text: str):
    for rx in DEADLINE_RES:
        m = rx.search(text or "")
        if m:
            return m.group(0).strip()
    return None


@dataclass
class Analysis:
    category: str = "Personal"
    priority: str = "Low"
    reasons: list = field(default_factory=list)
    reply_candidate: bool = False
    reply_reason: str = ""
    is_receipt: bool = False
    deadline: str | None = None


def analyze(msg, user_email: str, known_contacts=frozenset()) -> Analysis:
    user = (user_email or "").lower()
    body = clean_body(msg.body or msg.snippet or "")
    head = f"{msg.subject}\n{body[:800]}"
    labels = set(msg.labels or [])
    sender = msg.sender_email.lower()
    a = Analysis(deadline=find_deadline(f"{msg.subject}\n{body}"))
    automated = bool(msg.has_unsubscribe or AUTOMATED_ADDR.search(sender) or labels & BULK_LABELS)
    a.is_receipt = bool(RECEIPT_RE.search(head)) and not msg.is_sent

    # ---- category
    if a.is_receipt:
        a.category = "Shopping" if KEYWORDS["Shopping"].search(head) and not re.search(r"invoice|payment", head, re.I) else "Finance"
    elif "CATEGORY_SOCIAL" in labels or KEYWORDS["Social"].search(sender):
        a.category = "Social"
    elif msg.has_unsubscribe or "CATEGORY_PROMOTIONS" in labels or re.search(r"newsletter|digest", f"{sender} {msg.subject}", re.I):
        a.category = "Newsletter"
    else:
        scores = {k: 2 * len(rx.findall(msg.subject)) + len(rx.findall(body[:500])) for k, rx in KEYWORDS.items()}
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            a.category = best
        elif automated:
            a.category = "Notifications"
        else:
            d = _domain(sender)
            a.category = "Work" if d and d == _domain(user) and d not in FREEMAIL else "Personal"

    # ---- reply detection
    questions = find_questions(body)
    action = ACTION_RE.search(body)
    to_addrs = _addrs(msg.to)
    addressed = (user in to_addrs) or not to_addrs
    if not msg.is_sent and not automated and not a.is_receipt and addressed:
        if questions:
            a.reply_candidate, a.reply_reason = True, "Question detected in message."
        elif action:
            a.reply_candidate, a.reply_reason = True, f"Request detected (“{action.group(0)}”)."

    # ---- priority (score + explanation)
    score, why = 0.0, []
    if user and user in to_addrs and len(to_addrs) <= 2:
        score += 1; why.append("✓ Directly addressed to you")
    if action:
        score += 1.5; why.append("✓ Contains a requested action")
    if questions:
        score += 1; why.append("✓ Contains a question")
    if a.deadline:
        score += 1.5; why.append(f"✓ Mentions a deadline (“{a.deadline}”)")
    if URGENT_RE.search(head):
        score += 1; why.append("✓ Uses urgent wording")
    if sender in known_contacts:
        score += 1; why.append("✓ You have written to this sender before")
    if automated:
        score -= 2; why.append("– Looks like an automated or bulk sender")
    if a.category == "Newsletter":
        score -= 1; why.append("– Newsletter / promotional content")
    a.priority = "High" if score >= 3 else "Medium" if score >= 1 else "Low"
    if msg.is_sent:
        a.priority, why = "Low", ["– Message you sent"]
    a.reasons = why or ["– No requests, questions, deadlines or urgent wording found"]
    return a


@dataclass
class Summary:
    summary: str
    key_points: list
    action_items: list
    deadline: str
    people: list
    suggested_response: str


def people_mentioned(msg, user_email: str):
    names, user = [], (user_email or "").lower()
    for hdr in (f"{msg.sender_name} <{msg.sender_email}>", msg.to, msg.cc):
        for n, addr in getaddresses([hdr]):
            if addr and addr.lower() != user:
                label = n.strip() or addr
                if label not in names:
                    names.append(label)
    m = re.search(r"(?:thanks|thank you|regards|best|cheers|sincerely)[,!]?\s*\n+\s*([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s*$",
                  clean_body(msg.body)[-250:], re.I | re.M)
    if m and m.group(1) not in names and not any(m.group(1).lower() in n.lower() for n in names):
        names.append(m.group(1))
    return names


def summarize(msg, user_email: str) -> Summary:
    body = clean_body(msg.body or "")
    sents = sentences(body or msg.snippet or "")
    summary = " ".join(sents[:2])[:320] if sents else "No readable text content in this email."
    actions = [s for s in sents if ACTION_RE.search(s)][:5]
    points = [s for s in sents[:12] if s not in actions and (re.search(r"\d", s) or "?" in s)][:4]
    return Summary(
        summary=summary,
        key_points=points or ["No key points identified."],
        action_items=actions or ["No action items identified."],
        deadline=find_deadline(f"{msg.subject}\n{body}") or NO_DEADLINE,
        people=people_mentioned(msg, user_email) or ["No people identified."],
        suggested_response=generate_draft(msg, user_email))


def generate_draft(msg, user_email: str, user_name: str = "") -> str:
    """Template draft built only from the message; unknowns stay as [placeholders]."""
    first = (msg.sender_name or "").split()[0] if msg.sender_name and "@" not in msg.sender_name else ""
    lines = [f"Hi {first}," if first else "Hello,", "", f"Thanks for your email about “{msg.subject}”.", ""]
    body = clean_body(msg.body or "")
    for q in find_questions(body)[:3]:
        lines += [f"You asked: “{q}”", "[Your answer]", ""]
    if not find_questions(body):
        lines += ["[Your response]", ""]
    dl = find_deadline(f"{msg.subject}\n{body}")
    if dl:
        lines += [f"I've noted the timing you mentioned (“{dl}”). [Confirm or propose a different date]", ""]
    lines += ["Best regards,", user_name or "[Your name]"]
    return "\n".join(lines)
