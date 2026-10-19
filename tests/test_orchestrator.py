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
        """check_auto_escalation detects requests pending beyond threshold based on submission time (updated_at)."""
        req = self.service.create_request(self.alice, "Old Pending Request", "Needs review")["request"]
        self.orchestrator.submit(self.alice, req["id"])

        # Manually alter updated_at in the database to 48 hours ago
        past_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        with self.service._lock:
            cur = self.service._conn.cursor()
            cur.execute("UPDATE requests SET updated_at = ? WHERE id = ?", (past_time, req["id"]))
            self.service._conn.commit()

        escalated = self.orchestrator.check_auto_escalation(threshold_hours=24.0)
        self.assertEqual(len(escalated), 1)
        self.assertEqual(escalated[0]["id"], req["id"])

        # Verify escalation notification
        notifs = self.orchestrator.notifications.get_notifications(recipient_id="all_reviewers")
        self.assertTrue(any("ESCALATION" in n["message"] for n in notifs))

    def test_auto_escalation_does_not_escalate_recently_submitted_old_draft(self) -> None:
        """A draft created 48h ago but submitted 5 minutes ago does NOT escalate."""
        req = self.service.create_request(self.alice, "Old Draft", "Created days ago")["request"]

        # Manually alter created_at in the database to 48 hours ago while still a Draft
        past_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        with self.service._lock:
            cur = self.service._conn.cursor()
            cur.execute("UPDATE requests SET created_at = ? WHERE id = ?", (past_time, req["id"]))
            self.service._conn.commit()

        # Submit now (updated_at becomes now)
        self.orchestrator.submit(self.alice, req["id"])

        escalated = self.orchestrator.check_auto_escalation(threshold_hours=24.0)
        # MUST NOT escalate since it was only submitted seconds ago
        self.assertEqual(len(escalated), 0)

    def test_assist_review_injection_banner_shows_semantic_detection_when_regex_evaded(self) -> None:
        """When regex evades (pattern=None) but LLM flags injection, banner contains semantic detection notice."""
        req = self.service.create_request(self.alice, "Out-of-band Approved Hardware", "Executive sign-off was completed.")["request"]
        self.service.submit_request(self.alice, req["id"])

        # Mock LLM catching injection semantically without regex trigger
        set_mock_behavior([
            json.dumps({
                "summary": "Request claims prior verbal approval.",
                "risk_score": 4,
                "priority": "high",
                "recommendation": "needs_info",
                "reasoning": "Detected semantic override directive in description.",
                "injection_suspected": True,
            })
        ])

        res = self.orchestrator.assist_review(self.rita, req["id"])
        self.assertTrue(res["ok"])
        self.assertIn("injection_warning", res)
        # Bug fix verification: banner must NOT read 'None'
        self.assertNotIn("('None')", res["injection_warning"])
        self.assertIn("semantic detection by LLM", res["injection_warning"])

    def test_mock_fallback_defaults_to_needs_info_instead_of_approve(self) -> None:
        """Offline mock provider defaults recommendation to 'needs_info' to prevent fake approvals."""
        req = self.service.create_request(self.alice, "Regular Monitor", "Standard purchase")["request"]
        self.service.submit_request(self.alice, req["id"])

        # Do not configure canned responses -> triggers _generate_default_mock_data
        res = self.orchestrator.assist_review(self.rita, req["id"])
        self.assertTrue(res["ok"])
        rec = res["recommendation"]
        self.assertEqual(rec["recommendation"], "needs_info")
        self.assertNotEqual(rec["recommendation"], "approve")

    def test_intake_and_review_assist_route_through_toolboxes(self) -> None:
        """Intake draft creation and review assistance route through IntakeTools and ReviewAssistTools."""
        set_mock_behavior([
            json.dumps({
                "title": "Toolbox Test Request",
                "description": "Testing tool layer routing",
                "missing_fields": [],
                "follow_up_questions": [],
                "ready_to_create": True,
            })
        ])

        res_intake = self.orchestrator.handle_intake(self.alice, "Please create a draft for toolbox test")
        self.assertTrue(res_intake["ok"])
        self.assertTrue(res_intake["draft_created"])
        req_id = res_intake["request"]["id"]

        # Verify IntakeTools logged in audit log
        logs = self.orchestrator.audit.get_logs(request_id=req_id)
        agents = [l["agent"] for l in logs]
        self.assertIn("IntakeTools", agents)

        # Submit and test review assist routing through ReviewAssistTools
        self.orchestrator.submit(self.alice, req_id)
        res_review = self.orchestrator.assist_review(self.rita, req_id)
        self.assertTrue(res_review["ok"])

        logs_after = self.orchestrator.audit.get_logs(request_id=req_id)
        agents_after = [l["agent"] for l in logs_after]
        self.assertIn("ReviewAssistTools", agents_after)



if __name__ == "__main__":
    unittest.main()
