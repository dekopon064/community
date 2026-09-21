"""Fail-closed AI provider selection tests. 실제 API·DB를 쓰지 않는다."""

from __future__ import annotations

import inspect
import unittest

from ingest.ai_provider import (
    INVALID_AI_PROVIDER,
    MISSING_AI_PROVIDER,
    MISSING_ANTHROPIC_API_KEY,
    MISSING_GEMINI_API_KEY,
    PROVIDER_ANTHROPIC,
    PROVIDER_GEMINI,
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
        env = {"AI_PROVIDER": "claude", "ANTHROPIC_API_KEY": "x"}
        with self.assertRaises(ProviderError) as caught:
            require_ai_provider(env)
        self.assertEqual(caught.exception.code, INVALID_AI_PROVIDER)

    def test_anthropic_does_not_fall_back_to_gemini_key(self) -> None:
        env = {"AI_PROVIDER": "anthropic", "GEMINI_API_KEY": "gemini-only"}
        with self.assertRaises(ProviderError) as caught:
            require_configured_provider(env)
        self.assertEqual(caught.exception.code, MISSING_ANTHROPIC_API_KEY)

    def test_gemini_does_not_fall_back_to_anthropic_key(self) -> None:
        env = {"AI_PROVIDER": "gemini", "ANTHROPIC_API_KEY": "anthropic-only"}
        with self.assertRaises(ProviderError) as caught:
            require_configured_provider(env)
        self.assertEqual(caught.exception.code, MISSING_GEMINI_API_KEY)

    def test_configured_providers_return_matching_keys_only(self) -> None:
        anthropic = require_configured_provider(
            {
                "AI_PROVIDER": "anthropic",
                "ANTHROPIC_API_KEY": "anthropic-ok",
                "GEMINI_API_KEY": "gemini-unused",
            }
        )
        gemini = require_configured_provider(
            {
                "AI_PROVIDER": "gemini",
                "ANTHROPIC_API_KEY": "anthropic-unused",
                "GEMINI_API_KEY": "gemini-ok",
            }
        )
        self.assertEqual(anthropic, (PROVIDER_ANTHROPIC, "anthropic-ok"))
        self.assertEqual(gemini, (PROVIDER_GEMINI, "gemini-ok"))

    def test_provider_key_rejects_unknown_provider(self) -> None:
        with self.assertRaises(ProviderError) as caught:
            require_provider_key("openai", {"OPENAI_API_KEY": "x"})
        self.assertEqual(caught.exception.code, INVALID_AI_PROVIDER)

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


if __name__ == "__main__":
    unittest.main()
