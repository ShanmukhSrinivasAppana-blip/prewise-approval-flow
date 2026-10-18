"""Unit tests for app/orchestrator.py testing workflow coordination, audit logs, and human checkpoints."""

from datetime import datetime, timedelta, timezone
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from app.llm import LLMUnavailableError, reset_mock_behavior, set_mock_behavior
from app.orchestrator import Orchestrator
from app.rules import Role, Status
from app.schemas import IntakeOutput, QualityCheckOutput, ReviewAssistOutput
from app.service import ErrorCode, RequestService, User


class TestOrchestrator(unittest.TestCase):
    """Test suite for Orchestrator, human decision checkpoints, audit logs, and notifications."""

    def setUp(self) -> None:
        reset_mock_behavior()
        os.environ["LLM_PROVIDER"] = "mock"
        os.environ["LLM_FALLBACK_PROVIDER"] = ""

        self.service = RequestService(db_path=":memory:")
        self.orchestrator = Orchestrator(service=self.service)

        self.alice = User(id="alice", role=Role.CREATOR, name="Alice Creator")
        self.bob = User(id="bob", role=Role.CREATOR, name="Bob Creator")
        self.rita = User(id="rita", role=Role.REVIEWER, name="Rita Reviewer")

    def tearDown(self) -> None:
        reset_mock_behavior()

    def test_handle_intake_creates_draft_when_ready(self) -> None:
        """When intake agent says ready_to_create=True, Orchestrator creates Draft."""
        set_mock_behavior([
            json.dumps({
                "title": "AWS RDS Instance",
                "description": "Production PostgreSQL RDS instance",
                "missing_fields": [],
                "follow_up_questions": [],
                "ready_to_create": True,
            })
        ])

        res = self.orchestrator.handle_intake(self.alice, "Provision AWS RDS for production")
        self.assertTrue(res["ok"])
        self.assertTrue(res["draft_created"])
        req = res["request"]
        self.assertEqual(req["status"], Status.DRAFT.value)
        self.assertEqual(req["title"], "AWS RDS Instance")

        # Verify audit log recorded
        logs = self.orchestrator.audit.get_logs(request_id=None)
        agent_names = [l["agent"] for l in logs]
        self.assertIn("IntakeAgent", agent_names)

        # Verify notification sent to Alice
        notifs = self.orchestrator.notifications.get_notifications(recipient_id="alice")
        self.assertTrue(len(notifs) > 0)
        self.assertIn("successfully created", notifs[0]["message"])

    def test_handle_intake_does_not_create_draft_when_ambiguous(self) -> None:
        """When intake agent says ready_to_create=False, Draft is NOT created."""
        set_mock_behavior([
            json.dumps({
                "title": "Incomplete Monitor Request",
                "description": "User wants a monitor",
                "missing_fields": ["model", "justification"],
                "follow_up_questions": ["What size monitor do you need?"],
                "ready_to_create": False,
            })
        ])

        res = self.orchestrator.handle_intake(self.alice, "I want a monitor")
        self.assertTrue(res["ok"])
        self.assertFalse(res["draft_created"])
        self.assertNotIn("request", res)
        self.assertEqual(len(res["intake"]["follow_up_questions"]), 1)

    def test_check_quality_provides_advisory_suggestions(self) -> None:
        """Quality check inspects draft and returns advisory scores and suggestions."""
        # Create a draft first
        draft = self.service.create_request(self.alice, "Dev Server", "Small 4-core dev server")["request"]

        set_mock_behavior([
            json.dumps({
                "clarity_score": 4,
                "completeness_score": 3,
                "policy_flags": [],
                "suggestions": ["Include target environment"],
                "risks": ["Idle resource cost"],
            })
        ])

        res = self.orchestrator.check_quality(self.alice, draft["id"])
        self.assertTrue(res["ok"])
        quality = res["quality"]
        self.assertEqual(quality["clarity_score"], 4)
        self.assertEqual(quality["suggestions"], ["Include target environment"])

    def test_submit_flow_notifies_reviewers(self) -> None:
        """Submitting transitions request to Submitted and sends notification to reviewers."""
        draft = self.service.create_request(self.alice, "Conference Ticket", "Tech conf attendance")["request"]

        res = self.orchestrator.submit(self.alice, draft["id"], reason="Submitting for early-bird discount")
        self.assertTrue(res["ok"])
        self.assertEqual(res["request"]["status"], Status.SUBMITTED.value)

        # Reviewers should have notification
        notifs = self.orchestrator.notifications.get_notifications(recipient_id="all_reviewers")
        self.assertTrue(len(notifs) > 0)
        self.assertIn("Conference Ticket", notifs[0]["message"])

    def test_assist_review_never_transitions_status(self) -> None:
        """assist_review gives advisory recommendation but NEVER changes request status."""
        draft = self.service.create_request(self.alice, "Monitor Arm", "Ergonomic monitor arm")["request"]
        self.orchestrator.submit(self.alice, draft["id"])

        set_mock_behavior([
            json.dumps({
                "summary": "Ergonomic arm for workstation",
                "risk_score": 1,
                "priority": "low",
                "recommendation": "approve",
                "reasoning": "Standard ergonomic equipment under $100",
                "injection_suspected": False,
            })
        ])

        res = self.orchestrator.assist_review(self.rita, draft["id"])
        self.assertTrue(res["ok"])
        self.assertEqual(res["recommendation"]["recommendation"], "approve")

        # Crucial invariant: The request in the database MUST STILL BE SUBMITTED!
        in_db = self.service.get_request(self.rita, draft["id"])
        self.assertEqual(in_db["request"]["status"], Status.SUBMITTED.value)

    def test_human_decision_approves_and_notifies_creator(self) -> None:
        """Human reviewer approves request, requiring a reason, and creator is notified."""
        draft = self.service.create_request(self.alice, "Course Subscription", "Online ML course")["request"]
        self.orchestrator.submit(self.alice, draft["id"])

        # Attempt decision without reason -> rejected by validation
        res_fail = self.orchestrator.human_decision(
            actor=self.rita,
            request_id=draft["id"],
            decision="approve",
            reason="",
        )
        self.assertFalse(res_fail["ok"])
        self.assertEqual(res_fail["error"]["code"], ErrorCode.VALIDATION_ERROR.value)

        # Valid decision with reason
        res_ok = self.orchestrator.human_decision(
            actor=self.rita,
            request_id=draft["id"],
            decision="approve",
            reason="Approved per Q3 continuous learning budget",
        )
        self.assertTrue(res_ok["ok"])
        self.assertEqual(res_ok["request"]["status"], Status.APPROVED.value)

        # Alice should receive approval notification
        alice_notifs = self.orchestrator.notifications.get_notifications(recipient_id="alice")
        self.assertTrue(len(alice_notifs) > 0)
        self.assertIn("APPROVED", alice_notifs[0]["message"])

    def test_llm_unavailable_returns_ai_unavailable_error(self) -> None:
        """When LLM is unavailable, returns AI_UNAVAILABLE so human can proceed manually."""
        # Configure mock to fail 3 times
        set_mock_behavior([
            RuntimeError("Down"),
            RuntimeError("Down"),
            RuntimeError("Down"),
        ])

        res = self.orchestrator.handle_intake(self.alice, "Need a new mouse")
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], "AI_UNAVAILABLE")

        # Verify audit log captures the failure
        logs = self.orchestrator.audit.get_logs()
        self.assertEqual(logs[0]["status"], "FAILED")

    def test_auto_escalation_detects_overdue_requests(self) -> None:
        """check_auto_escalation detects requests pending beyond threshold."""
        req = self.service.create_request(self.alice, "Old Pending Request", "Needs review")["request"]
        self.orchestrator.submit(self.alice, req["id"])

        # Manually alter created_at in the database to 48 hours ago
        past_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        with self.service._lock:
            cur = self.service._conn.cursor()
            cur.execute("UPDATE requests SET created_at = ? WHERE id = ?", (past_time, req["id"]))
            self.service._conn.commit()

        escalated = self.orchestrator.check_auto_escalation(threshold_hours=24.0)
        self.assertEqual(len(escalated), 1)
        self.assertEqual(escalated[0]["id"], req["id"])

        # Verify escalation notification
        notifs = self.orchestrator.notifications.get_notifications(recipient_id="all_reviewers")
        self.assertTrue(any("ESCALATION" in n["message"] for n in notifs))


if __name__ == "__main__":
    unittest.main()
