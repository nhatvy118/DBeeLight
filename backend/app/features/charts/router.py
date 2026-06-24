"""Saved charts / project dashboard.

- POST   /api/projects/{pid}/charts          → save a chart to the project's dashboard
- GET    /api/projects/{pid}/charts          → list chart definitions
- GET    /api/projects/{pid}/dashboard/render → re-run all charts' SQL → live Vega-Lite specs
- DELETE /api/charts/{chart_id}              → remove a chart
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.features.auth.deps import get_current_user_id
from app.features.charts import service

router = APIRouter(tags=["charts"])


@router.post("/api/projects/{project_id}/charts")
async def save_chart(project_id: str, body: dict, user_id: str = Depends(get_current_user_id)):
    try:
        chart = await service.save_chart(user_id, project_id, body)
    except service.ChartError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"success": True, "chart": chart}


@router.get("/api/projects/{project_id}/charts")
async def list_charts(project_id: str, user_id: str = Depends(get_current_user_id)):
    return {"success": True, "charts": await service.list_charts(project_id, user_id)}


@router.get("/api/projects/{project_id}/dashboard/render")
async def render_dashboard(project_id: str, user_id: str = Depends(get_current_user_id)):
    try:
        charts = await service.render_dashboard(user_id, project_id)
    except service.ChartError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"success": True, "charts": charts}


@router.patch("/api/charts/{chart_id}")
async def update_chart(chart_id: str, body: dict, user_id: str = Depends(get_current_user_id)):
    try:
        await service.update_chart(user_id, chart_id, body)
    except service.ChartError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"success": True}


@router.post("/api/projects/{project_id}/dashboard/reorder")
async def reorder(project_id: str, body: dict, user_id: str = Depends(get_current_user_id)):
    await service.reorder(user_id, project_id, body.get("chart_ids") or [])
    return {"success": True}


@router.delete("/api/charts/{chart_id}")
async def delete_chart(chart_id: str, user_id: str = Depends(get_current_user_id)):
    await service.delete_chart(chart_id, user_id)
    return {"success": True}
