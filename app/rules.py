"""Business rules and state machine definitions for the approval flow.

This module defines the canonical roles, statuses, and state-transition rules.
All state transitions in the backend must adhere to the rules declared here.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Tuple


class Role(str, Enum):
    """User roles participating in the approval workflow."""
    CREATOR = "Creator"
    REVIEWER = "Reviewer"


class Status(str, Enum):
    """Lifecycle statuses of a request."""
    DRAFT = "Draft"
    SUBMITTED = "Submitted"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"


@dataclass(frozen=True)
class RuleConfig:
    """Configuration defining constraints for a single workflow action."""
    action: str
    allowed_role: Role
    from_statuses: Tuple[Status, ...]
    to_status: Status
    owner_only: bool


# Canonical state machine transition rules.
# The AI suggests; a deterministic backend decides.
# - Only Creators can create, submit and cancel.
# - Only Reviewers can approve or reject.
# - Only Submitted requests can become Approved or Rejected.
# - An Approved request cannot be cancelled.
# - Terminal statuses: Approved, Rejected, Cancelled cannot transition further.
RULES: Dict[str, RuleConfig] = {
    "submit": RuleConfig(
        action="submit",
        allowed_role=Role.CREATOR,
        from_statuses=(Status.DRAFT,),
        to_status=Status.SUBMITTED,
        owner_only=True,
    ),
    "approve": RuleConfig(
        action="approve",
        allowed_role=Role.REVIEWER,
        from_statuses=(Status.SUBMITTED,),
        to_status=Status.APPROVED,
        owner_only=False,
    ),
    "reject": RuleConfig(
        action="reject",
        allowed_role=Role.REVIEWER,
        from_statuses=(Status.SUBMITTED,),
        to_status=Status.REJECTED,
        owner_only=False,
    ),
    "cancel": RuleConfig(
        action="cancel",
        allowed_role=Role.CREATOR,
        from_statuses=(Status.DRAFT, Status.SUBMITTED),
        to_status=Status.CANCELLED,
        owner_only=True,
    ),
}

# Validation limits
MAX_TITLE_LENGTH: int = 120
MAX_DESCRIPTION_LENGTH: int = 5000
