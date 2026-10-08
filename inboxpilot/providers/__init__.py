from .base import EmailProvider, ProviderError


def create_provider(key: str, token_store, client_secrets_path: str = "") -> EmailProvider:
    if key == "gmail":
        from .gmail import GmailProvider
        return GmailProvider(token_store, client_secrets_path)
    raise ProviderError(f"Unknown provider: {key}")


__all__ = ["EmailProvider", "ProviderError", "create_provider"]
