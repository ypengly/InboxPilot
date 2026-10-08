from __future__ import annotations
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses

ISO = "%Y-%m-%dT%H:%M:%S"

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
 id TEXT PRIMARY KEY, account TEXT NOT NULL, thread_id TEXT, sender_name TEXT, sender_email TEXT,
 recipients TEXT, cc TEXT, subject TEXT, date TEXT, snippet TEXT, body TEXT, unread INTEGER, is_sent INTEGER,
 category TEXT, priority TEXT, reasons TEXT, reply_candidate INTEGER, reply_reason TEXT, is_receipt INTEGER,
 deadline TEXT, category_override TEXT, priority_override TEXT, reply_override INTEGER);
CREATE INDEX IF NOT EXISTS ix_date ON messages(date);
CREATE INDEX IF NOT EXISTS ix_thread ON messages(thread_id, is_sent, date);
CREATE TABLE IF NOT EXISTS drafts(
 message_id TEXT PRIMARY KEY, body TEXT NOT NULL, updated TEXT NOT NULL);
DROP VIEW IF EXISTS v_messages;
CREATE VIEW v_messages AS SELECT m.*,
 COALESCE(category_override, category) AS eff_category,
 COALESCE(priority_override, priority) AS eff_priority,
 CASE WHEN is_sent=0 AND COALESCE(reply_override,
   CASE WHEN reply_candidate=1 AND NOT EXISTS (SELECT 1 FROM messages s WHERE s.thread_id=m.thread_id
        AND s.is_sent=1 AND s.date>m.date) THEN 1 ELSE 0 END)=1 THEN 1 ELSE 0 END AS needs_reply,
 CASE WHEN is_sent=1 AND NOT EXISTS (SELECT 1 FROM messages r WHERE r.thread_id=m.thread_id
        AND r.is_sent=0 AND r.date>m.date) THEN 1 ELSE 0 END AS awaiting
FROM messages m;
"""

VIEWS = {
    "inbox": "is_sent=0",
    "important": "is_sent=0 AND (eff_priority='High' OR eff_category='Important')",
    "needs_reply": "needs_reply=1",
    "follow_up": "awaiting=1 AND date<=:follow_cutoff",
    "newsletters": "is_sent=0 AND eff_category='Newsletter'",
    "receipts": "is_sent=0 AND is_receipt=1",
    "unread": "is_sent=0 AND unread=1",
}
SORTS = {
    "date_desc": "date DESC", "date_asc": "date ASC", "sender": "LOWER(sender_name) ASC, date DESC",
    "subject": "LOWER(subject) ASC, date DESC",
    "priority": "CASE eff_priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END, date DESC",
}
_COLS = ("id,account,thread_id,sender_name,sender_email,recipients,cc,subject,date,snippet,body,unread,is_sent,"
         "category,priority,reasons,reply_candidate,reply_reason,is_receipt,deadline").split(",")


def _like(s: str) -> str:
    return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class Database:
    def __init__(self, path):
        self.path = str(path)
        self._local = threading.local()
        self._conn().executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            self._local.c = c
        return c

    # ---- writes
    def upsert(self, m, a):
        p = {"id": m.id, "account": m.account, "thread_id": m.thread_id, "sender_name": m.sender_name,
             "sender_email": m.sender_email, "recipients": m.to, "cc": m.cc, "subject": m.subject,
             "date": m.date, "snippet": m.snippet, "body": m.body, "unread": int(m.is_unread),
             "is_sent": int(m.is_sent), "category": a.category, "priority": a.priority,
             "reasons": json.dumps(a.reasons), "reply_candidate": int(a.reply_candidate),
             "reply_reason": a.reply_reason, "is_receipt": int(a.is_receipt), "deadline": a.deadline}
        upd = ",".join(f"{c}=excluded.{c}" for c in _COLS if c not in ("id", "account"))
        with self._conn() as c:  # overrides are intentionally not touched on re-sync
            c.execute(f"INSERT INTO messages({','.join(_COLS)}) VALUES({','.join(':' + c for c in _COLS)}) "
                      f"ON CONFLICT(id) DO UPDATE SET {upd}", p)

    def _set(self, mid, col, val):
        with self._conn() as c:
            c.execute(f"UPDATE messages SET {col}=? WHERE id=?", (val, mid))

    def set_category(self, mid, value):
        self._set(mid, "category_override", value)
        if value == "Needs Reply":
            self._set(mid, "reply_override", 1)

    def set_priority(self, mid, value):
        self._set(mid, "priority_override", value)

    def dismiss_reply(self, mid):
        self._set(mid, "reply_override", 0)

    def refresh_unread(self, unread_ids: set, complete: bool):
        with self._conn() as c:
            if complete:
                c.execute("UPDATE messages SET unread=0 WHERE is_sent=0")
            c.executemany("UPDATE messages SET unread=1 WHERE id=?", [(i,) for i in unread_ids])

    def save_draft(self, mid, body):
        with self._conn() as c:
            c.execute("INSERT INTO drafts(message_id,body,updated) VALUES(?,?,?) ON CONFLICT(message_id) "
                      "DO UPDATE SET body=excluded.body, updated=excluded.updated",
                      (mid, body, datetime.now(timezone.utc).strftime(ISO)))

    def clear_all(self):
        with self._conn() as c:
            c.execute("DELETE FROM messages")
            c.execute("DELETE FROM drafts")

    # ---- reads
    def get(self, mid):
        r = self._conn().execute("SELECT * FROM v_messages WHERE id=?", (mid,)).fetchone()
        return dict(r) if r else None

    def get_draft(self, mid):
        r = self._conn().execute("SELECT body FROM drafts WHERE message_id=?", (mid,)).fetchone()
        return r["body"] if r else None

    def known_ids(self) -> set:
        return {r[0] for r in self._conn().execute("SELECT id FROM messages")}

    def sent_contacts(self) -> set:
        out = set()
        for r in self._conn().execute("SELECT recipients, cc FROM messages WHERE is_sent=1"):
            out |= {a.lower() for _, a in getaddresses([r[0] or "", r[1] or ""]) if a}
        return out

    def _where(self, view, text, sender, category, since, until, follow_days):
        w, p = [VIEWS[view]], {}
        if view == "follow_up":
            p["follow_cutoff"] = (datetime.now(timezone.utc) - timedelta(days=follow_days)).strftime(ISO)
        if text:
            w.append("(subject LIKE :t ESCAPE '\\' OR sender_name LIKE :t ESCAPE '\\' OR "
                     "sender_email LIKE :t ESCAPE '\\' OR body LIKE :t ESCAPE '\\')"); p["t"] = _like(text)
        if sender:
            w.append("(sender_name LIKE :s ESCAPE '\\' OR sender_email LIKE :s ESCAPE '\\')"); p["s"] = _like(sender)
        if category:
            w.append("eff_category=:cat"); p["cat"] = category
        if since:
            w.append("date>=:since"); p["since"] = since
        if until:
            w.append("date<=:until"); p["until"] = until
        return " AND ".join(w), p

    def search(self, view="inbox", text="", sender="", category="", since=None, until=None,
               sort="date_desc", limit=2000, follow_days=3):
        where, p = self._where(view, text, sender, category, since, until, follow_days)
        rows = self._conn().execute(
            f"SELECT * FROM v_messages WHERE {where} ORDER BY {SORTS.get(sort, SORTS['date_desc'])} LIMIT {int(limit)}", p)
        return [dict(r) for r in rows]

    def count(self, view="inbox", text="", sender="", category="", since=None, until=None, follow_days=3) -> int:
        where, p = self._where(view, text, sender, category, since, until, follow_days)
        return self._conn().execute(f"SELECT COUNT(*) FROM v_messages WHERE {where}", p).fetchone()[0]
