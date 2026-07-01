from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from contextlib import asynccontextmanager
import os

from app.database import init_db, get_db
from app.auth import get_current_user
from app.templates import templates
from app.adapters import PLATFORM_INFO
from app.routers import auth, platforms, posts, media, schedules


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    os.makedirs("uploads", exist_ok=True)
    yield
    # Shutdown


app = FastAPI(
    title="Social CrossPost",
    description="Publish to multiple social media platforms from one dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(auth.router)
app.include_router(platforms.router)
app.include_router(posts.router)
app.include_router(media.router)
app.include_router(schedules.router)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    with get_db() as db:
        # Stats
        total_posts = db.execute(
            "SELECT COUNT(*) FROM posts WHERE user_id = ?", (user["id"],)
        ).fetchone()[0]
        published = db.execute(
            "SELECT COUNT(*) FROM posts WHERE user_id = ? AND status = 'published'", (user["id"],)
        ).fetchone()[0]
        scheduled = db.execute(
            "SELECT COUNT(*) FROM posts WHERE user_id = ? AND status = 'scheduled'", (user["id"],)
        ).fetchone()[0]
        platforms_count = db.execute(
            "SELECT COUNT(DISTINCT platform) FROM platform_accounts WHERE user_id = ? AND is_active = 1",
            (user["id"],),
        ).fetchone()[0]

        # Recent posts
        recent_posts = db.execute(
            "SELECT * FROM posts WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
            (user["id"],),
        ).fetchall()

        # Connected platforms
        accounts = db.execute(
            "SELECT platform FROM platform_accounts WHERE user_id = ? AND is_active = 1 GROUP BY platform",
            (user["id"],),
        ).fetchall()

    connected_platforms = {}
    for acc in accounts:
        connected_platforms[acc["platform"]] = []

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "stats": {
            "total_posts": total_posts,
            "published": published,
            "scheduled": scheduled,
            "platforms": platforms_count,
        },
        "recent_posts": [dict(p) for p in recent_posts],
        "connected_platforms": connected_platforms,
        "platform_info": PLATFORM_INFO,
    })


@app.get("/compose", response_class=HTMLResponse)
@app.get("/compose/{post_id}", response_class=HTMLResponse)
async def compose_page(request: Request, post_id: int = None):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    post = None
    media_files = []
    if post_id:
        with get_db() as db:
            post = db.execute(
                "SELECT * FROM posts WHERE id = ? AND user_id = ?",
                (post_id, user["id"]),
            ).fetchone()
            if post:
                post = dict(post)
                media_files = db.execute(
                    "SELECT * FROM media WHERE post_id = ? ORDER BY sort_order",
                    (post_id,),
                ).fetchall()

    # Get connected platforms
    with get_db() as db:
        accounts = db.execute(
            "SELECT platform FROM platform_accounts WHERE user_id = ? AND is_active = 1 GROUP BY platform",
            (user["id"],),
        ).fetchall()

    connected_platforms = {}
    for acc in accounts:
        connected_platforms[acc["platform"]] = []

    return templates.TemplateResponse("compose.html", {
        "request": request,
        "user": user,
        "post": post,
        "media_files": [dict(m) for m in media_files],
        "connected_platforms": connected_platforms,
        "platform_info": PLATFORM_INFO,
    })
