"""Least-privilege toolboxes exposing service operations to agents.

Core Security Guarantees:
1. Actor Injection: The `User` actor is strictly injected by backend code during instantiation.
   It is NEVER an argument the LLM can supply or override.
2. Least Privilege:
   - Base `ToolBox`: full access according to the actor's deterministic role permissions.
   - `IntakeTools`: restricted to `create_request` and `get_request`.
   - `ReviewAssistTools`: strictly read-only (`get_request` ONLY). Cannot transition, approve, or reject.
3. Strict Dispatch: All inputs to `dispatch()` are validated against Pydantic schemas. Unknown or
   unauthorized tools are strictly rejected.
"""

from typing import Any, Callable, Dict, Optional, Set
from pydantic import BaseModel, Field, ValidationError

from app.service import RequestService, User


class CreateRequestArgs(BaseModel):
    """Arguments for creating a draft request."""
    title: str = Field(..., description="Request title")
    description: str = Field(default="", description="Detailed explanation")


class GetRequestArgs(BaseModel):
    """Arguments for retrieving a request."""
    request_id: str = Field(..., description="ID of the target request")


class SubmitRequestArgs(BaseModel):
    """Arguments for submitting a draft request."""
    request_id: str = Field(..., description="ID of the draft request")
    reason: str = Field(default="", description="Submission comments")


class TransitionRequestArgs(BaseModel):
    """Arguments for transitioning request state."""
    request_id: str = Field(..., description="ID of the target request")
    action: str = Field(..., description="Action verb: submit, approve, reject, cancel")
    reason: str = Field(default="", description="Reason for the decision")


class ToolBox:
    """Base tool execution engine with actor binding and least-privilege enforcement."""

    def __init__(self, service: RequestService, actor: User) -> None:
        """Bind the deterministic service and immutable actor.

        Args:
            service: Backend RequestService.
            actor: Injected authenticated User identity.
        """
        self._service = service
        self._actor = actor

    @property
    def actor(self) -> User:
        """Return the securely injected actor (read-only)."""
        return self._actor

    @property
    def allowed_tools(self) -> Set[str]:
        """Set of tool names allowed on this toolbox."""
        return {"create_request", "get_request", "submit_request", "transition_request"}

    def create_request(self, title: str, description: str = "") -> Dict[str, Any]:
        """Create a new request in Draft status under the injected actor's identity."""
        return self._service.create_request(
            actor=self._actor,
            title=title,
            description=description,
        )

    def get_request(self, request_id: str) -> Dict[str, Any]:
        """Retrieve a request respecting visibility rules for the injected actor."""
        return self._service.get_request(
            actor=self._actor,
            request_id=request_id,
        )

    def submit_request(self, request_id: str, reason: str = "") -> Dict[str, Any]:
        """Submit a draft request for review under the injected actor's identity."""
        return self._service.submit_request(
            actor=self._actor,
            request_id=request_id,
            reason=reason,
        )

    def transition_request(self, request_id: str, action: str, reason: str = "") -> Dict[str, Any]:
        """Execute a state transition under the injected actor's identity."""
        return self._service.transition_request(
            actor=self._actor,
            request_id=request_id,
            action=action,
            reason=reason,
        )

    def dispatch(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Validate arguments with Pydantic and safely execute the requested tool.

        Guarantees:
        - Any attempted override of actor or actor_id in args is stripped and ignored.
        - Unregistered or unauthorized tools return TOOL_NOT_ALLOWED.
        - Argument parsing failures return TOOL_VALIDATION_ERROR.

        Args:
            tool_name: Name of tool method to execute.
            args: Raw argument dictionary provided by caller or LLM.

        Returns:
            Dict containing result from backend service or standard error.
        """
        if tool_name not in self.allowed_tools:
            return {
                "ok": False,
                "error": {
                    "code": "TOOL_NOT_ALLOWED",
                    "message": f"Tool '{tool_name}' is not permitted for this toolbox. Allowed tools: {sorted(list(self.allowed_tools))}",
                },
            }

        # Defend against LLM passing spoofed actor parameters
        safe_args = {k: v for k, v in (args or {}).items() if k not in ("actor", "actor_id", "role")}

        try:
            if tool_name == "create_request":
                parsed_create = CreateRequestArgs.model_validate(safe_args)
                return self.create_request(title=parsed_create.title, description=parsed_create.description)

            elif tool_name == "get_request":
                parsed_get = GetRequestArgs.model_validate(safe_args)
                return self.get_request(request_id=parsed_get.request_id)

            elif tool_name == "submit_request":
                parsed_submit = SubmitRequestArgs.model_validate(safe_args)
                return self.submit_request(request_id=parsed_submit.request_id, reason=parsed_submit.reason)

            elif tool_name == "transition_request":
                parsed_transition = TransitionRequestArgs.model_validate(safe_args)
                return self.transition_request(
                    request_id=parsed_transition.request_id,
                    action=parsed_transition.action,
                    reason=parsed_transition.reason,
                )

            else:
                return {
                    "ok": False,
                    "error": {
                        "code": "UNKNOWN_TOOL",
                        "message": f"Tool '{tool_name}' is not recognized.",
                    },
                }

        except ValidationError as val_err:
            return {
                "ok": False,
                "error": {
                    "code": "TOOL_VALIDATION_ERROR",
                    "message": f"Invalid arguments for tool '{tool_name}': {val_err.errors()}",
                },
            }


class IntakeTools(ToolBox):
    """Least-privilege toolbox for intake operations: create and read only.
    
    Architectural Pattern:
    LLM proposes structured output, orchestrator executes through a least-privilege tool layer.
    """

    @property
    def allowed_tools(self) -> Set[str]:
        return {"create_request", "get_request"}

    @classmethod
    def get_tool_declarations(cls) -> list[Dict[str, Any]]:
        """Return function calling declarations for Intake operations."""
        return [
            {
                "name": "create_request",
                "description": "Create a new draft request in the approval system under the authenticated creator's identity.",
                "parameters": CreateRequestArgs.model_json_schema(),
            },
            {
                "name": "get_request",
                "description": "Retrieve request details by ID respecting creator visibility rules.",
                "parameters": GetRequestArgs.model_json_schema(),
            },
        ]


class ReviewAssistTools(ToolBox):
    """Least-privilege toolbox for reviewer assistance: strictly read-only.

    Crucial Architectural Invariant:
    This toolbox contains NO transition tools whatsoever. Even if an LLM is compromised
    via prompt injection, it physically cannot approve, reject, submit, or cancel requests.

    Architectural Pattern:
    LLM proposes structured output, orchestrator executes through a least-privilege tool layer.
    """

    @property
    def allowed_tools(self) -> Set[str]:
        return {"get_request"}

    @classmethod
    def get_tool_declarations(cls) -> list[Dict[str, Any]]:
        """Return function calling declarations for Review Assist operations (strictly read-only)."""
        return [
            {
                "name": "get_request",
                "description": "Retrieve request details by ID respecting reviewer visibility rules. Strictly read-only.",
                "parameters": GetRequestArgs.model_json_schema(),
            },
        ]

