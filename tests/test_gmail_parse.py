import base64
from inboxpilot.providers.gmail import message_from_gmail


def b64(s): return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def test_parses_multipart_message():
    raw = {"id": "9", "threadId": "T", "labelIds": ["INBOX", "UNREAD"], "snippet": "Hi &amp; bye",
           "payload": {"mimeType": "multipart/alternative", "headers": [
               {"name": "From", "value": "Alex Smith <Alex@Acme.com>"}, {"name": "To", "value": "me@acme.com"},
               {"name": "Subject", "value": "=?utf-8?q?Caf=C3=A9?="}, {"name": "Date", "value": "Tue, 1 Sep 2026 10:00:00 +0200"},
               {"name": "List-Unsubscribe", "value": "<mailto:x@y>"}],
               "parts": [{"mimeType": "text/html", "body": {"data": b64("<p>Hello<br>there</p>")}},
                         {"mimeType": "text/plain", "body": {"data": b64("Plain body")}}]}}
    m = message_from_gmail(raw, "me@acme.com")
    assert (m.id, m.thread_id, m.sender_email, m.subject) == ("gmail:9", "gmail:T", "alex@acme.com", "Café")
    assert m.date == "2026-09-01T08:00:00" and m.body == "Plain body"
    assert m.is_unread and not m.is_sent and m.has_unsubscribe and m.snippet == "Hi & bye"


def test_html_only_and_missing_date():
    raw = {"id": "1", "internalDate": "1788000000000", "payload": {"mimeType": "text/html", "headers": [],
           "body": {"data": b64("<div>Only <b>html</b></div>")}}}
    m = message_from_gmail(raw)
    assert "Only html" in m.body and m.subject == "(no subject)" and m.date.startswith("2026")
