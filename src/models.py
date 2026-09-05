from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


# ---------------------------------------------------------------------------
# v2
# ---------------------------------------------------------------------------

FeatureStatus = Literal["inbox", "considering", "planned", "building", "shipped", "declined"]
Priority = Literal["low", "medium", "high", "critical"]
FeedbackSource = Literal["email", "in_app", "social", "interview", "support", "review", "other"]
Sentiment = Literal["positive", "neutral", "negative"]
ContentStatus = Literal["idea", "drafting", "scheduled", "published"]
CostCategory = Literal["infra", "ads", "tools", "llm", "contractors", "other"]
AdPlatform = Literal["google", "meta", "reddit", "x", "tiktok", "linkedin", "other"]
AlertCondition = Literal["below", "above", "drop_pct", "stale_days"]
Provider = Literal["stripe", "github", "railway", "gsc", "slack", "custom"]
AgentKind = Literal["weekly_brief", "seo", "ads", "analytics", "landing_pages", "custom"]
AgentSchedule = Literal["manual", "daily", "weekly"]
RecKind = Literal["experiment", "task", "content", "alert", "insight", "landing_page"]
RecStatus = Literal["open", "accepted", "dismissed", "done"]
Level = Literal["low", "medium", "high"]
DevinSource = Literal["manual", "feature_request", "recommendation", "experiment", "landing_page"]
LandingPageStatus = Literal["idea", "draft", "live", "retired"]


class ProjectUpdateV2(ProjectUpdate):
    repo_url: str | None = None
    settings: dict | None = None


class ProjectOutV2(ProjectOut):
    repo_url: str | None = None
    settings: dict = Field(default_factory=dict)


class IntegrationUpsert(BaseModel):
    project_id: UUID | None = None
    config: dict = Field(default_factory=dict)
    secret: str | None = None


class IntegrationOut(BaseModel):
    id: UUID
    project_id: UUID | None
    provider: Provider
    config: dict
    has_secret: bool
    status: str
    status_detail: str
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime
    meta: dict = Field(default_factory=dict)


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    user_key: str | None = None
    ts: datetime | None = None
    properties: dict = Field(default_factory=dict)


class EventsRequest(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=500)


class CostCreate(BaseModel):
    category: CostCategory = "other"
    amount: float = Field(ge=0)
    period_start: date
    period_end: date
    note: str = ""


class CostUpdate(BaseModel):
    category: CostCategory | None = None
    amount: float | None = Field(default=None, ge=0)
    period_start: date | None = None
    period_end: date | None = None
    note: str | None = None


class CostOut(BaseModel):
    id: UUID
    project_id: UUID | None
    category: CostCategory
    amount: float
    period_start: date
    period_end: date
    note: str
    source: str
    created_at: datetime


class AdSpendIn(BaseModel):
    platform: AdPlatform = "other"
    campaign_id: UUID | None = None
    day: date
    spend: float = Field(default=0, ge=0)
    impressions: int = Field(default=0, ge=0)
    clicks: int = Field(default=0, ge=0)
    conversions: int = Field(default=0, ge=0)


class AdSpendOut(BaseModel):
    id: int
    project_id: UUID
    campaign_id: UUID | None
    platform: AdPlatform
    day: date
    spend: float
    impressions: int
    clicks: int
    conversions: int
    source: str
    created_at: datetime


class TargetCreate(BaseModel):
    metric_id: UUID
    target_value: float
    due_date: date | None = None
    label: str = ""


class TargetOut(TargetCreate):
    id: UUID
    created_at: datetime


class AlertRuleCreate(BaseModel):
    metric_id: UUID
    condition: AlertCondition
    threshold: float
    window_days: int = 7
    enabled: bool = True


class AlertRuleOut(AlertRuleCreate):
    id: UUID
    last_fired_at: datetime | None
    created_at: datetime


class WikiPageUpsert(BaseModel):
    title: str | None = None
    content: str = ""
    sort_order: int | None = None


class WikiPageOut(BaseModel):
    id: UUID
    project_id: UUID
    slug: str
    title: str
    content: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class FeatureRequestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    status: FeatureStatus = "inbox"
    priority: Priority = "medium"
    votes: int = 0
    experiment_id: UUID | None = None


class FeatureRequestUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: FeatureStatus | None = None
    priority: Priority | None = None
    votes: int | None = None
    experiment_id: UUID | None = None


class FeatureRequestOut(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    description: str
    status: FeatureStatus
    priority: Priority
    votes: int
    experiment_id: UUID | None
    created_at: datetime
    updated_at: datetime


class FeedbackCreate(BaseModel):
    source: FeedbackSource = "other"
    author: str = ""
    content: str = Field(min_length=1)
    sentiment: Sentiment = "neutral"
    feature_request_id: UUID | None = None


class FeedbackUpdate(BaseModel):
    source: FeedbackSource | None = None
    author: str | None = None
    content: str | None = None
    sentiment: Sentiment | None = None
    feature_request_id: UUID | None = None


class FeedbackOut(BaseModel):
    id: UUID
    project_id: UUID
    source: FeedbackSource
    author: str
    content: str
    sentiment: Sentiment
    feature_request_id: UUID | None
    created_at: datetime


class ReleaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    url: str | None = None
    released_at: datetime | None = None


class ReleaseUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    url: str | None = None
    released_at: datetime | None = None


class ReleaseOut(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    body: str
    url: str | None
    external_id: str | None
    source: str
    released_at: datetime
    created_at: datetime


class ContentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    channel: Channel = "content"
    status: ContentStatus = "idea"
    publish_at: datetime | None = None
    url: str | None = None
    notes: str = ""
    campaign_id: UUID | None = None


class ContentUpdate(BaseModel):
    title: str | None = None
    channel: Channel | None = None
    status: ContentStatus | None = None
    publish_at: datetime | None = None
    url: str | None = None
    notes: str | None = None
    campaign_id: UUID | None = None


class ContentOut(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    channel: Channel
    status: ContentStatus
    publish_at: datetime | None
    url: str | None
    notes: str
    campaign_id: UUID | None
    created_at: datetime
    updated_at: datetime


class SeoKeywordCreate(BaseModel):
    keyword: str = Field(min_length=1, max_length=200)
    target_url: str | None = None
    position: float | None = None
    notes: str = ""


class SeoKeywordUpdate(BaseModel):
    keyword: str | None = None
    target_url: str | None = None
    position: float | None = None
    notes: str | None = None


class SeoKeywordOut(BaseModel):
    id: UUID
    project_id: UUID
    keyword: str
    target_url: str | None
    position: float | None
    clicks: int | None
    impressions: int | None
    ctr: float | None
    source: str
    checked_at: datetime | None
    notes: str
    created_at: datetime


class SeoAuditOut(BaseModel):
    id: UUID
    project_id: UUID
    url: str
    ts: datetime
    score: int
    findings: list
    page: dict


class DevinSessionCreate(BaseModel):
    prompt: str = Field(min_length=1)
    title: str = ""
    project_id: UUID | None = None
    source_type: DevinSource = "manual"
    source_id: UUID | None = None
    include_wiki: bool = True


class DevinMessage(BaseModel):
    message: str = Field(min_length=1)


class DevinSessionOut(BaseModel):
    id: UUID
    project_id: UUID | None
    session_id: str
    url: str
    title: str
    prompt: str
    status: str
    pr_url: str | None
    source_type: DevinSource
    source_id: UUID | None
    created_at: datetime
    updated_at: datetime


class DevinPromptPreview(BaseModel):
    prompt: str
    title: str


class AgentCreate(BaseModel):
    project_id: UUID | None = None
    kind: AgentKind = "custom"
    name: str = Field(min_length=1, max_length=120)
    instructions: str = ""
    schedule: AgentSchedule = "manual"
    enabled: bool = True
    config: dict = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    name: str | None = None
    instructions: str | None = None
    schedule: AgentSchedule | None = None
    enabled: bool | None = None
    config: dict | None = None


class AgentOut(BaseModel):
    id: UUID
    project_id: UUID | None
    kind: AgentKind
    name: str
    instructions: str
    schedule: AgentSchedule
    enabled: bool
    config: dict
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentRunOut(BaseModel):
    id: UUID
    agent_id: UUID
    status: str
    trigger: str
    started_at: datetime | None
    finished_at: datetime | None
    summary: str
    error: str
    input_tokens: int
    output_tokens: int
    created_at: datetime


class RecommendationUpdate(BaseModel):
    status: RecStatus | None = None
    title: str | None = None
    body: str | None = None


class RecommendationOut(BaseModel):
    id: UUID
    agent_run_id: UUID | None
    agent_id: UUID | None
    project_id: UUID | None
    title: str
    body: str
    kind: RecKind
    impact: Level
    effort: Level
    status: RecStatus
    experiment_id: UUID | None
    devin_session_id: UUID | None
    landing_page_id: UUID | None = None
    data: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


# ── Landing pages ────────────────────────────────────────────────────────────


def _normalize_path(value: str) -> str:
    value = value.strip()
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        value = parsed.path or "/"
    if not value.startswith("/"):
        value = "/" + value
    if len(value) > 1:
        value = value.rstrip("/")
    if any(c.isspace() for c in value):
        raise ValueError("path must not contain whitespace")
    return value


class LandingPageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    path: str = Field(min_length=1, max_length=400)
    url: str | None = Field(default=None, max_length=800)
    headline: str = Field(default="", max_length=300)
    angle: str = ""
    target_keyword: str = Field(default="", max_length=200)
    channel: Channel = "seo"
    status: LandingPageStatus = "idea"
    brief: str = ""
    notes: str = ""
    campaign_id: UUID | None = None
    experiment_id: UUID | None = None

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        return _normalize_path(v)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v


class LandingPageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    path: str | None = Field(default=None, min_length=1, max_length=400)
    url: str | None = Field(default=None, max_length=800)
    headline: str | None = Field(default=None, max_length=300)
    angle: str | None = None
    target_keyword: str | None = Field(default=None, max_length=200)
    channel: Channel | None = None
    status: LandingPageStatus | None = None
    brief: str | None = None
    notes: str | None = None
    campaign_id: UUID | None = None
    experiment_id: UUID | None = None

    @field_validator("path")
    @classmethod
    def _path(cls, v: str | None) -> str | None:
        return None if v is None else _normalize_path(v)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v or None


class LandingPageOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    path: str
    url: str | None
    headline: str
    angle: str
    target_keyword: str
    channel: Channel
    status: LandingPageStatus
    brief: str
    notes: str
    campaign_id: UUID | None
    experiment_id: UUID | None
    created_at: datetime
    updated_at: datetime


class LandingPagePerf(BaseModel):
    """One row of the cross-project comparison table."""

    page: LandingPageOut
    project_name: str
    project_slug: str
    accent_color: str
    days: int
    pageviews: int
    visitors: int
    signups: int
    pays: int
    signup_rate: float | None
    pay_rate: float | None
    gsc_clicks: int | None
    gsc_impressions: int | None
    gsc_ctr: float | None
    gsc_position: float | None
    gsc_keywords: int
    ad_spend: float | None
    ad_clicks: int | None
    ad_conversions: int | None
    cpa: float | None
    seo_score: int | None
    seo_audit_at: datetime | None
    campaign_name: str | None


class DiscoveredPath(BaseModel):
    """A `path` seen in visit events that has no landing_pages row yet."""

    project_id: UUID
    project_name: str
    path: str
    pageviews: int
    visitors: int


class LandingPerformance(BaseModel):
    days: int
    pages: list[LandingPagePerf]
    discovered: list[DiscoveredPath]
