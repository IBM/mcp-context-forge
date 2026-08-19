# -*- coding: utf-8 -*-
"""Schemas for process-local asynchronous tool invocation jobs."""

# Standard
from datetime import datetime
from typing import Any, Dict, Literal, Optional

# Third-Party
from pydantic import BaseModel, ConfigDict, Field

AsyncJobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class AsyncToolJobCreate(BaseModel):
    """Queue one governed ToolService invocation."""

    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(..., min_length=1, max_length=300)
    arguments: Dict[str, Any] = Field(default_factory=dict)
    headers: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, str] = Field(default_factory=dict)
    timeout_seconds: Optional[float] = Field(default=None, gt=0, le=600)


class AsyncJobErrorRead(BaseModel):
    """Sanitized terminal error returned to the task owner."""

    type: str
    message: str


class AsyncJobSummaryRead(BaseModel):
    """Owner-scoped asynchronous job summary without retained result data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    tool_id: str
    tool_name: str
    status: AsyncJobStatus
    timeout_seconds: float
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    error: Optional[AsyncJobErrorRead] = None


class AsyncJobRead(AsyncJobSummaryRead):
    """Detailed asynchronous job state returned for a single job."""

    result: Optional[Dict[str, Any]] = None


class AsyncJobListResponse(BaseModel):
    """Bounded list of jobs belonging to the authenticated caller."""

    data: list[AsyncJobSummaryRead]
    count: int
