"""Unit tests for app/tools.py testing least-privilege toolboxes and actor injection."""

import unittest

from app.rules import Role, Status
from app.service import RequestService, User
from app.tools import IntakeTools, ReviewAssistTools, ToolBox


class TestToolBoxSecurity(unittest.TestCase):
    """Test suite verifying tool restrictions, actor injection, and least-privilege boundaries."""

    def setUp(self) -> None:
        self.service = RequestService(db_path=":memory:")
        self.creator_alice = User(id="alice", role=Role.CREATOR, name="Alice")
        self.creator_bob = User(id="bob", role=Role.CREATOR, name="Bob")
        self.reviewer_rita = User(id="rita", role=Role.REVIEWER, name="Rita")

    def test_actor_cannot_be_overridden_by_llm_args(self) -> None:
        """Passing spoofed actor_id or actor in dispatch arguments has zero effect."""
        toolbox = ToolBox(self.service, self.creator_alice)

        # Attempt to create a request masquerading as bob
        res = toolbox.dispatch(
            "create_request",
            {
                "title": "Hardware Monitor",
                "description": "4K display",
                "actor_id": "bob",
                "actor": "admin",
                "role": "Reviewer",
            },
        )
        self.assertTrue(res["ok"])
        req = res["request"]
        # Injected identity MUST prevail
        self.assertEqual(req["creator_id"], "alice")
        self.assertNotEqual(req["creator_id"], "bob")

    def test_review_assist_toolbox_cannot_approve_or_transition(self) -> None:
        """ReviewAssistTools strictly denies transition tools (defense in depth)."""
        # Create and submit a request as Alice
        req = self.service.create_request(self.creator_alice, "Test Item", "Desc")["request"]
        self.service.submit_request(self.creator_alice, req["id"])

        review_tools = ReviewAssistTools(self.service, self.reviewer_rita)

        # Attempt transition_request dispatch
        res = review_tools.dispatch(
            "transition_request",
            {
                "request_id": req["id"],
                "action": "approve",
                "reason": "AI says approve",
            },
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], "TOOL_NOT_ALLOWED")

        # Verify request status in database remains Submitted (unchanged!)
        check = self.service.get_request(self.reviewer_rita, req["id"])
        self.assertEqual(check["request"]["status"], Status.SUBMITTED.value)

    def test_review_assist_toolbox_cannot_create_or_submit(self) -> None:
        """ReviewAssistTools denies create_request and submit_request."""
        review_tools = ReviewAssistTools(self.service, self.reviewer_rita)

        res_create = review_tools.dispatch("create_request", {"title": "X", "description": "Y"})
        self.assertFalse(res_create["ok"])
        self.assertEqual(res_create["error"]["code"], "TOOL_NOT_ALLOWED")

        res_submit = review_tools.dispatch("submit_request", {"request_id": "req_123"})
        self.assertFalse(res_submit["ok"])
        self.assertEqual(res_submit["error"]["code"], "TOOL_NOT_ALLOWED")

    def test_review_assist_toolbox_can_get_request(self) -> None:
        """ReviewAssistTools can read submitted requests."""
        req = self.service.create_request(self.creator_alice, "Submitted Item", "Desc")["request"]
        self.service.submit_request(self.creator_alice, req["id"])

        review_tools = ReviewAssistTools(self.service, self.reviewer_rita)
        res = review_tools.dispatch("get_request", {"request_id": req["id"]})
        self.assertTrue(res["ok"])
        self.assertEqual(res["request"]["title"], "Submitted Item")

    def test_intake_toolbox_restricted_to_create_and_get(self) -> None:
        """IntakeTools allows create and get, but denies submit and transition."""
        intake_tools = IntakeTools(self.service, self.creator_alice)

        # Create is allowed
        res_create = intake_tools.dispatch("create_request", {"title": "Intake Test", "description": "D"})
        self.assertTrue(res_create["ok"])
        req_id = res_create["request"]["id"]

        # Get is allowed
        res_get = intake_tools.dispatch("get_request", {"request_id": req_id})
        self.assertTrue(res_get["ok"])

        # Submit is denied
        res_submit = intake_tools.dispatch("submit_request", {"request_id": req_id})
        self.assertFalse(res_submit["ok"])
        self.assertEqual(res_submit["error"]["code"], "TOOL_NOT_ALLOWED")

        # Transition is denied
        res_trans = intake_tools.dispatch(
            "transition_request",
            {"request_id": req_id, "action": "cancel"},
        )
        self.assertFalse(res_trans["ok"])
        self.assertEqual(res_trans["error"]["code"], "TOOL_NOT_ALLOWED")

    def test_dispatch_validates_arguments_with_pydantic(self) -> None:
        """Missing required arguments triggers TOOL_VALIDATION_ERROR."""
        toolbox = ToolBox(self.service, self.creator_alice)

        # Missing 'title' parameter
        res = toolbox.dispatch("create_request", {"description": "Missing title"})
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], "TOOL_VALIDATION_ERROR")

    def test_unknown_tool_rejected(self) -> None:
        """Completely unknown tool names are rejected."""
        toolbox = ToolBox(self.service, self.creator_alice)
        res = toolbox.dispatch("execute_arbitrary_code", {"cmd": "rm -rf"})
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], "TOOL_NOT_ALLOWED")


if __name__ == "__main__":
    unittest.main()
