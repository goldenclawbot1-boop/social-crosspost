from fastapi import APIRouter, HTTPException, status, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from app.database import get_db
from app.auth import hash_password, verify_password, create_access_token, create_refresh_token, get_current_user, require_user
from app.config import settings
from app.templates import templates

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = await get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    user = await get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("register.html", {"request": request})


@router.post("/register")
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(""),
):
    if len(password) < 6:
        return JSONResponse({"error": "Password must be at least 6 characters"}, status_code=400)
    if len(email) < 3 or "@" not in email:
        return JSONResponse({"error": "Invalid email"}, status_code=400)

    with get_db() as db:
        existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            return JSONResponse({"error": "Email already registered"}, status_code=400)

        db.execute(
            "INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
            (email, hash_password(password), name or email.split("@")[0]),
        )
        user_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Audit
        db.execute(
            "INSERT INTO audit_log (user_id, action, entity_type, entity_id) VALUES (?, ?, ?, ?)",
            (user_id, "user_registered", "user", user_id),
        )

    # Create tokens
    access_token = create_access_token(user_id, email)
    refresh_token = create_refresh_token(user_id)

    response = JSONResponse({"success": True, "redirect": "/"})
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
    )
    return response


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE email = ? AND is_active = 1", (email,)).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            return JSONResponse({"error": "Invalid email or password"}, status_code=401)

        access_token = create_access_token(user["id"], user["email"])
        refresh_token = create_refresh_token(user["id"])

        db.execute(
            "INSERT INTO audit_log (user_id, action, entity_type, entity_id) VALUES (?, ?, ?, ?)",
            (user["id"], "user_login", "user", user["id"]),
        )

    response = JSONResponse({"success": True, "redirect": "/"})
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie("access_token")
    return response


@router.get("/me")
async def me(user: dict = Depends(require_user)):
    return {"id": user["id"], "email": user["email"], "name": user["name"], "timezone": user["timezone"]}
