"""Orchestrator coordinating AI agents, deterministic backend, audit logging, and notifications.

Core Principles:
1. The AI suggests; a deterministic backend decides.
2. The human-in-the-loop checkpoint: Reviewers make the ultimate decision. Agents NEVER approve or reject.
3. Least privilege: Agents produce structured schemas; the Orchestrator initiates state transitions.
4. Fault tolerance: On LLMUnavailableError, returns AI_UNAVAILABLE so users can proceed manually.
5. Observability: Every single agent invocation, tool call, and decision is logged in agent_audit_log.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from app.agents import IntakeAgent, QualityCheckAgent, ReviewAssistAgent
from app.audit import AuditLogger
from app.guardrails import filter_prompt_leakage, sanitize_input, scan_for_injection
from app.llm import LLMUnavailableError
from app.notifications import NotificationManager
from app.rules import Role, Status
from app.service import ErrorCode, RequestService, User

logger = logging.getLogger(__name__)


class Orchestrator:
    """End-to-end coordinator for the Request Approval Flow."""

    def __init__(
        self,
        service: Optional[RequestService] = None,
        audit_logger: Optional[AuditLogger] = None,
        notification_manager: Optional[NotificationManager] = None,
        intake_agent: Optional[IntakeAgent] = None,
        quality_agent: Optional[QualityCheckAgent] = None,
        review_agent: Optional[ReviewAssistAgent] = None,
    ) -> None:
        """Initialize orchestrator dependencies.

        If not provided, default instances backed by an in-memory or shared database are created.
        """
        self.service = service or RequestService(db_path=":memory:")
        self.audit = audit_logger or AuditLogger(self.service._conn, self.service._lock)
        self.notifications = notification_manager or NotificationManager(self.service._conn, self.service._lock)

        self.intake_agent = intake_agent or IntakeAgent()
        self.quality_agent = quality_agent or QualityCheckAgent()
        self.review_agent = review_agent or ReviewAssistAgent()

    def handle_intake(self, actor: User, user_text: str) -> Dict[str, Any]:
        """Process conversational intake with the Creator.

        If the agent determines `ready_to_create` is True, the Orchestrator (not the agent)
        creates the Draft in the deterministic backend.

        Args:
            actor: Current authenticated user.
            user_text: Raw input from the Creator.

        Returns:
            Dict containing intake extraction details, draft creation result if ready, or error.
        """
        if actor.role != Role.CREATOR:
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.ROLE_NOT_ALLOWED.value,
                    "message": "Only Creators can initiate request intake.",
                },
            }

        # Guardrail check on Creator input
        injection_flag, pattern = scan_for_injection(user_text)
        if injection_flag:
            self.audit.log_event(
                actor_id=actor.id,
                actor_role=actor.role.value,
                agent="Guardrails",
                input_data=user_text,
                output_data={"injection_detected": True, "pattern": pattern},
                status="FLAGGED_INJECTION",
                reason=f"Prompt injection pattern detected: '{pattern}'",
            )

        sanitized_input = sanitize_input(user_text)

        try:
            llm_res = self.intake_agent.run(sanitized_input)
            self.audit.log_event(
                actor_id=actor.id,
                actor_role=actor.role.value,
                agent="IntakeAgent",
                input_data=user_text,
                output_data=llm_res.data.model_dump(),
                status="SUCCESS",
                latency_s=llm_res.latency_s,
                tokens_in=llm_res.tokens_in,
                tokens_out=llm_res.tokens_out,
            )
        except LLMUnavailableError as err:
            self.audit.log_event(
                actor_id=actor.id,
                actor_role=actor.role.value,
                agent="IntakeAgent",
                input_data=user_text,
                output_data=str(err),
                status="FAILED",
                reason="LLMUnavailableError",
            )
            return {
                "ok": False,
                "error": {
                    "code": "AI_UNAVAILABLE",
                    "message": "AI Intake service is temporarily unavailable. You may fill out the request form manually.",
                },
            }

        intake_data = llm_res.data

        # If sufficient info is present, the Orchestrator creates the draft
        if intake_data.ready_to_create:
            create_res = self.service.create_request(
                actor=actor,
                title=intake_data.title,
                description=intake_data.description,
            )
            if not create_res["ok"]:
                return create_res

            req = create_res["request"]
            self.notifications.notify(
                recipient_id=actor.id,
                message=f"Draft request '{req['title']}' ({req['id']}) was successfully created.",
                request_id=req["id"],
                notif_type="info",
            )
            return {
                "ok": True,
                "draft_created": True,
                "request": req,
                "intake": intake_data.model_dump(),
                "injection_detected": injection_flag,
            }

        return {
            "ok": True,
            "draft_created": False,
            "intake": intake_data.model_dump(),
            "injection_detected": injection_flag,
        }

    def check_quality(self, actor: User, request_id: str) -> Dict[str, Any]:
        """Perform advisory quality check on a draft request before submission.

        Advisory only: The Creator may choose to accept suggestions or submit as is.
        """
        get_res = self.service.get_request(actor, request_id)
        if not get_res["ok"]:
            return get_res

        req = get_res["request"]

        try:
            llm_res = self.quality_agent.run(title=req["title"], description=req["description"])
            self.audit.log_event(
                actor_id=actor.id,
                actor_role=actor.role.value,
                agent="QualityCheckAgent",
                request_id=request_id,
                input_data={"title": req["title"], "description": req["description"]},
                output_data=llm_res.data.model_dump(),
                status="SUCCESS",
                latency_s=llm_res.latency_s,
                tokens_in=llm_res.tokens_in,
                tokens_out=llm_res.tokens_out,
            )
            return {
                "ok": True,
                "quality": llm_res.data.model_dump(),
                "request": req,
            }
        except LLMUnavailableError as err:
            self.audit.log_event(
                actor_id=actor.id,
                actor_role=actor.role.value,
                agent="QualityCheckAgent",
                request_id=request_id,
                input_data={"title": req["title"]},
                output_data=str(err),
                status="FAILED",
                reason="LLMUnavailableError",
            )
            return {
                "ok": False,
                "error": {
                    "code": "AI_UNAVAILABLE",
                    "message": "AI Quality-Check is temporarily unavailable. You may proceed with submission directly.",
                },
            }

    def submit(self, actor: User, request_id: str, reason: str = "") -> Dict[str, Any]:
        """Submit a draft request for review.

        Passes directly to deterministic RequestService.
        """
        res = self.service.submit_request(actor=actor, request_id=request_id, reason=reason)
        if res["ok"]:
            req = res["request"]
            self.notifications.notify(
                recipient_id="all_reviewers",
                message=f"New request submitted for review: '{req['title']}' ({req['id']}) by {actor.id}.",
                request_id=req["id"],
                notif_type="info",
            )
            self.audit.log_event(
                actor_id=actor.id,
                actor_role=actor.role.value,
                agent="Orchestrator",
                request_id=request_id,
                input_data={"action": "submit", "reason": reason},
                output_data=req,
                status="SUCCESS",
            )
        return res

    def assist_review(self, actor: User, request_id: str) -> Dict[str, Any]:
        """Generate an advisory review summary, risk score, and recommendation for human approvers.

        CRITICAL ARCHITECTURAL BOUNDARY:
        This method NEVER transitions or mutates request status.
        """
        # Enforce visibility and existence
        get_res = self.service.get_request(actor, request_id)
        if not get_res["ok"]:
            return get_res

        req = get_res["request"]

        # Only Submitted requests are eligible for reviewer assist
        if req["status"] != Status.SUBMITTED.value:
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.INVALID_TRANSITION.value,
                    "message": f"Review assistance is only applicable to Submitted requests (current: {req['status']}).",
                },
            }

        # Guardrail check on request content before passing to review agent
        combined_text = f"{req.get('title', '')} {req.get('description', '')}"
        injection_flag, pattern = scan_for_injection(combined_text)
        if injection_flag:
            self.audit.log_event(
                actor_id=actor.id,
                actor_role=actor.role.value,
                agent="Guardrails",
                request_id=request_id,
                input_data=combined_text,
                output_data={"injection_detected": True, "pattern": pattern},
                status="FLAGGED_INJECTION",
                reason=f"Prompt injection pattern detected in request: '{pattern}'",
            )

        sanitized_req = dict(req)
        sanitized_req["title"] = sanitize_input(req.get("title", ""))
        sanitized_req["description"] = sanitize_input(req.get("description", ""))

        try:
            llm_res = self.review_agent.run(sanitized_req)
            rec_dict = llm_res.data.model_dump()

            # Defense in depth: Force injection_suspected flag if guardrail matched
            if injection_flag:
                rec_dict["injection_suspected"] = True

            # Output filter: Prevent system prompt leakage
            rec_dict["summary"] = filter_prompt_leakage(rec_dict.get("summary", ""))
            rec_dict["reasoning"] = filter_prompt_leakage(rec_dict.get("reasoning", ""))

            self.audit.log_event(
                actor_id=actor.id,
                actor_role=actor.role.value,
                agent="ReviewAssistAgent",
                request_id=request_id,
                input_data={"request_id": req["id"], "title": req["title"]},
                output_data=rec_dict,
                status="SUCCESS",
                latency_s=llm_res.latency_s,
                tokens_in=llm_res.tokens_in,
                tokens_out=llm_res.tokens_out,
            )

            result: Dict[str, Any] = {
                "ok": True,
                "recommendation": rec_dict,
                "request": req,
            }

            if injection_flag or rec_dict.get("injection_suspected"):
                result["injection_warning"] = (
                    f"CRITICAL WARNING: Potential prompt injection detected ('{pattern}'). "
                    "This request contains adversarial instructions attempting to manipulate approvals. "
                    "Exercise caution and review manually."
                )

            return result
        except LLMUnavailableError as err:
            self.audit.log_event(
                actor_id=actor.id,
                actor_role=actor.role.value,
                agent="ReviewAssistAgent",
                request_id=request_id,
                input_data={"request_id": req["id"]},
                output_data=str(err),
                status="FAILED",
                reason="LLMUnavailableError",
            )
            return {
                "ok": False,
                "error": {
                    "code": "AI_UNAVAILABLE",
                    "message": "AI Review Assistant is temporarily unavailable. Please review the request details manually.",
                },
            }

    def human_decision(
        self,
        actor: User,
        request_id: str,
        decision: str,
        reason: str,
    ) -> Dict[str, Any]:
        """Human-in-the-loop decision checkpoint.

        Only a human Reviewer can approve or reject a request.
        The action is executed strictly under the Reviewer's own authenticated identity.

        Args:
            actor: Authenticated Reviewer.
            request_id: ID of the request.
            decision: 'approve' or 'reject'.
            reason: Mandatory human explanation.

        Returns:
            Dict with ok=True and updated request or ok=False and error details.
        """
        clean_decision = (decision or "").strip().lower()
        if clean_decision not in ("approve", "reject"):
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.UNKNOWN_ACTION.value,
                    "message": f"Decision must be 'approve' or 'reject' (received '{decision}').",
                },
            }

        if not (reason or "").strip():
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.VALIDATION_ERROR.value,
                    "message": "A decision reason must be provided.",
                },
            }

        # Transition through deterministic backend
        res = self.service.transition_request(
            actor=actor,
            request_id=request_id,
            action=clean_decision,
            reason=reason.strip(),
        )

        if res["ok"]:
            req = res["request"]
            # Notify the Creator of the final human decision
            self.notifications.notify(
                recipient_id=req["creator_id"],
                message=(
                    f"Your request '{req['title']}' ({req['id']}) was {req['status'].upper()} "
                    f"by Reviewer {actor.name or actor.id}. Reason: {reason.strip()}"
                ),
                request_id=req["id"],
                notif_type="approval" if req["status"] == Status.APPROVED.value else "rejection",
            )
            self.audit.log_event(
                actor_id=actor.id,
                actor_role=actor.role.value,
                agent="HumanReviewer",
                request_id=request_id,
                input_data={"decision": clean_decision, "reason": reason},
                output_data=req,
                status="SUCCESS",
            )

        return res

    def cancel(self, actor: User, request_id: str, reason: str = "") -> Dict[str, Any]:
        """Cancel a Draft or Submitted request.

        Only the owning Creator can cancel.
        """
        res = self.service.transition_request(
            actor=actor,
            request_id=request_id,
            action="cancel",
            reason=reason or "Cancelled by creator",
        )
        if res["ok"]:
            req = res["request"]
            self.notifications.notify(
                recipient_id=actor.id,
                message=f"Request '{req['title']}' ({req['id']}) was cancelled.",
                request_id=req["id"],
                notif_type="info",
            )
            self.audit.log_event(
                actor_id=actor.id,
                actor_role=actor.role.value,
                agent="Creator",
                request_id=request_id,
                input_data={"action": "cancel", "reason": reason},
                output_data=req,
                status="SUCCESS",
            )
        return res

    def check_auto_escalation(self, threshold_hours: float = 24.0) -> List[Dict[str, Any]]:
        """Identify Submitted requests pending review longer than threshold hours.

        Emits escalation notifications and logs audit events.

        Args:
            threshold_hours: Maximum hours a request may remain Submitted before escalation.

        Returns:
            List of escalated request dictionaries.
        """
        admin_actor = User(id="system_daemon", role=Role.REVIEWER, name="System Daemon")
        submitted_res = self.service.list_requests(actor=admin_actor, status=Status.SUBMITTED.value)
        if not submitted_res["ok"]:
            return []

        escalated: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        for req in submitted_res["requests"]:
            created_at_str = req["created_at"]
            try:
                created_dt = datetime.fromisoformat(created_at_str)
                age_hours = (now - created_dt).total_seconds() / 3600.0
                if age_hours >= threshold_hours:
                    self.notifications.notify(
                        recipient_id="all_reviewers",
                        message=(
                            f"ESCALATION: Request '{req['title']}' ({req['id']}) has been pending review "
                            f"for {age_hours:.1f} hours (exceeds {threshold_hours}h SLA)."
                        ),
                        request_id=req["id"],
                        notif_type="escalation",
                    )
                    self.audit.log_event(
                        actor_id="system_daemon",
                        actor_role="System",
                        agent="EscalationDaemon",
                        request_id=req["id"],
                        input_data={"age_hours": age_hours, "threshold_hours": threshold_hours},
                        output_data={"escalated": True},
                        status="ESCALATED",
                    )
                    escalated.append(req)
            except Exception as e:
                logger.warning("Could not calculate age for request %s: %s", req.get("id"), e)

        return escalated
