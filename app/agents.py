"""Three AI agents with structured outputs: Intake, Quality-Check, and Review-Assist.

Core Architectural Principles:
1. Pure Advisory Roles: Agents produce structured assessments and recommendations.
   They NEVER mutate request status, NEVER approve or reject on their own, and NEVER
   create records directly. The Orchestrator handles all backend state actions.
2. Prompt Isolation: All request data is wrapped strictly within <request_data> tags
   to separate untrusted user input from system instructions.
"""

from typing import Any, Dict, Optional

from app.llm import LLMResult, call_llm_json
from app.prompts import (
    INTAKE_SYSTEM_PROMPT,
    QUALITY_CHECK_SYSTEM_PROMPT,
    REVIEW_ASSIST_SYSTEM_PROMPT,
)
from app.schemas import IntakeOutput, QualityCheckOutput, ReviewAssistOutput


def _wrap_request_data(content: str) -> str:
    """Safely enclose untrusted user content inside request_data delimiters."""
    # Strip any rogue closing delimiters from untrusted content
    sanitized = content.replace("</request_data>", "")
    return f"<request_data>\n{sanitized}\n</request_data>"


class IntakeAgent:
    """Agent that converses with the Creator to gather request details and formulate a clean draft.
    
    Architectural Pattern:
    LLM proposes structured output, orchestrator executes through a least-privilege tool layer.
    """

    def __init__(self, system_prompt: str = INTAKE_SYSTEM_PROMPT, tools: Optional[Any] = None) -> None:
        self.system_prompt = system_prompt
        self.tools = tools

    def run(self, user_input: str, tools: Optional[Any] = None) -> LLMResult:
        """Analyze user input and extract structured intake information.

        Args:
            user_input: Raw text provided by the Creator.
            tools: Optional IntakeTools instance.

        Returns:
            LLMResult containing validated IntakeOutput schema.
        """
        active_tools = tools or self.tools
        wrapped_data = _wrap_request_data(user_input)
        return call_llm_json(
            system_prompt=self.system_prompt,
            user_content=wrapped_data,
            schema=IntakeOutput,
        )


class QualityCheckAgent:
    """Agent that performs pre-submission advisory review on draft requests."""

    def __init__(self, system_prompt: str = QUALITY_CHECK_SYSTEM_PROMPT) -> None:
        self.system_prompt = system_prompt

    def run(self, title: str, description: str) -> LLMResult:
        """Evaluate clarity, completeness, and potential policy flags of a draft request.

        Args:
            title: Request title.
            description: Request description.

        Returns:
            LLMResult containing validated QualityCheckOutput schema.
        """
        content = f"Title: {title}\nDescription: {description}"
        wrapped_data = _wrap_request_data(content)
        return call_llm_json(
            system_prompt=self.system_prompt,
            user_content=wrapped_data,
            schema=QualityCheckOutput,
        )


class ReviewAssistAgent:
    """Agent that provides executive summaries, risk scores, and advisory recommendations to human approvers.
    
    Architectural Pattern:
    LLM proposes structured output, orchestrator executes through a least-privilege tool layer.
    """

    def __init__(self, system_prompt: str = REVIEW_ASSIST_SYSTEM_PROMPT, tools: Optional[Any] = None) -> None:
        self.system_prompt = system_prompt
        self.tools = tools

    def run(self, request_data: Any, tools: Optional[Any] = None) -> LLMResult:
        """Assess a submitted request and produce an advisory recommendation for the Reviewer.

        Args:
            request_data: Dictionary containing request details OR request_id string.
            tools: Optional ReviewAssistTools instance for reading requests.

        Returns:
            LLMResult containing validated ReviewAssistOutput schema.
        """
        active_tools = tools or self.tools
        req_dict: Dict[str, Any] = {}

        if isinstance(request_data, str) and active_tools:
            # Use least-privilege tool to fetch request data
            fetched = active_tools.dispatch("get_request", {"request_id": request_data})
            if fetched.get("ok"):
                req_dict = fetched.get("request", {})
            else:
                req_dict = {"id": request_data}
        elif isinstance(request_data, dict):
            req_dict = request_data

        title = req_dict.get("title", "")
        description = req_dict.get("description", "")
        creator_id = req_dict.get("creator_id", "")
        req_id = req_dict.get("id", "")

        content = (
            f"Request ID: {req_id}\n"
            f"Creator ID: {creator_id}\n"
            f"Title: {title}\n"
            f"Description: {description}"
        )
        wrapped_data = _wrap_request_data(content)

        return call_llm_json(
            system_prompt=self.system_prompt,
            user_content=wrapped_data,
            schema=ReviewAssistOutput,
        )

