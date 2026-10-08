from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable, Iterator
from ..models import EmailMessage


class ProviderError(RuntimeError):
    """Raised with a user-presentable message."""


class EmailProvider(ABC):
    """Implement this to add a provider (Outlook/Microsoft Graph, IMAP+OAuth...).
    Providers must be read-only: InboxPilot never sends, deletes or modifies mail."""
    key: str = ""
    display_name: str = ""

    @abstractmethod
    def connect(self) -> str:
        """Run OAuth, store tokens securely, return the account email address."""

    @abstractmethod
    def disconnect(self) -> None:
        """Revoke access where possible and delete stored tokens."""

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def fetch_messages(self, known_ids: set, limit: int,
                       progress: Callable[[str], None] | None = None) -> Iterator[EmailMessage]:
        """Yield NEW messages (skip known_ids). Sent mail must come before inbox mail."""

    @abstractmethod
    def list_unread_ids(self, limit: int) -> set:
        """Ids (same format as EmailMessage.id) of currently unread inbox messages."""
