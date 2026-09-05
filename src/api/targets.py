from __future__ import annotations

import contextlib
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from src.db import get_pool
from src.integrations import slack
from src.models import AlertRuleCreate, AlertRuleOut, TargetCreate, TargetOut

router = APIRouter()


async def _metric_project(metric_id: UUID) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM metrics WHERE id = $1", metric_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Metric not found")
    return dict(row)


@router.get("/targets", response_model=list[TargetOut])
async def list_targets(project_id: UUID | None = Query(default=None)) -> list[TargetOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT t.* FROM metric_targets t JOIN metrics m ON m.id = t.metric_id
        WHERE ($1::uuid IS NULL OR m.project_id = $1) ORDER BY t.created_at DESC
        """,
        project_id,
    )
    return [TargetOut(**dict(r)) for r in rows]


@router.post("/targets", response_model=TargetOut, status_code=201)
async def create_target(body: TargetCreate) -> TargetOut:
    await _metric_project(body.metric_id)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO metric_targets (metric_id, target_value, due_date, label)
        VALUES ($1, $2, $3, $4) RETURNING *
        """,
        body.metric_id,
        body.target_value,
        body.due_date,
        body.label,
    )
    return TargetOut(**dict(row))


@router.delete("/targets/{target_id}", status_code=204)
async def delete_target(target_id: UUID) -> None:
    pool = await get_pool()
    await pool.execute("DELETE FROM metric_targets WHERE id = $1", target_id)


@router.get("/alerts", response_model=list[AlertRuleOut])
async def list_alerts(project_id: UUID | None = Query(default=None)) -> list[AlertRuleOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT a.* FROM alert_rules a JOIN metrics m ON m.id = a.metric_id
        WHERE ($1::uuid IS NULL OR m.project_id = $1) ORDER BY a.created_at DESC
        """,
        project_id,
    )
    return [AlertRuleOut(**dict(r)) for r in rows]


@router.post("/alerts", response_model=AlertRuleOut, status_code=201)
async def create_alert(body: AlertRuleCreate) -> AlertRuleOut:
    await _metric_project(body.metric_id)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO alert_rules (metric_id, condition, threshold, window_days, enabled)
        VALUES ($1, $2, $3, $4, $5) RETURNING *
        """,
        body.metric_id,
        body.condition,
        body.threshold,
        body.window_days,
        body.enabled,
    )
    return AlertRuleOut(**dict(row))


@router.delete("/alerts/{alert_id}", status_code=204)
async def delete_alert(alert_id: UUID) -> None:
    pool = await get_pool()
    await pool.execute("DELETE FROM alert_rules WHERE id = $1", alert_id)


async def evaluate_alerts() -> list[dict]:
    """Scheduler entrypoint. Fires each rule at most once per 24h; posts to Slack if set."""
    pool = await get_pool()
    rules = await pool.fetch(
        """
        SELECT a.*, m.key, m.name AS metric_name, m.unit, p.name AS project_name, p.id AS project_id
        FROM alert_rules a
        JOIN metrics m ON m.id = a.metric_id
        JOIN projects p ON p.id = m.project_id
        WHERE a.enabled
          AND (a.last_fired_at IS NULL OR a.last_fired_at < now() - interval '24 hours')
        """
    )
    fired = []
    for r in rules:
        stats = await pool.fetchrow(
            """
            SELECT
              (SELECT value FROM metric_points WHERE metric_id = $1
                 ORDER BY ts DESC LIMIT 1) AS last,
              (SELECT max(ts) FROM metric_points WHERE metric_id = $1) AS last_ts,
              (SELECT coalesce(sum(value), 0) FROM metric_points
                 WHERE metric_id = $1 AND ts > now() - make_interval(days => $2)) AS cur,
              (SELECT coalesce(sum(value), 0) FROM metric_points
                 WHERE metric_id = $1 AND ts <= now() - make_interval(days => $2)
                   AND ts > now() - make_interval(days => $2 * 2)) AS prev
            """,
            r["metric_id"],
            r["window_days"],
        )
        last = float(stats["last"]) if stats["last"] is not None else None
        threshold = float(r["threshold"])
        msg = None
        if r["condition"] == "below" and last is not None and last < threshold:
            msg = f"{r['metric_name']} is {last:g}{r['unit']} (below {threshold:g})"
        elif r["condition"] == "above" and last is not None and last > threshold:
            msg = f"{r['metric_name']} is {last:g}{r['unit']} (above {threshold:g})"
        elif r["condition"] == "drop_pct" and float(stats["prev"]) > 0:
            drop = (float(stats["prev"]) - float(stats["cur"])) / float(stats["prev"]) * 100
            if drop >= threshold:
                msg = (
                    f"{r['metric_name']} dropped {drop:.0f}% over the last "
                    f"{r['window_days']}d ({float(stats['prev']):g} → {float(stats['cur']):g})"
                )
        elif r["condition"] == "stale_days":
            age = (
                await pool.fetchval(
                    "SELECT extract(epoch FROM now() - $1::timestamptz) / 86400", stats["last_ts"]
                )
                if stats["last_ts"]
                else None
            )
            if age is None or age > threshold:
                msg = f"{r['metric_name']} has no new data for {age or '∞'} days"
        if msg:
            text = f":rotating_light: {r['project_name']}: {msg}"
            fired.append({"project_id": str(r["project_id"]), "text": text})
            await pool.execute(
                "UPDATE alert_rules SET last_fired_at = now() WHERE id = $1", r["id"]
            )
            await pool.execute(
                """
                INSERT INTO recommendations (project_id, title, body, kind, impact, effort)
                VALUES ($1, $2, $3, 'alert', 'high', 'low')
                """,
                r["project_id"],
                f"Alert: {msg}"[:200],
                f"Rule `{r['condition']} {threshold:g}` on {r['metric_name']} fired.",
            )
            with contextlib.suppress(Exception):
                await slack.post(text)
    return fired
