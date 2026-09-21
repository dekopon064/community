"""Fail-closed AI provider selection. No credential cross-fallback."""

from __future__ import annotations

import os

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GEMINI = "gemini"
ALLOWED_PROVIDERS = frozenset({PROVIDER_ANTHROPIC, PROVIDER_GEMINI})
AI_PROVIDER_ENV = "AI_PROVIDER"
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"

MISSING_AI_PROVIDER = "missing_ai_provider"
INVALID_AI_PROVIDER = "invalid_ai_provider"
MISSING_ANTHROPIC_API_KEY = "missing_anthropic_api_key"
MISSING_GEMINI_API_KEY = "missing_gemini_api_key"


class ProviderError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.code!r})"


def require_ai_provider(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    raw = env.get(AI_PROVIDER_ENV)
    if raw is None or not str(raw).strip():
        raise ProviderError(MISSING_AI_PROVIDER)
    value = str(raw).strip().lower()
    if value not in ALLOWED_PROVIDERS:
        raise ProviderError(INVALID_AI_PROVIDER)
    return value


def require_provider_key(
    provider: str,
    environ: dict[str, str] | None = None,
) -> str:
    env = os.environ if environ is None else environ
    if provider == PROVIDER_ANTHROPIC:
        key = env.get(ANTHROPIC_API_KEY_ENV)
        if key is None or not str(key).strip():
            raise ProviderError(MISSING_ANTHROPIC_API_KEY)
        return str(key)
    if provider == PROVIDER_GEMINI:
        key = env.get(GEMINI_API_KEY_ENV)
        if key is None or not str(key).strip():
            raise ProviderError(MISSING_GEMINI_API_KEY)
        return str(key)
    raise ProviderError(INVALID_AI_PROVIDER)


def require_configured_provider(
    environ: dict[str, str] | None = None,
) -> tuple[str, str]:
    provider = require_ai_provider(environ)
    return provider, require_provider_key(provider, environ)
