from __future__ import annotations
import html
import json
import logging
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..analysis import generate_draft, summarize
from ..models import CATEGORIES, PRIORITIES, EmailMessage
from ..providers import create_provider
from ..workers import ConnectWorker, SyncWorker

log = logging.getLogger("inboxpilot")
ISO = "%Y-%m-%dT%H:%M:%S"
NAV = [("inbox", "Inbox"), ("important", "Important"), ("needs_reply", "Needs Reply"), ("follow_up", "Follow Up"),
       ("newsletters", "Newsletters"), ("receipts", "Receipts"), ("unread", "Unread")]
RANGES = [("Any time", None), ("Today", 1), ("Last 7 days", 7), ("Last 30 days", 30), ("Last year", 365)]
SORTS = [("Newest first", "date_desc"), ("Oldest first", "date_asc"), ("Sender A–Z", "sender"),
         ("Subject A–Z", "subject"), ("Priority", "priority")]
PRIO_COLOR = {"High": "#c0392b", "Medium": "#b9770e", "Low": "#7f8c8d"}


def local_time(iso: str) -> str:
    try:
        return datetime.strptime(iso, ISO).replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso or ""


def esc(s) -> str:
    return html.escape(str(s or ""))


class MainWindow(QMainWindow):
    def __init__(self, db, settings, tokens):
        super().__init__()
        self.db, self.settings, self.tokens = db, settings, tokens
        self.provider = create_provider("gmail", tokens, settings.get("client_secrets_path"))
        self.rows, self.current, self._worker, self._loading = [], None, None, False
        self.setWindowTitle("InboxPilot — Email Command Center")
        self.resize(1400, 840)
        self._build()
        self._update_connection_ui()
        self.refresh()

    @property
    def account(self) -> str:
        return self.settings.get("account") or ""

    # ------------------------------------------------------------------ UI
    def _build(self):
        bar = self.addToolBar("main")
        bar.setMovable(False)
        self.btn_connect = QPushButton("Connect Gmail")
        self.btn_connect.clicked.connect(self.on_connect_clicked)
        self.btn_sync = QPushButton("⟳ Sync")
        self.btn_sync.clicked.connect(self.on_sync)
        self.lbl_account = QLabel("  Not connected")
        for w in (self.btn_connect, self.btn_sync, self.lbl_account):
            bar.addWidget(w)

        self.nav = QListWidget()
        self.nav.setFixedWidth(190)
        for key, label in NAV:
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, key)
            self.nav.addItem(it)
        self.nav.setCurrentRow(0)
        self.nav.currentRowChanged.connect(lambda _: self.refresh())

        self.stat = {}
        cards = QHBoxLayout()
        for key, title in (("unread", "Unread"), ("important", "Important"), ("pending", "Pending replies"),
                           ("recent", "Recent (7 days)")):
            f = QFrame(); f.setFrameShape(QFrame.StyledPanel)
            v = QVBoxLayout(f)
            n = QLabel("0"); n.setFont(QFont("", 20, QFont.Bold))
            v.addWidget(n); v.addWidget(QLabel(title))
            self.stat[key] = n
            cards.addWidget(f)

        self.search = QLineEdit(); self.search.setPlaceholderText("Search subject, sender, body…")
        self.sender = QLineEdit(); self.sender.setPlaceholderText("Filter by sender")
        self.cat = QComboBox(); self.cat.addItem("All categories", ""); [self.cat.addItem(c, c) for c in CATEGORIES]
        self.rng = QComboBox(); [self.rng.addItem(a, b) for a, b in RANGES]
        self.sort = QComboBox(); [self.sort.addItem(a, b) for a, b in SORTS]
        self._timer = QTimer(self, singleShot=True, interval=250, timeout=self.refresh)
        self.search.textChanged.connect(self._timer.start)
        self.sender.textChanged.connect(self._timer.start)
        for c in (self.cat, self.rng, self.sort):
            c.currentIndexChanged.connect(lambda _: self.refresh())
        filters = QHBoxLayout()
        for w in (self.search, self.sender, self.cat, self.rng, self.sort):
            filters.addWidget(w)
        filters.setStretch(0, 3); filters.setStretch(1, 2)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Sender", "Subject", "Date", "Category", "Importance", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for i in (0, 2, 3, 4, 5):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self.on_select)

        mid = QWidget(); ml = QVBoxLayout(mid)
        ml.addLayout(cards); ml.addLayout(filters); ml.addWidget(self.table)

        # detail pane
        self.head = QLabel("Select an email"); self.head.setWordWrap(True); self.head.setTextFormat(Qt.RichText)
        self.cb_cat = QComboBox(); [self.cb_cat.addItem(c) for c in CATEGORIES]
        self.cb_prio = QComboBox(); [self.cb_prio.addItem(p) for p in PRIORITIES]
        self.cb_cat.activated.connect(self.on_category)
        self.cb_prio.activated.connect(self.on_priority)
        self.btn_dismiss = QPushButton("Not needing reply")
        self.btn_dismiss.clicked.connect(self.on_dismiss)
        ov = QHBoxLayout()
        for t, w in (("Category:", self.cb_cat), ("Priority:", self.cb_prio)):
            ov.addWidget(QLabel(t)); ov.addWidget(w)
        ov.addWidget(self.btn_dismiss); ov.addStretch()

        self.tab_info = QTextBrowser(); self.tab_msg = QPlainTextEdit(); self.tab_msg.setReadOnly(True)
        self.draft = QPlainTextEdit()
        self.draft.setPlaceholderText("Click “Generate draft” to create an editable draft.")
        self.btn_gen = QPushButton("Generate draft"); self.btn_edit = QPushButton("Edit")
        self.btn_copy = QPushButton("Copy"); self.btn_save = QPushButton("Save Draft")
        self.btn_gen.clicked.connect(self.on_generate); self.btn_edit.clicked.connect(self.on_edit)
        self.btn_copy.clicked.connect(self.on_copy); self.btn_save.clicked.connect(self.on_save)
        db_ = QHBoxLayout()
        for b in (self.btn_gen, self.btn_edit, self.btn_copy, self.btn_save):
            db_.addWidget(b)
        dw = QWidget(); dl = QVBoxLayout(dw)
        dl.addWidget(QLabel("Drafts are never sent. InboxPilot only has read-only access to your mailbox."))
        dl.addWidget(self.draft); dl.addLayout(db_)
        tabs = QTabWidget()
        tabs.addTab(self.tab_info, "Summary & Priority"); tabs.addTab(self.tab_msg, "Message"); tabs.addTab(dw, "Draft")
        right = QWidget(); rl = QVBoxLayout(right)
        rl.addWidget(self.head); rl.addLayout(ov); rl.addWidget(tabs)

        split = QSplitter()
        split.addWidget(self.nav); split.addWidget(mid); split.addWidget(right)
        split.setStretchFactor(1, 3); split.setStretchFactor(2, 2)
        self.setCentralWidget(split)
        self.statusBar().showMessage("Ready")
        self._set_detail_enabled(False)

    def _set_detail_enabled(self, on):
        for w in (self.cb_cat, self.cb_prio, self.btn_dismiss, self.btn_gen, self.btn_edit, self.btn_copy,
                  self.btn_save, self.draft):
            w.setEnabled(on)

    # ------------------------------------------------------------ listing
    def _filters(self):
        days = self.rng.currentData()
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(ISO) if days else None
        return dict(text=self.search.text().strip(), sender=self.sender.text().strip(),
                    category=self.cat.currentData() or "", since=since)

    def refresh(self):
        item = self.nav.currentItem()
        view = item.data(Qt.UserRole) if item else "inbox"
        keep = self.current["id"] if self.current else None
        try:
            self.rows = self.db.search(view=view, sort=self.sort.currentData(), **self._filters())
            for i, (key, label) in enumerate(NAV):
                self.nav.item(i).setText(f"{label}  ({self.db.count(key)})")
            week = (datetime.now(timezone.utc) - timedelta(days=7)).strftime(ISO)
            self.stat["unread"].setText(str(self.db.count("unread")))
            self.stat["important"].setText(str(self.db.count("important")))
            self.stat["pending"].setText(str(self.db.count("needs_reply")))
            self.stat["recent"].setText(str(self.db.count("inbox", since=week)))
        except Exception as e:
            log.exception("refresh failed")
            self.statusBar().showMessage(f"Database error: {e}")
            return
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rows))
        bold = QFont(); bold.setBold(True)
        for r, row in enumerate(self.rows):
            status = ("Sent" if row["is_sent"] else "Unread" if row["unread"] else "Read")
            if row["needs_reply"]:
                status += " · Needs reply"
            if row["awaiting"]:
                status += " · Awaiting reply"
            vals = [row["sender_name"] or row["sender_email"], row["subject"], local_time(row["date"]),
                    row["eff_category"], row["eff_priority"], status]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if row["unread"] and not row["is_sent"]:
                    it.setFont(bold)
                if c == 4:
                    it.setForeground(QColor(PRIO_COLOR.get(v, "#000")))
                self.table.setItem(r, c, it)
            if row["id"] == keep:
                self.table.selectRow(r)
        self.table.blockSignals(False)
        if not any(r["id"] == keep for r in self.rows):
            self.current = None; self._show(None)
        if not self.rows:
            self.statusBar().showMessage("No messages match." if self.db.count("inbox") else
                                         "No mail yet — connect an account and click Sync.")

    # ------------------------------------------------------------- detail
    def on_select(self):
        sel = self.table.selectionModel().selectedRows()
        self._show(self.db.get(self.rows[sel[0].row()]["id"]) if sel else None)

    def _show(self, row):
        self.current = row
        self._set_detail_enabled(row is not None)
        if row is None:
            self.head.setText("Select an email"); self.tab_info.clear(); self.tab_msg.clear(); self.draft.clear()
            return
        msg = EmailMessage.from_row(row)
        self._loading = True
        self.cb_cat.setCurrentText(row["eff_category"]); self.cb_prio.setCurrentText(row["eff_priority"])
        self._loading = False
        self.btn_dismiss.setVisible(bool(row["needs_reply"]))
        self.head.setText(f"<b>{esc(row['subject'])}</b><br>From: {esc(row['sender_name'])} "
                          f"&lt;{esc(row['sender_email'])}&gt;<br>To: {esc(row['recipients'])}<br>{local_time(row['date'])}")
        s = summarize(msg, self.account)
        reasons = json.loads(row["reasons"] or "[]")
        li = lambda xs: "".join(f"<li>{esc(x)}</li>" for x in xs)
        parts = [f"<h3>Priority: {esc(row['eff_priority'])}"
                 + (" <small>(set by you)</small>" if row["priority_override"] else "") + "</h3>",
                 "<p><b>Reasons:</b></p><ul style='list-style:none'>" + li(reasons) + "</ul>"]
        if row["needs_reply"]:
            parts.append(f"<h3>Needs Reply</h3><p><b>Reason:</b> {esc(row['reply_reason'] or 'Marked by you.')}</p>")
        parts += [f"<h3>Summary</h3><p>{esc(s.summary)}</p>", f"<h3>Key Points</h3><ul>{li(s.key_points)}</ul>",
                  f"<h3>Action Items</h3><ul>{li(s.action_items)}</ul>", f"<h3>Deadline</h3><p>{esc(s.deadline)}</p>",
                  f"<h3>People Mentioned</h3><ul>{li(s.people)}</ul>",
                  "<p><small>Generated locally from the email text; nothing leaves this computer.</small></p>"]
        self.tab_info.setHtml("".join(parts))
        self.tab_msg.setPlainText(row["body"] or row["snippet"] or "")
        self.draft.setPlainText(self.db.get_draft(row["id"]) or "")

    def on_category(self):
        if self.current and not self._loading:
            self.db.set_category(self.current["id"], self.cb_cat.currentText()); self._after_edit()

    def on_priority(self):
        if self.current and not self._loading:
            self.db.set_priority(self.current["id"], self.cb_prio.currentText()); self._after_edit()

    def on_dismiss(self):
        if self.current:
            self.db.dismiss_reply(self.current["id"]); self._after_edit()

    def _after_edit(self):
        mid = self.current["id"]
        self.refresh()
        self._show(self.db.get(mid))

    # -------------------------------------------------------------- draft
    def on_generate(self):
        if self.current:
            if self.draft.toPlainText().strip() and QMessageBox.question(
                    self, "Replace draft?", "Replace the current draft text?") != QMessageBox.Yes:
                return
            self.draft.setPlainText(generate_draft(EmailMessage.from_row(self.current), self.account))
            self.statusBar().showMessage("Draft generated. Review and edit it — it will not be sent.")

    def on_edit(self):
        self.draft.setFocus(); self.draft.moveCursor(self.draft.textCursor().MoveOperation.End)

    def on_copy(self):
        QGuiApplication.clipboard().setText(self.draft.toPlainText())
        self.statusBar().showMessage("Draft copied to clipboard.")

    def on_save(self):
        if self.current:
            self.db.save_draft(self.current["id"], self.draft.toPlainText())
            self.statusBar().showMessage("Draft saved locally (not in your mailbox).")

    # ---------------------------------------------------- account / sync
    def _update_connection_ui(self):
        on = bool(self.account) and self.provider.is_connected()
        self.btn_connect.setText("Disconnect" if on else "Connect Gmail")
        self.btn_sync.setEnabled(on)
        self.lbl_account.setText(f"  Connected: {self.account}" if on else "  Not connected")

    def on_connect_clicked(self):
        if self.btn_connect.text() == "Disconnect":
            return self.on_disconnect()
        path = self.settings.get("client_secrets_path")
        if not path:
            QMessageBox.information(self, "Google setup", "Choose the OAuth client file (credentials.json) you "
                                    "downloaded from Google Cloud Console. See the README, “Google setup”.")
            path, _ = QFileDialog.getOpenFileName(self, "Select credentials.json", "", "JSON (*.json)")
            if not path:
                return
            self.settings.set("client_secrets_path", path)
            self.provider.client_secrets_path = path
        self.btn_connect.setEnabled(False)
        self.statusBar().showMessage("Complete sign-in in your browser…")
        self._worker = ConnectWorker(self.provider)
        self._worker.connected.connect(self._on_connected)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_connected(self, account):
        self.settings.set("account", account)
        self.btn_connect.setEnabled(True)
        self._update_connection_ui()
        self.on_sync()

    def on_disconnect(self):
        box = QMessageBox(QMessageBox.Question, "Disconnect", f"Disconnect {self.account}?\n\nAccess is revoked and "
                          "the stored token is deleted. You can also remove the downloaded mail from this computer.", parent=self)
        keep = box.addButton("Disconnect, keep local data", QMessageBox.AcceptRole)
        wipe = box.addButton("Disconnect and delete local data", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() not in (keep, wipe):
            return
        try:
            self.provider.disconnect()
        except Exception as e:
            QMessageBox.warning(self, "Disconnect", f"Could not fully disconnect: {e}")
            return
        if box.clickedButton() is wipe:
            self.db.clear_all()
        self.settings.set("account", "")
        self._update_connection_ui(); self.refresh()
        self.statusBar().showMessage("Disconnected.")

    def on_sync(self):
        if self._worker and self._worker.isRunning():
            return
        self.btn_sync.setEnabled(False)
        self._worker = SyncWorker(self.provider, self.db, self.account, int(self.settings.get("sync_limit")))
        self._worker.progress.connect(self.statusBar().showMessage)
        self._worker.done.connect(self._on_synced)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_synced(self, n):
        self.btn_sync.setEnabled(True)
        self.statusBar().showMessage(f"Sync complete — {n} new message(s).")
        self.refresh()

    def _on_failed(self, msg):
        self.btn_connect.setEnabled(True)
        self._update_connection_ui()
        self.statusBar().showMessage("Error: " + msg)
        QMessageBox.warning(self, "InboxPilot", msg)
