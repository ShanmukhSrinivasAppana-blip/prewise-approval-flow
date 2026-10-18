"""LLM client abstraction supporting Gemini, Ollama, and Mock providers.

Provides structured JSON output with automatic retries, backoff, schema validation,
and seamless fallback between providers.
"""

from dataclasses import dataclass
import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError

# Load environment variables if python-dotenv is present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMUnavailableError(Exception):
    """Raised when all primary and fallback LLM attempts are exhausted."""
    pass


@dataclass
class LLMResult:
    """Standardized result returned by call_llm_json."""
    data: Any  # Validated Pydantic schema instance
    tokens_in: int
    tokens_out: int
    latency_s: float
    provider: str
    raw_response: str = ""


# Configurable mock handler for tests
_mock_behavior: Dict[str, Any] = {
    "canned_responses": [],  # List of strings or exceptions to return sequentially
    "call_count": 0,
    "last_prompt": None,
}


def set_mock_behavior(canned_responses: Optional[List[Any]] = None) -> None:
    """Configure mock provider responses for unit testing.

    Args:
        canned_responses: List of strings (JSON) or Exception instances to yield.
    """
    _mock_behavior["canned_responses"] = list(canned_responses) if canned_responses else []
    _mock_behavior["call_count"] = 0
    _mock_behavior["last_prompt"] = None


def reset_mock_behavior() -> None:
    """Reset mock provider to default behavior."""
    _mock_behavior["canned_responses"] = []
    _mock_behavior["call_count"] = 0
    _mock_behavior["last_prompt"] = None


def _generate_default_mock_data(schema: Type[T], user_content: str) -> str:
    """Synthesize a valid JSON string for a given Pydantic schema for offline testing."""
    schema_fields = schema.model_fields if hasattr(schema, "model_fields") else {}
    sample: Dict[str, Any] = {}

    for name, field in schema_fields.items():
        annotation = field.annotation
        # String
        if annotation is str:
            if "title" in name:
                sample[name] = "Hardware Laptop Request"
            elif "summary" in name:
                sample[name] = "Summary of laptop hardware upgrade request."
            elif "reasoning" in name:
                sample[name] = "Request aligns with standard company hardware refresh cycle."
            else:
                sample[name] = "Standard description of the request."
        # Int / score
        elif annotation is int:
            if "score" in name:
                sample[name] = 4
            else:
                sample[name] = 1
        # Bool
        elif annotation is bool:
            if "ready" in name:
                # If user input looks like a question or incomplete, ready_to_create = False
                sample[name] = not ("?" in user_content or len(user_content.strip()) < 15)
            elif "injection" in name:
                sample[name] = False
            else:
                sample[name] = False
        # List
        elif getattr(annotation, "__origin__", None) in (list, List):
            if "missing_fields" in name:
                sample[name] = []
            elif "follow_up_questions" in name:
                sample[name] = []
            elif "policy_flags" in name:
                sample[name] = []
            elif "suggestions" in name:
                sample[name] = ["Provide budget code if available"]
            elif "risks" in name:
                sample[name] = ["Low budget risk"]
            else:
                sample[name] = []
        # Literal / Enum fallback
        else:
            # Check for Literal values
            args = getattr(annotation, "__args__", None)
            if args:
                sample[name] = args[0]
            else:
                sample[name] = "medium"

    return json.dumps(sample)


def _call_gemini_raw(
    system_prompt: str,
    user_content: str,
    schema: Type[T],
    model: str,
    api_key: str,
) -> tuple[str, int, int]:
    """Call Google Gemini using google-genai SDK with structured JSON mode."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0.1,
    )
    response = client.models.generate_content(
        model=model,
        contents=user_content,
        config=config,
    )

    tokens_in = 0
    tokens_out = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        tokens_in = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        tokens_out = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

    text = response.text or "{}"
    return text, tokens_in, tokens_out


def _call_ollama_raw(
    system_prompt: str,
    user_content: str,
    schema: Type[T],
    model: str,
    base_url: str,
) -> tuple[str, int, int]:
    """Call local Ollama server via REST API."""
    import requests

    endpoint = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1},
    }

    resp = requests.post(endpoint, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    message = data.get("message", {})
    text = message.get("content", "{}")
    tokens_in = data.get("prompt_eval_count", 0) or 0
    tokens_out = data.get("eval_count", 0) or 0
    return text, tokens_in, tokens_out


def _call_mock_raw(
    system_prompt: str,
    user_content: str,
    schema: Type[T],
) -> tuple[str, int, int]:
    """Return mock canned JSON or synthetic valid output for tests."""
    _mock_behavior["call_count"] += 1
    _mock_behavior["last_prompt"] = user_content

    # Check for configured canned sequence
    if _mock_behavior["canned_responses"]:
        item = _mock_behavior["canned_responses"].pop(0)
        if isinstance(item, Exception):
            raise item
        text = str(item)
    else:
        text = _generate_default_mock_data(schema, user_content)

    tokens_in = len(user_content.split()) + len(system_prompt.split())
    tokens_out = len(text.split())
    return text, tokens_in, tokens_out


def _invoke_single_provider(
    provider: str,
    system_prompt: str,
    user_content: str,
    schema: Type[T],
) -> tuple[T, int, int, str]:
    """Invoke a single provider once, validate with Pydantic, and return (data, in, out, raw)."""
    p = provider.lower().strip()

    if p == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set or empty in environment.")
        raw_text, tokens_in, tokens_out = _call_gemini_raw(
            system_prompt, user_content, schema, model, api_key
        )

    elif p == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
        model = os.getenv("OLLAMA_MODEL", "llama3").strip()
        raw_text, tokens_in, tokens_out = _call_ollama_raw(
            system_prompt, user_content, schema, model, base_url
        )

    elif p == "mock":
        raw_text, tokens_in, tokens_out = _call_mock_raw(system_prompt, user_content, schema)

    else:
        raise ValueError(f"Unknown LLM provider: '{provider}'")

    # Validate against schema
    validated_data = schema.model_validate_json(raw_text)
    return validated_data, tokens_in, tokens_out, raw_text


def call_llm_json(
    system_prompt: str,
    user_content: str,
    schema: Type[T],
    max_retries: int = 3,
    backoff_factor: float = 0.5,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> LLMResult:
    """Call LLM with guaranteed structured output adhering to schema.

    Enforces:
    - Retries up to max_retries with exponential backoff on API errors or validation failures.
    - Fallback provider invocation if primary provider fails.
    - Raises LLMUnavailableError if all attempts and fallbacks fail.

    Args:
        system_prompt: System instruction.
        user_content: Untrusted user request data.
        schema: Pydantic model class defining expected output format.
        max_retries: Number of retry attempts per provider.
        backoff_factor: Exponential backoff base (seconds).
        sleep_fn: Hookable sleep function (for deterministic fast tests).

    Returns:
        LLMResult containing validated Pydantic object, token counts, and latency.
    """
    primary_provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()
    fallback_provider = os.getenv("LLM_FALLBACK_PROVIDER", "").strip().lower()

    providers_to_try = [primary_provider]
    if fallback_provider:
        providers_to_try.append(fallback_provider)

    last_error: Optional[Exception] = None

    for provider in providers_to_try:
        for attempt in range(1, max_retries + 1):
            start_time = time.perf_counter()
            try:
                data, tokens_in, tokens_out, raw_text = _invoke_single_provider(
                    provider=provider,
                    system_prompt=system_prompt,
                    user_content=user_content,
                    schema=schema,
                )
                latency = time.perf_counter() - start_time
                return LLMResult(
                    data=data,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_s=latency,
                    provider=provider,
                    raw_response=raw_text,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM call failed (provider=%s, attempt=%d/%d): %s",
                    provider,
                    attempt,
                    max_retries,
                    exc,
                )
                if attempt < max_retries:
                    sleep_time = backoff_factor * (2 ** (attempt - 1))
                    sleep_fn(sleep_time)

    raise LLMUnavailableError(
        f"All LLM providers ({providers_to_try}) failed after {max_retries} attempts each. "
        f"Last error: {last_error}"
    ) from last_error
