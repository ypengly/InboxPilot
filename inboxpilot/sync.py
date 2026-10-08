"""Qt-free synchronisation so it can be tested and reused by any provider."""
from __future__ import annotations
from email.utils import getaddresses
from .analysis import analyze
from .providers.base import EmailProvider


def sync_account(provider: EmailProvider, db, account: str, limit: int = 300, progress=None) -> int:
    known = db.known_ids()
    contacts = db.sent_contacts()
    new = 0
    for msg in provider.fetch_messages(known, limit, progress):
        if msg.is_sent:
            contacts |= {a.lower() for _, a in getaddresses([msg.to, msg.cc]) if a}
        db.upsert(msg, analyze(msg, account, contacts))
        new += 1
    unread = provider.list_unread_ids(500)
    db.refresh_unread(unread, complete=len(unread) < 500)
    return new
