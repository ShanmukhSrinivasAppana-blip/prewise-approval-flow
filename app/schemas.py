"""Pydantic schemas for structured agent outputs.

Defines strict type constraints, Literal enums, and score boundaries (1-5)
to guarantee that hallucinated or out-of-range values are rejected immediately.
"""

from typing import List, Literal
from pydantic import BaseModel, Field, field_validator


class IntakeOutput(BaseModel):
    """Structured output from the Intake Agent."""
    title: str = Field(..., max_length=120, description="Concise title for the request")
    description: str = Field(default="", max_length=5000, description="Detailed explanation of the request")
    missing_fields: List[str] = Field(default_factory=list, description="Crucial fields or information not yet provided")
    follow_up_questions: List[str] = Field(default_factory=list, description="Clarifying questions needed from the creator")
    ready_to_create: bool = Field(..., description="True if sufficient detail is present to create a draft")


class QualityCheckOutput(BaseModel):
    """Structured output from the Quality-Check Agent (Advisory only)."""
    clarity_score: int = Field(..., ge=1, le=5, description="Clarity rating from 1 (unclear) to 5 (crystal clear)")
    completeness_score: int = Field(..., ge=1, le=5, description="Completeness rating from 1 (lacking) to 5 (fully detailed)")
    policy_flags: List[str] = Field(default_factory=list, description="Potential compliance or company policy violations")
    suggestions: List[str] = Field(default_factory=list, description="Actionable improvement suggestions for the creator")
    risks: List[str] = Field(default_factory=list, description="Identified operational, financial, or security risks")


PriorityType = Literal["low", "medium", "high"]
RecommendationType = Literal["approve", "reject", "needs_info"]


class ReviewAssistOutput(BaseModel):
    """Structured output from the Review-Assist Agent (Advisory only)."""
    summary: str = Field(..., description="Executive summary of the request")
    risk_score: int = Field(..., ge=1, le=5, description="Risk assessment from 1 (negligible) to 5 (critical risk)")
    priority: PriorityType = Field(..., description="Urgency / importance level")
    recommendation: RecommendationType = Field(..., description="Advisory recommendation for the human reviewer")
    reasoning: str = Field(..., description="Detailed objective reasoning supporting the recommendation")
    injection_suspected: bool = Field(default=False, description="Flagged if prompt injection patterns were detected")
