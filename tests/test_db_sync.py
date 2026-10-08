from inboxpilot.analysis import analyze
from inboxpilot.db import Database
from inboxpilot.providers.base import EmailProvider
from inboxpilot.sync import sync_account
from helpers import mk, ME


def put(db, **kw):
    m = mk(**kw)
    db.upsert(m, analyze(m, ME))
    return m


def test_reply_clears_needs_reply_and_creates_follow_up(tmp_path):
    db = Database(tmp_path / "t.db")
    put(db, id="gmail:a", thread_id="T1", body="Can you send the file?")
    put(db, id="gmail:b", thread_id="T2", body="Can you send the file?")
    assert db.count("needs_reply") == 2
    put(db, id="gmail:c", thread_id="T1", is_sent=True, sender_email=ME, to="alex@acme.com",
        date="2026-09-02T10:00:00", body="Here it is.")
    assert [r["id"] for r in db.search("needs_reply")] == ["gmail:b"]
    put(db, id="gmail:d", thread_id="T3", is_sent=True, sender_email=ME, to="bob@x.com",
        date="2026-01-01T10:00:00", body="Any news?")
    assert {r["id"] for r in db.search("follow_up")} == {"gmail:c", "gmail:d"}  # sent, old, no answer
    assert db.count("follow_up", follow_days=100000) == 0                       # age threshold respected


def test_overrides_survive_resync_and_drive_views(tmp_path):
    db = Database(tmp_path / "t.db")
    m = put(db, body="Hello there, just a note.")
    db.set_priority(m.id, "High"); db.set_category(m.id, "Finance")
    put(db, body="Hello there, just a note.")  # re-sync
    r = db.get(m.id)
    assert r["eff_priority"] == "High" and r["eff_category"] == "Finance"
    assert db.count("important") == 1
    db.dismiss_reply(m.id)
    assert db.count("needs_reply") == 0


def test_search_filters_and_wildcards_are_literal(tmp_path):
    db = Database(tmp_path / "t.db")
    put(db, id="gmail:1", subject="Budget 100% done", date="2026-09-01T10:00:00")
    put(db, id="gmail:2", subject="Lunch", sender_name="Zed", sender_email="zed@x.com", date="2026-05-01T10:00:00")
    assert db.count("inbox", text="100%") == 1
    assert db.count("inbox", text="%") == 1             # only the literal %
    assert [r["id"] for r in db.search(sender="zed")] == ["gmail:2"]
    assert [r["id"] for r in db.search(since="2026-08-01T00:00:00")] == ["gmail:1"]
    assert [r["id"] for r in db.search(sort="date_asc")] == ["gmail:2", "gmail:1"]


def test_drafts_persist(tmp_path):
    db = Database(tmp_path / "t.db")
    db.save_draft("gmail:1", "v1"); db.save_draft("gmail:1", "v2")
    assert db.get_draft("gmail:1") == "v2" and db.get_draft("nope") is None


class Fake(EmailProvider):
    def __init__(self): self.msgs = [mk(id="gmail:s", is_sent=True, sender_email=ME, to="alex@acme.com",
                                        thread_id="X", body="hi"), mk(id="gmail:i", body="Question here, ok?")]
    def connect(self): return ME
    def disconnect(self): pass
    def is_connected(self): return True
    def fetch_messages(self, known_ids, limit, progress=None):
        yield from (m for m in self.msgs if m.id not in known_ids)
    def list_unread_ids(self, limit): return {"gmail:i"}


def test_sync_is_incremental_and_updates_unread(tmp_path):
    db, p = Database(tmp_path / "t.db"), Fake()
    assert sync_account(p, db, ME) == 2
    assert sync_account(p, db, ME) == 0
    assert db.count("unread") == 1
    assert "alex@acme.com" in db.sent_contacts()
