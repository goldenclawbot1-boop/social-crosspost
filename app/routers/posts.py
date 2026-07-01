from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from app.database import get_db
from app.auth import require_user, get_current_user
from app.templates import templates
from app.adapters import PLATFORM_INFO
from app.services.publisher import publish_post
import json

router = APIRouter(prefix="/posts", tags=["posts"])


@router.get("", response_class=HTMLResponse)
async def posts_page(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    with get_db() as db:
        posts = db.execute(
            "SELECT * FROM posts WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (user["id"],),
        ).fetchall()

        # Enrich with platform statuses
        enriched = []
        for post in posts:
            p = dict(post)
            pps = db.execute(
                "SELECT * FROM post_platforms WHERE post_id = ?",
                (post["id"],),
            ).fetchall()
            p["platform_statuses"] = [dict(pp) for pp in pps]
            enriched.append(p)

    return templates.TemplateResponse("posts.html", {
        "request": request,
        "user": user,
        "posts": enriched,
    })


@router.get("/{post_id}", response_class=HTMLResponse)
async def post_detail(post_id: int, request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    with get_db() as db:
        post = db.execute(
            "SELECT * FROM posts WHERE id = ? AND user_id = ?",
            (post_id, user["id"]),
        ).fetchone()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")

        media_files = db.execute(
            "SELECT * FROM media WHERE post_id = ? ORDER BY sort_order",
            (post_id,),
        ).fetchall()

        platform_statuses = db.execute(
            "SELECT * FROM post_platforms WHERE post_id = ?",
            (post_id,),
        ).fetchall()

    return templates.TemplateResponse("post_detail.html", {
        "request": request,
        "user": user,
        "post": dict(post),
        "media_files": [dict(m) for m in media_files],
        "platform_statuses": [dict(ps) for ps in platform_statuses],
    })


@router.post("")
async def create_post(
    request: Request,
    user: dict = Depends(require_user),
):
    form = await request.form()
    content = form.get("content", "").strip()
    link_url = form.get("link_url", "").strip()
    platforms_str = form.get("platforms", "[]")
    scheduled_at = form.get("scheduled_at", "").strip() or None

    try:
        platforms = json.loads(platforms_str)
    except json.JSONDecodeError:
        platforms = []

    if not content and not platforms:
        return JSONResponse({"error": "Content is required"}, status_code=400)

    status = "scheduled" if scheduled_at else "draft"

    with get_db() as db:
        db.execute(
            "INSERT INTO posts (user_id, content, link_url, status, scheduled_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], content, link_url, status, scheduled_at),
        )
        post_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Create post_platforms entries
        for platform in platforms:
            # Get user's connected accounts for this platform
            accounts = db.execute(
                "SELECT id FROM platform_accounts WHERE user_id = ? AND platform = ? AND is_active = 1",
                (user["id"], platform),
            ).fetchall()
            for acc in accounts:
                db.execute(
                    "INSERT INTO post_platforms (post_id, platform, platform_account_id, status) VALUES (?, ?, ?, ?)",
                    (post_id, platform, acc["id"], "pending"),
                )

        db.execute(
            "INSERT INTO audit_log (user_id, action, entity_type, entity_id) VALUES (?, ?, ?, ?)",
            (user["id"], "post_created", "post", post_id),
        )

    return JSONResponse({"success": True, "post_id": post_id})


@router.put("/{post_id}")
async def update_post(
    post_id: int,
    request: Request,
    user: dict = Depends(require_user),
):
    form = await request.form()
    content = form.get("content", "").strip()
    link_url = form.get("link_url", "").strip()
    platforms_str = form.get("platforms", "[]")
    scheduled_at = form.get("scheduled_at", "").strip() or None

    try:
        platforms = json.loads(platforms_str)
    except json.JSONDecodeError:
        platforms = []

    with get_db() as db:
        post = db.execute(
            "SELECT * FROM posts WHERE id = ? AND user_id = ?",
            (post_id, user["id"]),
        ).fetchone()
        if not post:
            return JSONResponse({"error": "Post not found"}, status_code=404)

        status = "scheduled" if scheduled_at else post["status"]
        if status == "scheduled" and not scheduled_at:
            status = "draft"

        db.execute(
            "UPDATE posts SET content = ?, link_url = ?, status = ?, scheduled_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (content, link_url, status, scheduled_at, post_id),
        )

        # Update platforms if post is still draft
        if post["status"] in ("draft", "scheduled"):
            db.execute("DELETE FROM post_platforms WHERE post_id = ?", (post_id,))
            for platform in platforms:
                accounts = db.execute(
                    "SELECT id FROM platform_accounts WHERE user_id = ? AND platform = ? AND is_active = 1",
                    (user["id"], platform),
                ).fetchall()
                for acc in accounts:
                    db.execute(
                        "INSERT INTO post_platforms (post_id, platform, platform_account_id, status) VALUES (?, ?, ?, ?)",
                        (post_id, platform, acc["id"], "pending"),
                    )

    return JSONResponse({"success": True, "post_id": post_id})


@router.post("/{post_id}/publish")
async def publish(post_id: int, user: dict = Depends(require_user)):
    """Publish a post to all selected platforms."""
    with get_db() as db:
        post = db.execute(
            "SELECT * FROM posts WHERE id = ? AND user_id = ?",
            (post_id, user["id"]),
        ).fetchone()
        if not post:
            return JSONResponse({"error": "Post not found"}, status_code=404)

        media_files = db.execute(
            "SELECT * FROM media WHERE post_id = ? ORDER BY sort_order",
            (post_id,),
        ).fetchall()

        platform_entries = db.execute(
            "SELECT pp.*, pa.access_token, pa.metadata as account_metadata, pa.account_id as pa_account_id, pa.account_name "
            "FROM post_platforms pp "
            "LEFT JOIN platform_accounts pa ON pp.platform_account_id = pa.id "
            "WHERE pp.post_id = ?",
            (post_id,),
        ).fetchall()

    if not platform_entries:
        return JSONResponse({"error": "No platforms selected"}, status_code=400)

    # Publish to all platforms
    results = await publish_post(
        dict(post),
        [dict(m) for m in media_files],
        [dict(pe) for pe in platform_entries],
    )

    # Update statuses
    with get_db() as db:
        all_published = True
        any_published = False
        for result in results:
            db.execute(
                "UPDATE post_platforms SET status = ?, platform_post_id = ?, platform_post_url = ?, "
                "error_message = ?, published_at = CURRENT_TIMESTAMP, retry_count = retry_count + 1 "
                "WHERE post_id = ? AND platform = ?",
                (
                    "published" if result["success"] else "failed",
                    result.get("platform_post_id", ""),
                    result.get("platform_post_url", ""),
                    result.get("error", ""),
                    post_id,
                    result["platform"],
                ),
            )
            if result["success"]:
                any_published = True
            else:
                all_published = False

        # Update post status
        new_status = "published" if all_published else ("partial" if any_published else "failed")
        db.execute(
            "UPDATE posts SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_status, post_id),
        )

        db.execute(
            "INSERT INTO audit_log (user_id, action, entity_type, entity_id, new_value) VALUES (?, ?, ?, ?, ?)",
            (user["id"], "post_published", "post", post_id, json.dumps({"status": new_status, "results": results})),
        )

    return JSONResponse({"success": any_published, "results": results})


@router.delete("/{post_id}")
async def delete_post(post_id: int, user: dict = Depends(require_user)):
    with get_db() as db:
        post = db.execute("SELECT * FROM posts WHERE id = ? AND user_id = ?", (post_id, user["id"])).fetchone()
        if not post:
            return JSONResponse({"error": "Post not found"}, status_code=404)
        db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        db.execute(
            "INSERT INTO audit_log (user_id, action, entity_type, entity_id) VALUES (?, ?, ?, ?)",
            (user["id"], "post_deleted", "post", post_id),
        )
    return JSONResponse({"success": True})
