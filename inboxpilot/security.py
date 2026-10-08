from __future__ import annotations


class SecureStorageError(RuntimeError):
    pass


class TokenStore:
    """OAuth tokens in the OS credential store (Windows Credential Manager,
    macOS Keychain, Secret Service). Never falls back to plaintext files."""
    SERVICE = "InboxPilot"

    def _kr(self):
        try:
            import keyring
            from keyring.backends.fail import Keyring as FailKeyring
        except ImportError as e:  # pragma: no cover
            raise SecureStorageError("The 'keyring' package is not installed.") from e
        if isinstance(keyring.get_keyring(), FailKeyring):
            raise SecureStorageError("No secure credential storage is available on this system.")
        return keyring

    def get(self, key: str):
        try:
            return self._kr().get_password(self.SERVICE, key)
        except SecureStorageError:
            raise
        except Exception as e:
            raise SecureStorageError(f"Could not read credential store: {e}") from e

    def set(self, key: str, value: str):
        try:
            self._kr().set_password(self.SERVICE, key, value)
        except SecureStorageError:
            raise
        except Exception as e:
            raise SecureStorageError(f"Could not write credential store: {e}") from e

    def delete(self, key: str):
        try:
            self._kr().delete_password(self.SERVICE, key)
        except SecureStorageError:
            raise
        except Exception:
            pass  # already gone
