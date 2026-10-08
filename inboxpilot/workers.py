from __future__ import annotations
import logging
from PySide6.QtCore import QThread, Signal
from .sync import sync_account

log = logging.getLogger("inboxpilot")


class SyncWorker(QThread):
    progress = Signal(str)
    done = Signal(int)
    failed = Signal(str)

    def __init__(self, provider, db, account, limit):
        super().__init__()
        self.provider, self.db, self.account, self.limit = provider, db, account, limit

    def run(self):
        try:
            self.done.emit(sync_account(self.provider, self.db, self.account, self.limit, self.progress.emit))
        except Exception as e:  # surfaced to the user, details in log
            log.exception("sync failed")
            self.failed.emit(str(e) or e.__class__.__name__)


class ConnectWorker(QThread):
    connected = Signal(str)
    failed = Signal(str)

    def __init__(self, provider):
        super().__init__()
        self.provider = provider

    def run(self):
        try:
            self.connected.emit(self.provider.connect())
        except Exception as e:
            log.exception("connect failed")
            self.failed.emit(str(e) or e.__class__.__name__)
