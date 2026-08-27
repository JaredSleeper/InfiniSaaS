from __future__ import annotations

from fastapi import APIRouter

from src.db import get_pool

router = APIRouter()


@router.get("")
async def overview() -> dict:
    pool = await get_pool()
    projects = await pool.fetch("SELECT * FROM projects ORDER BY created_at")
    experiments = await pool.fetch(
        """
        SELECT e.*, p.name AS project_name, p.slug AS project_slug,
               p.accent_color AS project_accent
        FROM experiments e JOIN projects p ON p.id = e.project_id
        WHERE e.status IN ('planned', 'running')
        ORDER BY e.updated_at DESC
        """
    )
    learnings = await pool.fetch(
        """
        SELECT l.*, p.name AS project_name, p.accent_color AS project_accent
        FROM learnings l LEFT JOIN projects p ON p.id = l.project_id
        ORDER BY l.created_at DESC LIMIT 8
        """
    )
    key_series = await pool.fetch(
        """
        SELECT m.project_id, m.id AS metric_id, m.key, m.name, m.unit, m.kind,
               mp.ts, mp.value
        FROM metrics m
        LEFT JOIN metric_points mp
            ON mp.metric_id = m.id AND mp.ts > now() - interval '90 days'
        WHERE m.is_key
        ORDER BY m.project_id, mp.ts
        """
    )

    series: dict = {}
    for r in key_series:
        entry = series.setdefault(
            str(r["project_id"]),
            {
                "metric_id": str(r["metric_id"]),
                "key": r["key"],
                "name": r["name"],
                "unit": r["unit"],
                "kind": r["kind"],
                "points": [],
            },
        )
        if r["ts"] is not None:
            entry["points"].append({"ts": r["ts"].isoformat(), "value": float(r["value"])})

    counts = await pool.fetchrow(
        """
        SELECT
            (SELECT count(*) FROM experiments WHERE status = 'running') AS running_experiments,
            (SELECT count(*) FROM campaigns WHERE status = 'active') AS active_campaigns,
            (SELECT count(*) FROM learnings) AS total_learnings
        """
    )

    return {
        "projects": [
            {
                **{k: v for k, v in dict(p).items() if k != "ingest_token"},
                "id": str(p["id"]),
                "created_at": p["created_at"].isoformat(),
                "updated_at": p["updated_at"].isoformat(),
                "key_metric": series.get(str(p["id"])),
            }
            for p in projects
        ],
        "active_experiments": [
            {
                **dict(e),
                "id": str(e["id"]),
                "project_id": str(e["project_id"]),
                "target_metric_id": str(e["target_metric_id"]) if e["target_metric_id"] else None,
                "started_at": e["started_at"].isoformat() if e["started_at"] else None,
                "ended_at": e["ended_at"].isoformat() if e["ended_at"] else None,
                "created_at": e["created_at"].isoformat(),
                "updated_at": e["updated_at"].isoformat(),
            }
            for e in experiments
        ],
        "recent_learnings": [
            {
                "id": str(li["id"]),
                "project_id": str(li["project_id"]) if li["project_id"] else None,
                "project_name": li["project_name"],
                "project_accent": li["project_accent"],
                "content": li["content"],
                "created_at": li["created_at"].isoformat(),
            }
            for li in learnings
        ],
        "counts": dict(counts),
    }
