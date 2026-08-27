from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Stage = Literal["idea", "building", "live", "scaling", "paused", "retired"]
Health = Literal["unknown", "healthy", "watch", "critical"]
Channel = Literal[
    "seo", "paid", "social", "content", "email", "community", "product", "pricing", "other"
]
ExperimentStatus = Literal["idea", "planned", "running", "concluded", "abandoned"]
ExperimentResult = Literal["positive", "negative", "inconclusive"]
CampaignStatus = Literal["planned", "active", "paused", "done"]
MetricKind = Literal["gauge", "counter", "currency"]


class ProjectCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=120)
    url: str | None = None
    stage: Stage = "idea"
    description: str = ""
    accent_color: str = "#4C8DFF"


class ProjectUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    stage: Stage | None = None
    health: Health | None = None
    description: str | None = None
    accent_color: str | None = None


class ProjectOut(BaseModel):
    id: UUID
    slug: str
    name: str
    url: str | None
    stage: Stage
    health: Health
    description: str
    accent_color: str
    created_at: datetime
    updated_at: datetime


class MetricCreate(BaseModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=120)
    unit: str = ""
    kind: MetricKind = "gauge"
    is_key: bool = False


class MetricOut(BaseModel):
    id: UUID
    project_id: UUID
    key: str
    name: str
    unit: str
    kind: MetricKind
    is_key: bool


class MetricPointIn(BaseModel):
    value: float
    ts: datetime | None = None
    source: str = "manual"


class IngestPoint(BaseModel):
    metric: str
    value: float
    ts: datetime | None = None


class IngestRequest(BaseModel):
    points: list[IngestPoint] = Field(min_length=1, max_length=500)


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    hypothesis: str = ""
    channel: Channel = "product"
    target_metric_id: UUID | None = None
    status: ExperimentStatus = "idea"


class ExperimentUpdate(BaseModel):
    name: str | None = None
    hypothesis: str | None = None
    channel: Channel | None = None
    target_metric_id: UUID | None = None
    status: ExperimentStatus | None = None
    result: ExperimentResult | None = None
    learnings: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class ExperimentOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    hypothesis: str
    channel: Channel
    target_metric_id: UUID | None
    status: ExperimentStatus
    result: ExperimentResult | None
    learnings: str
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    channel: Channel = "content"
    status: CampaignStatus = "planned"
    budget: float | None = None
    url: str | None = None
    notes: str = ""


class CampaignUpdate(BaseModel):
    name: str | None = None
    channel: Channel | None = None
    status: CampaignStatus | None = None
    budget: float | None = None
    url: str | None = None
    notes: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class CampaignOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    channel: Channel
    status: CampaignStatus
    budget: float | None
    url: str | None
    notes: str
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime


class LearningCreate(BaseModel):
    content: str = Field(min_length=1)
    project_id: UUID | None = None
    experiment_id: UUID | None = None


class LearningOut(BaseModel):
    id: UUID
    project_id: UUID | None
    experiment_id: UUID | None
    content: str
    created_at: datetime
