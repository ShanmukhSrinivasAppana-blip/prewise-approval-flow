"""Unit tests for app/llm.py testing retries, backoff, schema validation, and fallback."""

import os
import unittest
from unittest.mock import patch

from pydantic import BaseModel, Field

from app.llm import (
    LLMResult,
    LLMUnavailableError,
    call_llm_json,
    reset_mock_behavior,
    set_mock_behavior,
)


class SampleSchema(BaseModel):
    """Test schema for structured LLM parsing."""
    title: str = Field(..., description="Request title")
    priority: int = Field(..., ge=1, le=5)
    approved: bool = False


class TestLLMClient(unittest.TestCase):
    """Test suite for LLM retry, backoff, and fallback handling."""

    def setUp(self) -> None:
        reset_mock_behavior()
        self.original_provider = os.environ.get("LLM_PROVIDER")
        self.original_fallback = os.environ.get("LLM_FALLBACK_PROVIDER")
        os.environ["LLM_PROVIDER"] = "mock"
        os.environ["LLM_FALLBACK_PROVIDER"] = ""

    def tearDown(self) -> None:
        reset_mock_behavior()
        if self.original_provider is not None:
            os.environ["LLM_PROVIDER"] = self.original_provider
        else:
            os.environ.pop("LLM_PROVIDER", None)

        if self.original_fallback is not None:
            os.environ["LLM_FALLBACK_PROVIDER"] = self.original_fallback
        else:
            os.environ.pop("LLM_FALLBACK_PROVIDER", None)

    def test_mock_provider_returns_valid_structured_data(self) -> None:
        """Mock provider automatically satisfies the requested Pydantic schema."""
        result = call_llm_json(
            system_prompt="Test system instruction",
            user_content="Laptop budget request",
            schema=SampleSchema,
        )
        self.assertIsInstance(result, LLMResult)
        self.assertIsInstance(result.data, SampleSchema)
        self.assertTrue(len(result.data.title) > 0)
        self.assertGreaterEqual(result.data.priority, 1)
        self.assertLessEqual(result.data.priority, 5)
        self.assertEqual(result.provider, "mock")
        self.assertGreaterEqual(result.latency_s, 0.0)

    def test_retry_on_malformed_json_and_succeed(self) -> None:
        """First attempt yields broken JSON, second attempt yields valid JSON."""
        # 1st call: malformed JSON, 2nd call: valid JSON
        sleep_calls = []
        set_mock_behavior([
            "NOT_JSON_AT_ALL {{{",
            '{"title": "Fixed Title", "priority": 3, "approved": true}',
        ])

        result = call_llm_json(
            system_prompt="Prompt",
            user_content="Content",
            schema=SampleSchema,
            max_retries=3,
            backoff_factor=0.1,
            sleep_fn=lambda s: sleep_calls.append(s),
        )

        self.assertEqual(result.data.title, "Fixed Title")
        self.assertEqual(result.data.priority, 3)
        self.assertTrue(result.data.approved)
        self.assertEqual(len(sleep_calls), 1)  # Slept once after 1st failure

    def test_retry_on_pydantic_validation_error(self) -> None:
        """First attempt violates schema range (priority=99), second attempt succeeds."""
        sleep_calls = []
        set_mock_behavior([
            '{"title": "Invalid Priority", "priority": 99, "approved": false}',
            '{"title": "Valid Priority", "priority": 4, "approved": true}',
        ])

        result = call_llm_json(
            system_prompt="Prompt",
            user_content="Content",
            schema=SampleSchema,
            max_retries=3,
            backoff_factor=0.1,
            sleep_fn=lambda s: sleep_calls.append(s),
        )

        self.assertEqual(result.data.priority, 4)
        self.assertEqual(result.data.title, "Valid Priority")
        self.assertEqual(len(sleep_calls), 1)

    def test_fallback_provider_when_primary_fails_all_retries(self) -> None:
        """Primary provider fails 3 times, fallback provider is invoked and succeeds."""
        os.environ["LLM_PROVIDER"] = "mock"
        os.environ["LLM_FALLBACK_PROVIDER"] = "mock"

        # Provide 3 failing responses followed by 1 valid response
        set_mock_behavior([
            RuntimeError("Provider timeout 1"),
            RuntimeError("Provider timeout 2"),
            RuntimeError("Provider timeout 3"),
            '{"title": "Recovered via Fallback", "priority": 2, "approved": true}',
        ])

        sleep_calls = []
        result = call_llm_json(
            system_prompt="Prompt",
            user_content="Content",
            schema=SampleSchema,
            max_retries=3,
            backoff_factor=0.01,
            sleep_fn=lambda s: sleep_calls.append(s),
        )

        self.assertEqual(result.data.title, "Recovered via Fallback")
        self.assertEqual(result.data.priority, 2)

    def test_llm_unavailable_error_when_all_fail(self) -> None:
        """When all retries and fallback attempts fail, raise LLMUnavailableError."""
        set_mock_behavior([
            RuntimeError("Permanent API 500 error"),
            RuntimeError("Permanent API 500 error"),
            RuntimeError("Permanent API 500 error"),
        ])

        with self.assertRaises(LLMUnavailableError):
            call_llm_json(
                system_prompt="Prompt",
                user_content="Content",
                schema=SampleSchema,
                max_retries=3,
                backoff_factor=0.01,
                sleep_fn=lambda s: None,
            )


if __name__ == "__main__":
    unittest.main()
