from typing import Optional
from fastapi import Request
from app.adapters import BasePlatformAdapter, PublishResult
from app.config import settings
import httpx
import urllib.parse


class FacebookAdapter(BasePlatformAdapter):
    platform_name = "facebook"

    async def get_auth_url(self, request: Request, user_id: int) -> Optional[str]:
        if not settings.META_APP_ID:
            raise ValueError("Meta App ID not configured")

        params = {
            "client_id": settings.META_APP_ID,
            "redirect_uri": f"{settings.BASE_URL}/platforms/facebook/callback",
            "scope": "pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_metadata",
            "response_type": "code",
            "state": str(user_id),
        }
        return f"https://www.facebook.com/v19.0/dialog/oauth?{urllib.parse.urlencode(params)}"

    async def handle_callback(self, request: Request, user_id: int) -> dict:
        code = request.query_params.get("code")
        if not code:
            raise ValueError("No authorization code received")

        # Exchange code for token
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://graph.facebook.com/v19.0/oauth/access_token",
                params={
                    "client_id": settings.META_APP_ID,
                    "client_secret": settings.META_APP_SECRET,
                    "redirect_uri": f"{settings.BASE_URL}/platforms/facebook/callback",
                    "code": code,
                },
            )
            if resp.status_code != 200:
                raise ValueError(f"Token exchange failed: {resp.text}")
            token_data = resp.json()

        # Get user's pages
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://graph.facebook.com/v19.0/me/accounts",
                params={"access_token": token_data["access_token"]},
            )
            if resp.status_code != 200:
                raise ValueError(f"Failed to get pages: {resp.text}")
            pages_data = resp.json()

        pages = pages_data.get("data", [])
        if not pages:
            raise ValueError("No Facebook Pages found. Create a Page first.")

        # Use the first page (user can select later)
        page = pages[0]

        return {
            "account_name": page["name"],
            "account_id": page["id"],
            "access_token": page["access_token"],  # Page access token
            "refresh_token": token_data.get("access_token"),  # User token for refresh
            "scopes": ["pages_show_list", "pages_manage_posts"],
            "metadata": {
                "page_name": page["name"],
                "page_id": page["id"],
                "all_pages": pages,
            },
        }

    async def validate_credentials(self, account: dict) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://graph.facebook.com/v19.0/{account['account_id']}",
                    params={"access_token": account["access_token"], "fields": "id,name"},
                    timeout=10,
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def publish(self, account: dict, content: str, media_files: list[dict], link_url: str = "") -> PublishResult:
        """Publish to a Facebook Page."""
        page_id = account["account_id"]
        page_token = account["access_token"]

        async with httpx.AsyncClient(timeout=60) as client:
            try:
                if media_files:
                    media = media_files[0]
                    file_path = media.get("file_path", "")
                    media_type = media.get("file_type", "image")

                    if media_type == "video":
                        # Upload video
                        with open(file_path, "rb") as f:
                            resp = await client.post(
                                f"https://graph.facebook.com/v19.0/{page_id}/videos",
                                data={
                                    "access_token": page_token,
                                    "description": content[:63206],
                                },
                                files={"source": f},
                            )
                    else:
                        # Upload photo
                        with open(file_path, "rb") as f:
                            resp = await client.post(
                                f"https://graph.facebook.com/v19.0/{page_id}/photos",
                                data={
                                    "access_token": page_token,
                                    "caption": content[:63206],
                                },
                                files={"source": f},
                            )
                else:
                    # Text-only post
                    resp = await client.post(
                        f"https://graph.facebook.com/v19.0/{page_id}/feed",
                        data={
                            "access_token": page_token,
                            "message": content[:63206],
                            "link": link_url or None,
                        },
                    )

                result = resp.json()
                if "id" in result:
                    post_id = result["id"]
                    return PublishResult(
                        success=True,
                        platform_post_id=post_id,
                        platform_post_url=f"https://www.facebook.com/{post_id}",
                    )
                else:
                    return PublishResult(success=False, error=result.get("error", {}).get("message", str(result)))

            except Exception as e:
                return PublishResult(success=False, error=str(e))

    def max_caption_length(self) -> int:
        return 63206
