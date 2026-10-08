import pytest

pytest.importorskip("PySide6")
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from inboxpilot.analysis import analyze
from inboxpilot.config import Settings
from inboxpilot.db import Database
from inboxpilot.ui.main_window import MainWindow
from helpers import mk, ME


class NoTokens:
    def get(self, k): return None
    def set(self, k, v): pass
    def delete(self, k): pass


def test_window_lists_selects_edits_and_saves_draft(tmp_path):
    app = QApplication.instance() or QApplication([])
    db = Database(tmp_path / "t.db")
    for i, body in enumerate(["Can you send the report by Friday?", "Thanks for yesterday."]):
        m = mk(id=f"gmail:{i}", thread_id=f"T{i}", body=body, date=f"2026-09-0{i + 1}T10:00:00")
        db.upsert(m, analyze(m, ME))
    s = Settings(tmp_path / "s.json"); s.set("account", ME)
    w = MainWindow(db, s, NoTokens())
    assert w.table.rowCount() == 2 and w.stat["pending"].text() == "1"
    w.table.selectRow(0); app.processEvents()
    assert w.current and "Deadline" in w.tab_info.toPlainText()
    w.on_generate(); assert w.draft.toPlainText().startswith("Hi Alex")
    w.on_save(); assert db.get_draft(w.current["id"])
    w.cb_prio.setCurrentText("Low"); w.on_priority()
    assert db.get(w.current["id"])["priority_override"] == "Low"
    w.nav.setCurrentRow(2); app.processEvents()           # Needs Reply view
    assert w.table.rowCount() == 1
    w.search.setText("zzz"); w.refresh(); assert w.table.rowCount() == 0
