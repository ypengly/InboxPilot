from __future__ import annotations
import json
import os
from pathlib import Path


def data_dir() -> Path:
    p = Path(os.environ.get("INBOXPILOT_HOME") or Path.home() / ".inboxpilot")
    p.mkdir(parents=True, exist_ok=True)
    return p


class Settings:
    """Non-secret settings only (OAuth tokens live in the OS credential store)."""
    DEFAULTS = {"client_secrets_path": "", "account": "", "sync_limit": 300}

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else data_dir() / "settings.json"
        self.data = dict(self.DEFAULTS)
        try:
            self.data.update(json.loads(self.path.read_text("utf-8")))
        except (OSError, ValueError):
            pass

    def get(self, key):
        return self.data.get(key, self.DEFAULTS.get(key))

    def set(self, key, value):
        self.data[key] = value
        self.path.write_text(json.dumps(self.data, indent=2), "utf-8")
