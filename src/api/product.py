"""Product layer: feature requests, customer feedback, releases, content calendar."""

from __future__ import annotations

from src.api.crud import make_router
from src.models import (
    ContentCreate,
    ContentOut,
    ContentUpdate,
    FeatureRequestCreate,
    FeatureRequestOut,
    FeatureRequestUpdate,
    FeedbackCreate,
    FeedbackOut,
    FeedbackUpdate,
    ReleaseCreate,
    ReleaseOut,
    ReleaseUpdate,
    SeoKeywordCreate,
    SeoKeywordOut,
    SeoKeywordUpdate,
)

feature_requests = make_router(
    "feature_requests",
    FeatureRequestCreate,
    FeatureRequestUpdate,
    FeatureRequestOut,
    order_by=(
        "CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,"
        " votes DESC, created_at DESC"
    ),
    filters=("status",),
)

feedback = make_router(
    "feedback",
    FeedbackCreate,
    FeedbackUpdate,
    FeedbackOut,
    filters=("source",),
    has_updated_at=False,
)

releases = make_router(
    "releases",
    ReleaseCreate,
    ReleaseUpdate,
    ReleaseOut,
    order_by="released_at DESC",
    filters=("source",),
    has_updated_at=False,
    limit=200,
)

content = make_router(
    "content_items",
    ContentCreate,
    ContentUpdate,
    ContentOut,
    order_by="coalesce(publish_at, created_at) DESC",
    filters=("status", "channel"),
)

seo_keywords = make_router(
    "seo_keywords",
    SeoKeywordCreate,
    SeoKeywordUpdate,
    SeoKeywordOut,
    order_by="clicks DESC NULLS LAST, position ASC NULLS LAST, created_at DESC",
    filters=("source",),
    has_updated_at=False,
)
