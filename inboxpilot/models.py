from __future__ import annotations
from dataclasses import dataclass, field

CATEGORIES = ["Work", "Personal", "Finance", "Shopping", "Newsletter", "Social",
              "Travel", "Notifications", "Important", "Needs Reply"]
PRIORITIES = ["High", "Medium", "Low"]


@dataclass
class EmailMessage:
    id: str                      # globally unique: "<provider>:<provider id>"
    thread_id: str
    sender_name: str
    sender_email: str
    to: str
    cc: str
    subject: str
    date: str                    # ISO-8601 UTC, "YYYY-MM-DDTHH:MM:SS"
    snippet: str = ""
    body: str = ""
    is_unread: bool = False
    is_sent: bool = False
    has_unsubscribe: bool = False
    labels: list = field(default_factory=list)
    account: str = ""

    @classmethod
    def from_row(cls, r: dict) -> "EmailMessage":
        return cls(id=r["id"], thread_id=r["thread_id"], sender_name=r["sender_name"] or "",
                   sender_email=r["sender_email"] or "", to=r["recipients"] or "", cc=r["cc"] or "",
                   subject=r["subject"] or "", date=r["date"], snippet=r["snippet"] or "",
                   body=r["body"] or "", is_unread=bool(r["unread"]), is_sent=bool(r["is_sent"]),
                   account=r["account"])
