from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from app.database import get_db
from app.auth import require_user, get_current_user
from app.templates import templates
from app.adapters import get_adapter, PLATFORM_INFO
import json

router = APIRouter(prefix="/platforms", tags=["platforms"])


@router.get("", response_class=HTMLResponse)
async def platforms_page(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    with get_db() as db:
        accounts = db.execute(
            "SELECT * FROM platform_accounts WHERE user_id = ? ORDER BY platform, created_at DESC",
            (user["id"],),
        ).fetchall()

    # Build platform status map
    connected = {}
    for acc in accounts:
        connected[acc["platform"]] = connected.get(acc["platform"], []) + [dict(acc)]

    return templates.TemplateResponse("platforms.html", {
        "request": request,
        "user": user,
        "platforms": PLATFORM_INFO,
        "connected": connected,
    })


@router.get("/{platform}/connect")
async def connect_platform(platform: str, request: Request, user: dict = Depends(require_user)):
    """Start OAuth flow or return connection instructions."""
    adapter = get_adapter(platform)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {platform}")

    auth_url = await adapter.get_auth_url(request, user["id"])
    if auth_url:
        return RedirectResponse(url=auth_url, status_code=302)

    # For platforms without OAuth (Telegram), show manual connect form
    return templates.TemplateResponse("platform_connect.html", {
        "request": request,
        "user": user,
        "platform": platform,
        "info": PLATFORM_INFO.get(platform, {}),
    })


@router.get("/{platform}/callback")
async def oauth_callback(platform: str, request: Request):
    """Handle OAuth callback."""
    adapter = get_adapter(platform)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {platform}")

    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    try:
        account_data = await adapter.handle_callback(request, user["id"])
        with get_db() as db:
            db.execute(
                """INSERT OR REPLACE INTO platform_accounts 
                   (user_id, platform, account_name, account_id, access_token, refresh_token, 
                    token_expires_at, scopes, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user["id"], platform,
                    account_data.get("account_name"),
                    account_data.get("account_id"),
                    account_data.get("access_token"),
                    account_data.get("refresh_token"),
                    account_data.get("token_expires_at"),
                    json.dumps(account_data.get("scopes", [])),
                    json.dumps(account_data.get("metadata", {})),
                ),
            )
            db.execute(
                "INSERT INTO audit_log (user_id, action, entity_type, entity_id) VALUES (?, ?, ?, ?)",
                (user["id"], f"platform_connected", "platform_account", platform),
            )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    return RedirectResponse(url="/platforms?connected=" + platform, status_code=302)


@router.post("/{platform}/connect-manual")
async def connect_manual(
    platform: str,
    request: Request,
    user: dict = Depends(require_user),
):
    """Manual connection for platforms like Telegram (bot token)."""
    adapter = get_adapter(platform)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {platform}")

    form = await request.form()
    try:
        account_data = await adapter.handle_manual_connect(form, user["id"])
        with get_db() as db:
            db.execute(
                """INSERT OR REPLACE INTO platform_accounts 
                   (user_id, platform, account_name, account_id, access_token, metadata)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    user["id"], platform,
                    account_data.get("account_name"),
                    account_data.get("account_id"),
                    account_data.get("access_token"),
                    json.dumps(account_data.get("metadata", {})),
                ),
            )
            db.execute(
                "INSERT INTO audit_log (user_id, action, entity_type, entity_id) VALUES (?, ?, ?, ?)",
                (user["id"], f"platform_connected", "platform_account", platform),
            )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    return JSONResponse({"success": True, "redirect": "/platforms"})


@router.delete("/{platform}/{account_id}")
async def disconnect_platform(platform: str, account_id: int, user: dict = Depends(require_user)):
    with get_db() as db:
        db.execute(
            "DELETE FROM platform_accounts WHERE id = ? AND user_id = ? AND platform = ?",
            (account_id, user["id"], platform),
        )
        db.execute(
            "INSERT INTO audit_log (user_id, action, entity_type, entity_id) VALUES (?, ?, ?, ?)",
            (user["id"], f"platform_disconnected", "platform_account", account_id),
        )
    return JSONResponse({"success": True})
