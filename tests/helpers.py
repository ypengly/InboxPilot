from inboxpilot.models import EmailMessage

ME = "me@acme.com"


def mk(**kw):
    d = dict(id="gmail:1", thread_id="t1", sender_name="Alex Smith", sender_email="alex@acme.com", to=ME, cc="",
             subject="Project update", date="2026-09-01T10:00:00", snippet="", body="", is_unread=True,
             is_sent=False, has_unsubscribe=False, labels=[], account=ME)
    d.update(kw)
    return EmailMessage(**d)
