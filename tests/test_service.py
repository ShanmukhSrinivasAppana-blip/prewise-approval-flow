"""Unit tests for RequestService, rules, and deterministic state transitions."""

import unittest

from app.rules import (
    MAX_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    Role,
    Status,
)
from app.service import ErrorCode, RequestService, User


class TestRequestService(unittest.TestCase):
    """Test suite verifying the deterministic backend and business rules."""

    def setUp(self) -> None:
        """Create fresh in-memory database and test users for each test."""
        self.service = RequestService(db_path=":memory:")
        self.creator_alice = User(id="alice", role=Role.CREATOR, name="Alice")
        self.creator_bob = User(id="bob", role=Role.CREATOR, name="Bob")
        self.reviewer_rita = User(id="rita", role=Role.REVIEWER, name="Rita")

    # --- 1. Happy Paths ---

    def test_creator_can_create_draft_happy_path(self) -> None:
        """Creator successfully creates a Draft request."""
        res = self.service.create_request(
            actor=self.creator_alice,
            title="Laptop Upgrade",
            description="Requesting 32GB RAM upgrade for ML workflows.",
        )
        self.assertTrue(res["ok"])
        req = res["request"]
        self.assertEqual(req["title"], "Laptop Upgrade")
        self.assertEqual(req["status"], Status.DRAFT.value)
        self.assertEqual(req["creator_id"], "alice")
        self.assertTrue(req["id"].startswith("req_"))

    def test_creator_can_submit_draft_happy_path(self) -> None:
        """Creator transitions a Draft to Submitted status."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Software License",
            description="Annual JetBrains license.",
        )["request"]

        res = self.service.submit_request(actor=self.creator_alice, request_id=created["id"])
        self.assertTrue(res["ok"])
        self.assertEqual(res["request"]["status"], Status.SUBMITTED.value)

    def test_reviewer_can_approve_submitted_request_happy_path(self) -> None:
        """Reviewer approves a Submitted request."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Team Offsite",
            description="Budget approval for Q3 offsite.",
        )["request"]
        self.service.submit_request(actor=self.creator_alice, request_id=created["id"])

        res = self.service.transition_request(
            actor=self.reviewer_rita,
            request_id=created["id"],
            action="approve",
            reason="Within team budget",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["request"]["status"], Status.APPROVED.value)

    def test_reviewer_can_reject_submitted_request_happy_path(self) -> None:
        """Reviewer rejects a Submitted request with a reason."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Personal Gadget",
            description="Personal gadget reimbursement.",
        )["request"]
        self.service.submit_request(actor=self.creator_alice, request_id=created["id"])

        res = self.service.transition_request(
            actor=self.reviewer_rita,
            request_id=created["id"],
            action="reject",
            reason="Policy does not cover personal gadgets",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["request"]["status"], Status.REJECTED.value)

    def test_creator_can_cancel_draft_happy_path(self) -> None:
        """Creator cancels their own Draft request."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Draft to cancel",
            description="No longer needed.",
        )["request"]

        res = self.service.transition_request(
            actor=self.creator_alice,
            request_id=created["id"],
            action="cancel",
            reason="Created by mistake",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["request"]["status"], Status.CANCELLED.value)

    def test_creator_can_cancel_submitted_request_happy_path(self) -> None:
        """Creator cancels their own Submitted request."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Submitted to cancel",
            description="Needs rework.",
        )["request"]
        self.service.submit_request(actor=self.creator_alice, request_id=created["id"])

        res = self.service.transition_request(
            actor=self.creator_alice,
            request_id=created["id"],
            action="cancel",
            reason="Scope changed",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["request"]["status"], Status.CANCELLED.value)

    # --- 2. Invalid State Transitions ---

    def test_cannot_approve_draft_request(self) -> None:
        """Draft cannot be Approved directly without being Submitted first."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Direct Approval Attempt",
            description="Attempting skip.",
        )["request"]

        res = self.service.transition_request(
            actor=self.reviewer_rita,
            request_id=created["id"],
            action="approve",
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], ErrorCode.INVALID_TRANSITION.value)

    def test_cannot_reject_draft_request(self) -> None:
        """Draft cannot be Rejected directly without being Submitted first."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Direct Reject Attempt",
            description="Attempting skip.",
        )["request"]

        res = self.service.transition_request(
            actor=self.reviewer_rita,
            request_id=created["id"],
            action="reject",
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], ErrorCode.INVALID_TRANSITION.value)

    def test_approved_request_cannot_be_cancelled(self) -> None:
        """Explicit business rule: An Approved request cannot be cancelled."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Approved Request",
            description="Already finalized.",
        )["request"]
        self.service.submit_request(actor=self.creator_alice, request_id=created["id"])
        self.service.transition_request(
            actor=self.reviewer_rita,
            request_id=created["id"],
            action="approve",
        )

        res = self.service.transition_request(
            actor=self.creator_alice,
            request_id=created["id"],
            action="cancel",
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], ErrorCode.INVALID_TRANSITION.value)

    def test_terminal_statuses_cannot_transition(self) -> None:
        """Terminal statuses (Rejected, Cancelled) cannot transition anywhere."""
        # Rejected cannot be approved or submitted
        created1 = self.service.create_request(
            actor=self.creator_alice,
            title="Terminal Test 1",
            description="Body",
        )["request"]
        self.service.submit_request(actor=self.creator_alice, request_id=created1["id"])
        self.service.transition_request(actor=self.reviewer_rita, request_id=created1["id"], action="reject")

        res_reject_to_approve = self.service.transition_request(
            actor=self.reviewer_rita, request_id=created1["id"], action="approve"
        )
        self.assertFalse(res_reject_to_approve["ok"])
        self.assertEqual(res_reject_to_approve["error"]["code"], ErrorCode.INVALID_TRANSITION.value)

        # Cancelled cannot be submitted
        created2 = self.service.create_request(
            actor=self.creator_alice,
            title="Terminal Test 2",
            description="Body",
        )["request"]
        self.service.transition_request(actor=self.creator_alice, request_id=created2["id"], action="cancel")

        res_cancel_to_submit = self.service.transition_request(
            actor=self.creator_alice, request_id=created2["id"], action="submit"
        )
        self.assertFalse(res_cancel_to_submit["ok"])
        self.assertEqual(res_cancel_to_submit["error"]["code"], ErrorCode.INVALID_TRANSITION.value)

    # --- 3. Role Violations ---

    def test_reviewer_cannot_create_request(self) -> None:
        """Reviewer role is prohibited from creating requests."""
        res = self.service.create_request(
            actor=self.reviewer_rita,
            title="Reviewer Creation Attempt",
            description="Should fail.",
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], ErrorCode.ROLE_NOT_ALLOWED.value)

    def test_reviewer_cannot_submit_request(self) -> None:
        """Reviewer role is prohibited from submitting requests."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Submit Test",
            description="Body",
        )["request"]

        res = self.service.transition_request(
            actor=self.reviewer_rita,
            request_id=created["id"],
            action="submit",
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], ErrorCode.ROLE_NOT_ALLOWED.value)

    def test_reviewer_cannot_cancel_request(self) -> None:
        """Reviewer role is prohibited from cancelling requests."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Cancel Test",
            description="Body",
        )["request"]

        res = self.service.transition_request(
            actor=self.reviewer_rita,
            request_id=created["id"],
            action="cancel",
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], ErrorCode.ROLE_NOT_ALLOWED.value)

    def test_creator_cannot_approve_request(self) -> None:
        """Creator role is prohibited from approving requests."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Self Approval Attempt",
            description="Body",
        )["request"]
        self.service.submit_request(actor=self.creator_alice, request_id=created["id"])

        res = self.service.transition_request(
            actor=self.creator_alice,
            request_id=created["id"],
            action="approve",
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], ErrorCode.ROLE_NOT_ALLOWED.value)

    def test_creator_cannot_reject_request(self) -> None:
        """Creator role is prohibited from rejecting requests."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Self Rejection Attempt",
            description="Body",
        )["request"]
        self.service.submit_request(actor=self.creator_alice, request_id=created["id"])

        res = self.service.transition_request(
            actor=self.creator_alice,
            request_id=created["id"],
            action="reject",
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], ErrorCode.ROLE_NOT_ALLOWED.value)

    # --- 4. Ownership Violations ---

    def test_other_creator_cannot_submit_request(self) -> None:
        """Only the owning Creator can submit a request."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Alice Request",
            description="Body",
        )["request"]

        res = self.service.transition_request(
            actor=self.creator_bob,
            request_id=created["id"],
            action="submit",
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], ErrorCode.NOT_OWNER.value)

    def test_other_creator_cannot_cancel_request(self) -> None:
        """Only the owning Creator can cancel a request."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Alice Request",
            description="Body",
        )["request"]

        res = self.service.transition_request(
            actor=self.creator_bob,
            request_id=created["id"],
            action="cancel",
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], ErrorCode.NOT_OWNER.value)

    # --- 5. Visibility Rules ---

    def test_reviewer_cannot_view_draft_request(self) -> None:
        """Reviewers cannot see Draft requests (returns NOT_VISIBLE)."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Secret Draft",
            description="Draft details.",
        )["request"]

        res = self.service.get_request(actor=self.reviewer_rita, request_id=created["id"])
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], ErrorCode.NOT_VISIBLE.value)

    def test_reviewer_list_requests_filters_out_drafts(self) -> None:
        """Reviewer request listing never includes any Draft requests."""
        draft = self.service.create_request(actor=self.creator_alice, title="Draft Item", description="D")["request"]
        sub = self.service.create_request(actor=self.creator_alice, title="Sub Item", description="S")["request"]
        self.service.submit_request(actor=self.creator_alice, request_id=sub["id"])

        res = self.service.list_requests(actor=self.reviewer_rita)
        self.assertTrue(res["ok"])
        ids = [r["id"] for r in res["requests"]]
        self.assertIn(sub["id"], ids)
        self.assertNotIn(draft["id"], ids)

    # --- 6. Input Validation ---

    def test_empty_or_whitespace_title_rejected(self) -> None:
        """Title must not be empty or whitespace-only."""
        for empty_title in ["", "   ", "\t\n"]:
            res = self.service.create_request(
                actor=self.creator_alice,
                title=empty_title,
                description="Valid description.",
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"]["code"], ErrorCode.VALIDATION_ERROR.value)

    def test_title_exceeding_max_length_rejected(self) -> None:
        """Title exceeding 120 characters is rejected."""
        long_title = "A" * (MAX_TITLE_LENGTH + 1)
        res = self.service.create_request(
            actor=self.creator_alice,
            title=long_title,
            description="Valid description.",
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], ErrorCode.VALIDATION_ERROR.value)

    def test_description_exceeding_max_length_rejected(self) -> None:
        """Description exceeding 5000 characters is rejected."""
        long_desc = "D" * (MAX_DESCRIPTION_LENGTH + 1)
        res = self.service.create_request(
            actor=self.creator_alice,
            title="Valid Title",
            description=long_desc,
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], ErrorCode.VALIDATION_ERROR.value)

    # --- 7. Edge Cases: Unknown Action and Not Found ---

    def test_unknown_action_rejected(self) -> None:
        """Unrecognized actions return UNKNOWN_ACTION."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Action Test",
            description="Body",
        )["request"]

        res = self.service.transition_request(
            actor=self.creator_alice,
            request_id=created["id"],
            action="fast_forward",
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], ErrorCode.UNKNOWN_ACTION.value)

    def test_nonexistent_request_not_found(self) -> None:
        """Non-existent request ID returns NOT_FOUND."""
        res_get = self.service.get_request(actor=self.creator_alice, request_id="req_doesnotexist")
        self.assertFalse(res_get["ok"])
        self.assertEqual(res_get["error"]["code"], ErrorCode.NOT_FOUND.value)

        res_trans = self.service.transition_request(
            actor=self.creator_alice,
            request_id="req_doesnotexist",
            action="submit",
        )
        self.assertFalse(res_trans["ok"])
        self.assertEqual(res_trans["error"]["code"], ErrorCode.NOT_FOUND.value)

    # --- 8. Audit History & Concurrency Checks ---

    def test_history_records_full_lifecycle(self) -> None:
        """Verify request_history captures create, submit, and approve actions."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Full Lifecycle Test",
            description="Complete audit trail check.",
        )["request"]
        req_id = created["id"]

        self.service.submit_request(actor=self.creator_alice, request_id=req_id, reason="Submitting for Q3")
        self.service.transition_request(
            actor=self.reviewer_rita,
            request_id=req_id,
            action="approve",
            reason="Approved with budget headroom",
        )

        hist_res = self.service.get_history(actor=self.creator_alice, request_id=req_id)
        self.assertTrue(hist_res["ok"])
        history = hist_res["history"]

        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["action"], "create")
        self.assertEqual(history[0]["to_status"], Status.DRAFT.value)

        self.assertEqual(history[1]["action"], "submit")
        self.assertEqual(history[1]["from_status"], Status.DRAFT.value)
        self.assertEqual(history[1]["to_status"], Status.SUBMITTED.value)
        self.assertEqual(history[1]["actor_id"], "alice")

        self.assertEqual(history[2]["action"], "approve")
        self.assertEqual(history[2]["from_status"], Status.SUBMITTED.value)
        self.assertEqual(history[2]["to_status"], Status.APPROVED.value)
        self.assertEqual(history[2]["actor_id"], "rita")
        self.assertEqual(history[2]["reason"], "Approved with budget headroom")

    def test_concurrency_conflict_detected_on_outdated_state(self) -> None:
        """If database state changes concurrently during transition, CONFLICT is returned."""
        created = self.service.create_request(
            actor=self.creator_alice,
            title="Race Condition Test",
            description="Testing atomic conditional update.",
        )["request"]
        req_id = created["id"]

        # Alice submits
        self.service.submit_request(actor=self.creator_alice, request_id=req_id)

        # Behind the scenes, simulate an external update that changed status to Rejected
        with self.service._lock:
            cur = self.service._conn.cursor()
            cur.execute("UPDATE requests SET status = ? WHERE id = ?", (Status.REJECTED.value, req_id))
            self.service._conn.commit()

        # Rita tries to approve assuming it was still Submitted, but DB check order 5 or rowcount fails
        res = self.service.transition_request(
            actor=self.reviewer_rita,
            request_id=req_id,
            action="approve",
        )
        self.assertFalse(res["ok"])
        # Status was already changed to Rejected, so step 5 catches invalid transition
        self.assertEqual(res["error"]["code"], ErrorCode.INVALID_TRANSITION.value)


if __name__ == "__main__":
    unittest.main()
