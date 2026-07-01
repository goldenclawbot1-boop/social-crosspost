from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from app.database import get_db
from app.auth import require_user, get_current_user
from app.templates import templates
from app.adapters import PLATFORM_INFO
import json

router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.get("", response_class=HTMLResponse)
async def schedules_page(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    with get_db() as db:
        schedules = db.execute(
            "SELECT * FROM schedules WHERE user_id = ? ORDER BY created_at DESC",
            (user["id"],),
        ).fetchall()

        # Get connected platforms for the form
        accounts = db.execute(
            "SELECT platform FROM platform_accounts WHERE user_id = ? AND is_active = 1 GROUP BY platform",
            (user["id"],),
        ).fetchall()

    connected_platforms = {}
    for acc in accounts:
        connected_platforms[acc["platform"]] = []

    return templates.TemplateResponse("schedules.html", {
        "request": request,
        "user": user,
        "schedules": [dict(s) for s in schedules],
        "connected_platforms": connected_platforms,
        "platform_info": PLATFORM_INFO,
    })


@router.post("")
async def create_schedule(
    request: Request,
    user: dict = Depends(require_user),
):
    form = await request.form()
    name = form.get("name", "").strip()
    cron_expression = form.get("cron_expression", "").strip()
    content_template = form.get("content_template", "").strip()
    platforms = form.getlist("platforms")

    if not name or not cron_expression:
        return JSONResponse({"error": "Name and cron expression are required"}, status_code=400)

    with get_db() as db:
        db.execute(
            "INSERT INTO schedules (user_id, name, cron_expression, content_template, platforms) VALUES (?, ?, ?, ?, ?)",
            (user["id"], name, cron_expression, content_template, json.dumps(platforms)),
        )
        schedule_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    return JSONResponse({"success": True, "schedule_id": schedule_id})


@router.post("/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: int, user: dict = Depends(require_user)):
    with get_db() as db:
        schedule = db.execute(
            "SELECT * FROM schedules WHERE id = ? AND user_id = ?",
            (schedule_id, user["id"]),
        ).fetchone()
        if not schedule:
            return JSONResponse({"error": "Schedule not found"}, status_code=404)

        new_active = not schedule["is_active"]
        db.execute("UPDATE schedules SET is_active = ? WHERE id = ?", (new_active, schedule_id))

    return JSONResponse({"success": True, "is_active": new_active})


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: int, user: dict = Depends(require_user)):
    with get_db() as db:
        db.execute("DELETE FROM schedules WHERE id = ? AND user_id = ?", (schedule_id, user["id"]))
    return JSONResponse({"success": True})
