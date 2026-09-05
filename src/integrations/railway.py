"""Railway GraphQL → Ops panel: services and their latest deployment status."""

from __future__ import annotations

import httpx

from src.config import settings

API = "https://backboard.railway.com/graphql/v2"

_QUERY = """
query($id: String!) {
  project(id: $id) {
    name
    services { edges { node {
      id name
      deployments(first: 1) { edges { node { id status createdAt updatedAt staticUrl } } }
    } } }
  }
}
"""


async def fetch_project(project_id: str, token: str | None) -> dict:
    token = token or settings.railway_api_token
    if not token:
        raise RuntimeError("No Railway token configured (integration secret or RAILWAY_API_TOKEN)")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            API,
            headers={"Authorization": f"Bearer {token}"},
            json={"query": _QUERY, "variables": {"id": project_id}},
        )
        r.raise_for_status()
        body = r.json()
    if body.get("errors"):
        raise RuntimeError(body["errors"][0].get("message", "Railway API error"))
    project = body["data"]["project"]
    services = []
    for edge in project["services"]["edges"]:
        node = edge["node"]
        deps = node["deployments"]["edges"]
        latest = deps[0]["node"] if deps else None
        services.append(
            {
                "id": node["id"],
                "name": node["name"],
                "status": latest["status"] if latest else "NONE",
                "deployed_at": latest["updatedAt"] if latest else None,
                "url": f"https://{latest['staticUrl']}" if latest and latest["staticUrl"] else None,
            }
        )
    return {"name": project["name"], "services": services}


async def verify(project_id: str, token: str | None) -> str:
    data = await fetch_project(project_id, token)
    return f"Connected to {data['name']} ({len(data['services'])} services)"
