from fastapi import APIRouter, Depends, Request, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from app.database import get_db
from app.auth import require_user
from app.config import settings
import os
import uuid
from PIL import Image
import io

router = APIRouter(prefix="/media", tags=["media"])


ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".avi", ".mkv"}
MAX_FILE_SIZE = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@router.post("/upload")
async def upload_media(
    request: Request,
    files: list[UploadFile] = File(...),
    user: dict = Depends(require_user),
):
    """Upload media files. Returns HTML for HTMX swap."""
    uploaded = []
    errors = []

    upload_dir = os.path.join(settings.UPLOAD_DIR, str(user["id"]))
    os.makedirs(upload_dir, exist_ok=True)

    for file in files:
        # Validate extension
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(f"{file.filename}: Unsupported file type")
            continue

        # Validate size
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            errors.append(f"{file.filename}: File too large (max {settings.MAX_UPLOAD_SIZE_MB}MB)")
            continue

        # Save file
        file_id = uuid.uuid4().hex[:12]
        filename = f"{file_id}{ext}"
        filepath = os.path.join(upload_dir, filename)

        with open(filepath, "wb") as f:
            f.write(content)

        # Determine type and get dimensions
        file_type = "image" if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"} else "video"
        width, height = 0, 0

        if file_type == "image":
            try:
                img = Image.open(io.BytesIO(content))
                width, height = img.size
            except Exception:
                pass

        # Create thumbnail for images
        thumbnail_path = None
        if file_type == "image":
            try:
                img = Image.open(io.BytesIO(content))
                img.thumbnail((300, 300))
                thumb_path = os.path.join(upload_dir, f"{file_id}_thumb.jpg")
                img.convert("RGB").save(thumb_path, "JPEG", quality=80)
                thumbnail_path = thumb_path
            except Exception:
                pass

        uploaded.append({
            "id": file_id,
            "filename": filename,
            "filepath": filepath,
            "file_type": file_type,
            "mime_type": file.content_type or "",
            "file_size": len(content),
            "width": width,
            "height": height,
            "thumbnail_path": thumbnail_path,
        })

    # Return HTML for HTMX
    html_parts = []
    for u in uploaded:
        preview_url = f"/media/preview/{u['id']}"
        html_parts.append(f'''
        <div class="relative w-24 h-24 bg-gray-100 rounded-lg overflow-hidden group">
            <img src="{preview_url}" class="w-full h-full object-cover" data-media-id="{u['id']}">
            <button
                class="absolute top-1 right-1 bg-red-500 text-white rounded-full w-5 h-5 text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition"
                onclick="this.parentElement.remove()"
            >&times;</button>
        </div>
        ''')

    for err in errors:
        html_parts.append(f'<div class="text-xs text-red-500">{err}</div>')

    return "".join(html_parts)


@router.get("/preview/{media_id}")
async def preview_media(media_id: str):
    """Serve a media file preview. Looks up by media_id in the uploads directory."""
    # Search for the file
    upload_dir = settings.UPLOAD_DIR
    for root, dirs, files in os.walk(upload_dir):
        for f in files:
            if f.startswith(media_id) and not f.endswith("_thumb.jpg"):
                return FileResponse(os.path.join(root, f))
    raise HTTPException(status_code=404, detail="Media not found")


@router.get("/{media_id}/preview")
async def media_preview_by_db_id(media_id: int):
    """Serve media by database media ID."""
    with get_db() as db:
        media = db.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        if not media:
            raise HTTPException(status_code=404, detail="Media not found")
        file_path = media["file_path"]
        if os.path.exists(file_path):
            return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="File not found")


@router.delete("/{media_id}")
async def delete_media(media_id: int, user: dict = Depends(require_user)):
    with get_db() as db:
        media = db.execute(
            "SELECT m.* FROM media m JOIN posts p ON m.post_id = p.id WHERE m.id = ? AND p.user_id = ?",
            (media_id, user["id"]),
        ).fetchone()
        if not media:
            return JSONResponse({"error": "Media not found"}, status_code=404)

        # Delete file
        if os.path.exists(media["file_path"]):
            os.remove(media["file_path"])
        if media["thumbnail_path"] and os.path.exists(media["thumbnail_path"]):
            os.remove(media["thumbnail_path"])

        db.execute("DELETE FROM media WHERE id = ?", (media_id,))

    return JSONResponse({"success": True})
