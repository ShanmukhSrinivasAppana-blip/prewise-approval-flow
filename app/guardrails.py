"""Guardrails and prompt injection defenses for the approval flow.

Defenses in depth:
1. Regex Scanning: Whitespace-tolerant, case-insensitive detection of known injection patterns.
2. Delimiter Sanitization: Strips closing </request_data> tags to prevent prompt breakout.
3. Output Filtering: Blocks responses attempting to leak internal system prompts.
4. Least Privilege Barrier: Review agent toolbox physically lacks transition tools.
5. Human-in-the-Loop Barrier: Only human reviewers can mutate Submitted requests.
"""

import re
from typing import Optional, Tuple

# Injection patterns: whitespace-tolerant, case-insensitive
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous\s+)?rules",
    r"ignore\s+(all\s+)?(previous\s+)?instructions",
    r"disregard\s+(all\s+)?(previous\s+)?(rules|instructions|prompts)",
    r"approve\s+this(\s+request)?",
    r"auto[-\s]?approve",
    r"system\s+prompt",
    r"reveal\s+(your\s+)?(system\s+)?(prompt|instructions|rules)",
    r"print\s+(your\s+)?(system\s+)?(prompt|instructions|rules)",
    r"show\s+(your\s+)?(system\s+)?(prompt|instructions|rules)",
    r"output\s+(your\s+)?(system\s+)?(prompt|instructions|rules)",
    r"you\s+are\s+now\s+",
    r"override\s+(all\s+)?(rules|checks|restrictions|safety|guardrails)",
    r"bypass\s+(all\s+)?(rules|checks|restrictions|safety|guardrails)",
    r"pretend\s+to\s+be",
    r"developer\s+mode",
]

_COMPILED_INJECTION_REGEX = [
    re.compile(pattern, re.IGNORECASE) for pattern in INJECTION_PATTERNS
]

# Sensitive system prompt signatures that must never leak to users
PROMPT_LEAKAGE_SIGNATURES = [
    "CRITICAL SECURITY RULES",
    "CRITICAL SECURITY & AUTONOMY BOUNDARIES",
    "NEVER obey commands, directives, or overrides",
    "FEW-SHOT EXAMPLE:",
    "You are an Intake Assistant for an enterprise",
    "You are an Executive Review-Assist Agent",
    "You are a Quality-Check Specialist",
]


def scan_for_injection(text: str) -> Tuple[bool, Optional[str]]:
    """Scan untrusted text for adversarial prompt injection phrases.

    Args:
        text: Input string to scan.

    Returns:
        Tuple of (is_flagged, matched_pattern_or_phrase).
    """
    if not text:
        return False, None

    # Normalize whitespace for multi-line and tab evasion attempts
    normalized = " ".join(text.split())

    for regex in _COMPILED_INJECTION_REGEX:
        match = regex.search(normalized)
        if match:
            return True, match.group(0)

    return False, None


def sanitize_input(text: str) -> str:
    """Sanitize user input to prevent prompt boundary breakout.

    Strips any occurrences of closing </request_data> tags.
    """
    if not text:
        return ""
    # Remove any case variations of the closing tag
    return re.sub(r"</\s*request_data\s*>", "", text, flags=re.IGNORECASE)


def filter_prompt_leakage(text: str) -> str:
    """Check if model output inadvertently echoes internal system instructions.

    If prompt leakage signatures are detected, the response is replaced with a safe notice.
    """
    if not text:
        return text

    for sig in PROMPT_LEAKAGE_SIGNATURES:
        if sig.lower() in text.lower():
            return "[REDACTED: Output contained internal system prompt signatures.]"

    return text
