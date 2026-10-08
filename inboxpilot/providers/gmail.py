"""Gmail via the official Gmail API + OAuth 2.0 (installed-app flow, PKCE).
Only the read-only scope is requested, so the app *cannot* modify or send mail."""
from __future__ import annotations
import base64
import html as htmllib
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from ..models import EmailMessage
from .base import EmailProvider, ProviderError

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_KEY = "gmail:token"
ISO = "%Y-%m-%dT%H:%M:%S"


def _dh(v: str) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def _html_to_text(h: str) -> str:
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", h)
    return re.sub(r"[ \t]+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def _collect(part: dict, out: dict):
    mime, data = part.get("mimeType", ""), (part.get("body") or {}).get("data")
    if data and mime in ("text/plain", "text/html"):
        out.setdefault(mime, "")
        out[mime] += _b64(data)
    for p in part.get("parts", []) or []:
        _collect(p, out)


def message_from_gmail(raw: dict, account: str = "") -> EmailMessage:
    payload = raw.get("payload", {})
    h = {x["name"].lower(): x["value"] for x in payload.get("headers", [])}
    name, addr = parseaddr(_dh(h.get("from", "")))
    try:
        dt = parsedate_to_datetime(h["date"])
        dt = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        dt = datetime.fromtimestamp(int(raw.get("internalDate", 0)) / 1000, timezone.utc)
    parts: dict = {}
    _collect(payload, parts)
    body = parts.get("text/plain") or _html_to_text(parts.get("text/html", ""))
    labels = raw.get("labelIds", [])
    return EmailMessage(
        id=f"gmail:{raw['id']}", thread_id=f"gmail:{raw.get('threadId', raw['id'])}",
        sender_name=name or addr, sender_email=addr.lower(), to=_dh(h.get("to", "")),
        cc=_dh(h.get("cc", "")), subject=_dh(h.get("subject", "")) or "(no subject)",
        date=dt.strftime(ISO), snippet=htmllib.unescape(raw.get("snippet", "")), body=body,
        is_unread="UNREAD" in labels, is_sent="SENT" in labels,
        has_unsubscribe="list-unsubscribe" in h, labels=labels, account=account)


class GmailProvider(EmailProvider):
    key = "gmail"
    display_name = "Gmail"

    def __init__(self, token_store, client_secrets_path: str = ""):
        self.tokens = token_store
        self.client_secrets_path = client_secrets_path
        self.account = ""

    # ---- auth
    def connect(self) -> str:
        if not self.client_secrets_path or not Path(self.client_secrets_path).is_file():
            raise ProviderError("Google OAuth client file (credentials.json) not found. See README, 'Google setup'.")
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_path, SCOPES)
            creds = flow.run_local_server(port=0, timeout_seconds=240, open_browser=True)
        except Exception as e:
            raise ProviderError(f"Sign-in was cancelled or failed: {e}") from e
        self.tokens.set(TOKEN_KEY, creds.to_json())
        svc = self._service()
        try:
            self.account = svc.users().getProfile(userId="me").execute()["emailAddress"].lower()
        except Exception as e:
            raise ProviderError(f"Signed in, but could not read the Gmail profile: {e}") from e
        return self.account

    def is_connected(self) -> bool:
        try:
            return bool(self.tokens.get(TOKEN_KEY))
        except Exception:
            return False

    def disconnect(self) -> None:
        raw = None
        try:
            raw = self.tokens.get(TOKEN_KEY)
        finally:
            self.tokens.delete(TOKEN_KEY)
        if raw:  # best-effort revoke at Google
            try:
                d = json.loads(raw)
                tok = d.get("refresh_token") or d.get("token")
                req = urllib.request.Request(
                    "https://oauth2.googleapis.com/revoke", urllib.parse.urlencode({"token": tok}).encode(),
                    {"Content-Type": "application/x-www-form-urlencoded"})
                urllib.request.urlopen(req, timeout=10).close()
            except Exception:
                pass

    def _service(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        raw = self.tokens.get(TOKEN_KEY)
        if not raw:
            raise ProviderError("Not connected. Click Connect first.")
        creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
        if not creds.valid:
            if creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    raise ProviderError("Your Google session expired or was revoked. Please reconnect.") from e
                self.tokens.set(TOKEN_KEY, creds.to_json())
            else:
                raise ProviderError("Your Google session expired. Please reconnect.")
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    # ---- data
    def fetch_messages(self, known_ids, limit, progress=None):
        from googleapiclient.errors import HttpError
        svc = self._service()
        try:
            for label in ("SENT", "INBOX"):  # sent first so reply detection has context
                page, seen = None, 0
                while seen < limit:
                    resp = svc.users().messages().list(
                        userId="me", labelIds=[label], maxResults=min(100, limit - seen),
                        pageToken=page).execute()
                    for ref in resp.get("messages", []):
                        seen += 1
                        if f"gmail:{ref['id']}" in known_ids:
                            continue
                        raw = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
                        if progress:
                            progress(f"Downloading {label.lower()} mail… {seen}/{limit}")
                        yield message_from_gmail(raw, self.account)
                    page = resp.get("nextPageToken")
                    if not page:
                        break
        except HttpError as e:
            raise ProviderError(f"Gmail API error: {getattr(e, 'reason', e)}") from e

    def list_unread_ids(self, limit):
        from googleapiclient.errors import HttpError
        svc, ids, page = self._service(), set(), None
        try:
            while len(ids) < limit:
                r = svc.users().messages().list(userId="me", labelIds=["INBOX", "UNREAD"],
                                                maxResults=100, pageToken=page).execute()
                ids |= {f"gmail:{m['id']}" for m in r.get("messages", [])}
                page = r.get("nextPageToken")
                if not page:
                    break
        except HttpError as e:
            raise ProviderError(f"Gmail API error: {getattr(e, 'reason', e)}") from e
        return ids
