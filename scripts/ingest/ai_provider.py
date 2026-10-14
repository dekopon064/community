"""Fail-closed explicit AI provider selection. No provider or credential fallback."""

from __future__ import annotations

import os

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"
PROVIDER_CHATGPT_PLAN = "chatgpt_plan"
ALLOWED_PROVIDERS = frozenset({PROVIDER_ANTHROPIC, PROVIDER_OPENAI, PROVIDER_CHATGPT_PLAN})
AI_PROVIDER_ENV = "AI_PROVIDER"
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"

MISSING_AI_PROVIDER = "missing_ai_provider"
INVALID_AI_PROVIDER = "invalid_ai_provider"
MISSING_ANTHROPIC_API_KEY = "missing_anthropic_api_key"
MISSING_OPENAI_API_KEY = "missing_openai_api_key"


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
) -> str | None:
    env = os.environ if environ is None else environ
    if provider not in ALLOWED_PROVIDERS:
        raise ProviderError(INVALID_AI_PROVIDER)
    if provider == PROVIDER_CHATGPT_PLAN:
        return None  # OAuth only; never inspect/fall back to either API key.
    key_env = OPENAI_API_KEY_ENV if provider == PROVIDER_OPENAI else ANTHROPIC_API_KEY_ENV
    key = env.get(key_env)
    if key is None or not str(key).strip():
        raise ProviderError(MISSING_OPENAI_API_KEY if provider == PROVIDER_OPENAI else MISSING_ANTHROPIC_API_KEY)
    return str(key)


def require_configured_provider(
    environ: dict[str, str] | None = None,
) -> tuple[str, str | None]:
    provider = require_ai_provider(environ)
    return provider, require_provider_key(provider, environ)


def create_provider_adapter(provider: str, api_key: str | None, *, client=None, plan_session=None):
    """Lazy construction only after explicit execution; never load env files."""
    if provider == PROVIDER_CHATGPT_PLAN:
        from ingest.chatgpt_plan_auth import authenticate_worker
        from ingest.ai_chatgpt_plan import ChatGPTPlanAdapter
        if api_key is not None:
            raise ProviderError("chatgpt_plan_api_key_forbidden")
        session = plan_session if plan_session is not None else authenticate_worker()
        try:
            return ChatGPTPlanAdapter(session=session, client=client)
        except Exception:
            if hasattr(session, 'clear'):
                session.clear()
            raise
    if provider == PROVIDER_OPENAI:
        from ingest.ai_openai import OpenAIAdapter
        return OpenAIAdapter(api_key=api_key, client=client)
    if provider == PROVIDER_ANTHROPIC:
        from ingest.ai_claude import ClaudeAdapter
        return ClaudeAdapter(api_key=api_key, client=client)
    raise ProviderError(INVALID_AI_PROVIDER)


def close_provider_adapter(adapter):
    """Clear runtime plan credentials; protected registration survives closure."""
    close = getattr(adapter, 'close', None)
    if close is not None:
        close()


def provider_validation_limits():
    """Non-executing CLI display; no credential access or login."""
    if os.environ.get(AI_PROVIDER_ENV, '').strip().lower() == PROVIDER_CHATGPT_PLAN:
        return {'usd_cap':None, 'billing':'chatgpt_plan',
                'output_limit_enforcement':'post_completion', 'max_generation_calls':2}
    return {'usd_cap':0.10}
