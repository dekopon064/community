"""Fail-closed AI provider selection tests. 실제 API·DB를 쓰지 않는다."""

from __future__ import annotations

import inspect
import unittest

from ingest.ai_provider import (
    INVALID_AI_PROVIDER,
    MISSING_AI_PROVIDER,
    MISSING_ANTHROPIC_API_KEY,
    PROVIDER_ANTHROPIC,
    ProviderError,
    require_ai_provider,
    require_configured_provider,
    require_provider_key,
)


class ProviderSelectionTests(unittest.TestCase):
    def test_missing_provider_does_not_read_keys(self) -> None:
        env = {
            "ANTHROPIC_API_KEY": "anthropic-secret-marker",
            "GEMINI_API_KEY": "gemini-secret-marker",
        }
        with self.assertRaises(ProviderError) as caught:
            require_ai_provider(env)
        self.assertEqual(caught.exception.code, MISSING_AI_PROVIDER)
        self.assertNotIn("anthropic-secret-marker", str(caught.exception))
        self.assertNotIn("gemini-secret-marker", str(caught.exception))

    def test_invalid_provider_is_fail_closed(self) -> None:
        for value in ("claude", "gemini", "openai", "Gemini"):
            env = {"AI_PROVIDER": value, "ANTHROPIC_API_KEY": "x"}
            with self.assertRaises(ProviderError) as caught:
                require_ai_provider(env)
            self.assertEqual(caught.exception.code, INVALID_AI_PROVIDER, value)

    def test_gemini_is_invalid_even_with_anthropic_key(self) -> None:
        env = {"AI_PROVIDER": "gemini", "ANTHROPIC_API_KEY": "anthropic-only"}
        with self.assertRaises(ProviderError) as caught:
            require_configured_provider(env)
        self.assertEqual(caught.exception.code, INVALID_AI_PROVIDER)
        self.assertNotIn("anthropic-only", str(caught.exception))

    def test_anthropic_does_not_fall_back_to_another_key(self) -> None:
        env = {"AI_PROVIDER": "anthropic", "GEMINI_API_KEY": "gemini-only"}
        with self.assertRaises(ProviderError) as caught:
            require_configured_provider(env)
        self.assertEqual(caught.exception.code, MISSING_ANTHROPIC_API_KEY)
        self.assertNotIn("gemini-only", str(caught.exception))

    def test_anthropic_configured_returns_its_own_key(self) -> None:
        anthropic = require_configured_provider(
            {
                "AI_PROVIDER": "anthropic",
                "ANTHROPIC_API_KEY": "anthropic-ok",
                "GEMINI_API_KEY": "gemini-unused",
            }
        )
        self.assertEqual(anthropic, (PROVIDER_ANTHROPIC, "anthropic-ok"))

    def test_provider_key_rejects_unknown_provider(self) -> None:
        for provider in ("openai", "gemini"):
            with self.assertRaises(ProviderError) as caught:
                require_provider_key(provider, {"ANTHROPIC_API_KEY": "x"})
            self.assertEqual(caught.exception.code, INVALID_AI_PROVIDER, provider)

    def test_module_has_no_network_imports(self) -> None:
        import ingest.ai_provider as module

        source = inspect.getsource(module)
        self.assertNotIn("import fetch_and_save", source)
        self.assertNotIn("from fetch_and_save", source)
        self.assertNotIn("import google", source)
        self.assertNotIn("from google", source)
        self.assertNotIn("import anthropic", source)
        self.assertNotIn("from anthropic", source)
        self.assertNotIn("import supabase", source)
        self.assertNotIn("from supabase", source)
        self.assertNotIn("GEMINI_API_KEY", source)
        self.assertNotIn("PROVIDER_GEMINI", source)
        self.assertNotIn("google-genai", source)


if __name__ == "__main__":
    unittest.main()
