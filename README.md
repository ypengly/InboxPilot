# InboxPilot 📧 — Email Command Center

A desktop app (Python 3.11+, PySide6, SQLite) that syncs your Gmail inbox read-only and turns it into
a prioritized dashboard: Inbox · Important · Needs Reply · Follow Up · Newsletters · Receipts · Unread.

## Privacy & safety model
- **Official Gmail API + OAuth 2.0** (browser sign-in, PKCE). Your password is never requested or stored.
- **Read-only scope** (`gmail.readonly`): the app is technically unable to send, delete, archive or modify mail.
- Tokens are stored only in the **OS credential store** (Windows Credential Manager / Keychain / Secret Service).
  If none is available, the app refuses to store tokens rather than writing them to disk.
- **Disconnect** revokes the token at Google, deletes it locally, and optionally wipes the local mail cache.
- Analysis runs **locally**; no email content is sent to any third-party service.
- Drafts are only text in the app: **Edit / Copy / Save Draft**. Saved drafts live in the local database, not in Gmail.

## Google setup (one time)
1. Google Cloud Console → create a project → **APIs & Services → Library** → enable **Gmail API**.
2. **OAuth consent screen**: External, add yourself as a *Test user*, add scope `.../auth/gmail.readonly`.
3. **Credentials → Create credentials → OAuth client ID → Desktop app** → download `credentials.json`.
4. Start InboxPilot → **Connect Gmail** → pick `credentials.json` → sign in in your browser.
   (`credentials.json` identifies the app, not you; keep it out of version control.)

## Run
```
python -m venv .venv && .venv\Scripts\activate     # source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
python run.py
```
Data lives in `~/.inboxpilot/` (override with `INBOXPILOT_HOME`): `inboxpilot.db`, `settings.json`, `inboxpilot.log`.

## Tests
```
pip install -r requirements-dev.txt
pytest
```
Covers analysis rules, DB filters/overrides/reply logic, incremental sync (fake provider), Gmail message parsing,
and a headless UI smoke test (set `QT_QPA_PLATFORM=offscreen` on servers).

## Windows packaging
In a venv with `requirements-dev.txt`: run `build_windows.bat` → `dist\InboxPilot\InboxPilot.exe`
(PyInstaller, windowed). Wrap the folder with Inno Setup for an installer if desired.

## How the analysis works (and its limits)
Rule-based and deterministic, so every result is traceable to text in the message.
- **Priority** = High/Medium/Low from a score; the UI lists every reason (✓ direct recipient, requested action,
  question, deadline, urgent wording, prior correspondence; – bulk/automated sender). Override anytime.
- **Needs Reply**: a question or request addressed to you, from a non-automated sender, with no later sent message
  in the thread. **Follow Up**: your sent messages with no reply after 3+ days.
- **Deadline**: the exact phrase found (“by Friday”) or `No deadline identified.`
- **Summary / Key points / Action items / People** are extracted from the message text; empty sections say so.
- **Suggested response** is a template with `[placeholders]` for anything the app cannot know.
- Heuristics make mistakes (sarcasm, other languages, unusual phrasing) — hence category/priority overrides.
- The optional AI API is **not** wired in; `analysis.summarize()` / `generate_draft()` are the seams to replace.

## Layout
```
inboxpilot/
  providers/base.py   EmailProvider interface   providers/gmail.py   Gmail implementation
  analysis.py         categorize, priority, follow-up, summaries, drafts
  db.py               SQLite schema, views, search     sync.py   provider-agnostic sync
  security.py         OS keyring token store           workers.py   Qt background threads
  ui/main_window.py   PySide6 interface
```
**Adding a provider** (e.g. Outlook via Microsoft Graph): subclass `EmailProvider`, register it in
`providers/__init__.py:create_provider`, and give message ids a `"<provider>:"` prefix.

## Known limitations
- Gmail only for now; syncs the latest N (default 300) inbox and sent messages per run (`sync_limit` in settings.json).
- Only new messages are downloaded; read/unread state is refreshed each sync, edits to old messages are not.
- Not yet verified against a live Google account in this build environment — see “Google setup” to try it.
