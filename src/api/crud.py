"""Generic project-scoped CRUD router factory for simple v2 tables."""

from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.api.projects import require_project
from src.db import get_pool


def _serialize(row) -> dict:
    return dict(row)


async def fetch_one(table: str, row_id: UUID) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow(f"SELECT * FROM {table} WHERE id = $1", row_id)  # noqa: S608
    if row is None:
        raise HTTPException(status_code=404, detail=f"{table[:-1].replace('_', ' ')} not found")
    return dict(row)


async def insert_row(table: str, values: dict[str, Any]) -> dict:
    values = {k: v for k, v in values.items() if v is not None}  # let column defaults apply
    cols = list(values)
    placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
    pool = await get_pool()
    try:
        row = await pool.fetchrow(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) RETURNING *",  # noqa: S608
            *values.values(),
        )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(status_code=409, detail="Already exists") from exc
    except asyncpg.ForeignKeyViolationError as exc:
        raise HTTPException(status_code=400, detail="Referenced record not found") from exc
    return dict(row)


async def update_row(table: str, row_id: UUID, values: dict[str, Any], touch: bool) -> dict:
    if not values:
        return await fetch_one(table, row_id)
    sets = [f"{c} = ${i + 2}" for i, c in enumerate(values)]
    if touch:
        sets.append("updated_at = now()")
    pool = await get_pool()
    row = await pool.fetchrow(
        f"UPDATE {table} SET {', '.join(sets)} WHERE id = $1 RETURNING *",  # noqa: S608
        row_id,
        *values.values(),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return dict(row)


def make_router(
    table: str,
    create_model: type[BaseModel],
    update_model: type[BaseModel],
    out_model: type[BaseModel],
    *,
    order_by: str = "created_at DESC",
    filters: tuple[str, ...] = ("status",),
    has_updated_at: bool = True,
    limit: int = 500,
) -> APIRouter:
    router = APIRouter()

    @router.get("", response_model=list[out_model])
    async def list_rows(  # noqa: PLR0913
        project_id: UUID | None = Query(default=None),
        status: str | None = Query(default=None),
        channel: str | None = Query(default=None),
        platform: str | None = Query(default=None),
        category: str | None = Query(default=None),
        source: str | None = Query(default=None),
    ):
        provided = {
            "status": status,
            "channel": channel,
            "platform": platform,
            "category": category,
            "source": source,
        }
        where = ["($1::uuid IS NULL OR project_id = $1)"]
        args: list[Any] = [project_id]
        for col in filters:
            if provided.get(col) is not None:
                args.append(provided[col])
                where.append(f"{col} = ${len(args)}")
        pool = await get_pool()
        rows = await pool.fetch(
            f"SELECT * FROM {table} WHERE {' AND '.join(where)} "  # noqa: S608
            f"ORDER BY {order_by} LIMIT {limit}",
            *args,
        )
        return [out_model(**_serialize(r)) for r in rows]

    @router.post("/projects/{project_id}", response_model=out_model, status_code=201)
    async def create_row(project_id: UUID, body: create_model):  # type: ignore[valid-type]
        await require_project(project_id)
        values = {"project_id": project_id, **body.model_dump()}
        return out_model(**await insert_row(table, values))

    @router.get("/{row_id}", response_model=out_model)
    async def get_row(row_id: UUID):
        return out_model(**await fetch_one(table, row_id))

    @router.patch("/{row_id}", response_model=out_model)
    async def patch_row(row_id: UUID, body: update_model):  # type: ignore[valid-type]
        values = body.model_dump(exclude_unset=True)
        return out_model(**await update_row(table, row_id, values, has_updated_at))

    @router.delete("/{row_id}", status_code=204)
    async def delete_row(row_id: UUID):
        pool = await get_pool()
        res = await pool.execute(f"DELETE FROM {table} WHERE id = $1", row_id)  # noqa: S608
        if res.endswith("0"):
            raise HTTPException(status_code=404, detail="Not found")

    return router
