from inboxpilot.analysis import analyze, summarize, generate_draft, find_deadline, NO_DEADLINE
from helpers import mk, ME


def test_no_deadline_is_stated_not_invented():
    s = summarize(mk(body="Just sharing the notes from today's chat. Nothing else to add here."), ME)
    assert s.deadline == NO_DEADLINE
    assert s.action_items == ["No action items identified."]


def test_deadline_extracted_verbatim():
    assert find_deadline("Please send the report by Friday.") == "by Friday"
    assert find_deadline("Review before March 5, 2026? Thanks") == "before March 5, 2026"
    assert find_deadline("Deadline: 2026-10-01 at noon").lower().startswith("deadline")
    assert find_deadline("We talked about Fridays.") is None


def test_question_flags_needs_reply_with_reason():
    a = analyze(mk(body="Hi, are you free to review the draft this week? Let me know."), ME)
    assert a.reply_candidate and a.reply_reason == "Question detected in message."


def test_high_priority_has_explained_reasons():
    a = analyze(mk(body="Can you send the numbers by Friday? This is urgent."), ME)
    assert a.priority == "High"
    text = " ".join(a.reasons)
    assert "Directly addressed" in text and "requested action" in text and "deadline" in text


def test_newsletter_is_low_and_never_needs_reply():
    a = analyze(mk(sender_email="news@shop.com", has_unsubscribe=True, body="Big sale! Would you like 20% off?"), ME)
    assert a.category == "Newsletter" and a.priority == "Low" and not a.reply_candidate


def test_receipt_detected():
    a = analyze(mk(sender_email="no-reply@acme-store.com", subject="Your receipt from Acme",
                   body="Thank you for your purchase. Total $12.00"), ME)
    assert a.is_receipt and a.category in ("Finance", "Shopping") and not a.reply_candidate


def test_quoted_text_is_ignored():
    a = analyze(mk(body="Sounds good, thanks.\n\nOn Mon, Alex wrote:\n> Can you send it by Friday?"), ME)
    assert not a.reply_candidate and a.deadline is None


def test_draft_is_template_with_placeholders_and_no_invented_commitments():
    d = generate_draft(mk(body="Can you confirm the budget by Friday?"), ME)
    assert d.startswith("Hi Alex,") and "[Your answer]" in d and "by Friday" in d and "[Your name]" in d


def test_people_only_from_message():
    s = summarize(mk(cc="Dana Lee <dana@acme.com>", body="Hello.\n\nThanks,\nAlex Smith"), ME)
    assert "Alex Smith" in s.people and "Dana Lee" in s.people and len(s.people) == 2
