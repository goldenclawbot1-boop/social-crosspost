from typing import Optional
from fastapi import Request
from app.adapters import BasePlatformAdapter, PublishResult
from app.config import settings
import httpx
import urllib.parse


class InstagramAdapter(BasePlatformAdapter):
    platform_name = "instagram"

    async def get_auth_url(self, request: Request, user_id: int) -> Optional[str]:
        if not settings.META_APP_ID:
            raise ValueError("Meta App ID not configured")

        params = {
            "client_id": settings.META_APP_ID,
            "redirect_uri": f"{settings.BASE_URL}/platforms/instagram/callback",
            "scope": "pages_show_list,instagram_basic,instagram_content_publish,pages_read_engagement",
            "response_type": "code",
            "state": str(user_id),
        }
        return f"https://www.facebook.com/v19.0/dialog/oauth?{urllib.parse.urlencode(params)}"

    async def handle_callback(self, request: Request, user_id: int) -> dict:
        code = request.query_params.get("code")
        if not code:
            raise ValueError("No authorization code received")

        # Exchange code for user token
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://graph.facebook.com/v19.0/oauth/access_token",
                params={
                    "client_id": settings.META_APP_ID,
                    "client_secret": settings.META_APP_SECRET,
                    "redirect_uri": f"{settings.BASE_URL}/platforms/instagram/callback",
                    "code": code,
                },
            )
            if resp.status_code != 200:
                raise ValueError(f"Token exchange failed: {resp.text}")
            token_data = resp.json()

        user_token = token_data["access_token"]

        # Get pages → Instagram Business accounts
        async with httpx.AsyncClient() as client:
            # Get pages
            resp = await client.get(
                "https://graph.facebook.com/v19.0/me/accounts",
                params={"access_token": user_token},
            )
            pages = resp.json().get("data", [])

            ig_account = None
            page_token = None
            page_name = None

            for page in pages:
                # Get Instagram account for each page
                ig_resp = await client.get(
                    f"https://graph.facebook.com/v19.0/{page['id']}",
                    params={
                        "access_token": page["access_token"],
                        "fields": "instagram_business_account{id,username,name}",
                    },
                )
                ig_data = ig_resp.json()
                ig_biz = ig_data.get("instagram_business_account")
                if ig_biz:
                    ig_account = ig_biz
                    page_token = page["access_token"]
                    page_name = page["name"]
                    break

            if not ig_account:
                raise ValueError("No Instagram Business account found. Connect an Instagram account to your Facebook Page.")

        return {
            "account_name": f"@{ig_account['username']}",
            "account_id": ig_account["id"],
            "access_token": page_token,  # Page token for IG API
            "refresh_token": user_token,
            "scopes": ["instagram_basic", "instagram_content_publish"],
            "metadata": {
                "ig_account_id": ig_account["id"],
                "ig_username": ig_account["username"],
                "ig_name": ig_account.get("name", ""),
                "page_name": page_name,
            },
        }

    async def validate_credentials(self, account: dict) -> bool:
        try:
            import json
            metadata = json.loads(account["metadata"]) if isinstance(account.get("metadata"), str) else account.get("metadata", {})
            ig_id = metadata.get("ig_account_id", account["account_id"])
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://graph.facebook.com/v19.0/{ig_id}",
                    params={"access_token": account["access_token"], "fields": "id,username"},
                    timeout=10,
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def publish(self, account: dict, content: str, media_files: list[dict], link_url: str = "") -> PublishResult:
        """Publish to Instagram. Supports single image, carousel (2-10 images), single video/reel."""
        import json
        metadata = json.loads(account["metadata"]) if isinstance(account.get("metadata"), str) else account.get("metadata", {})
        ig_account_id = metadata.get("ig_account_id", account["account_id"])
        page_token = account["access_token"]

        async with httpx.AsyncClient(timeout=120) as client:
            try:
                if not media_files:
                    return PublishResult(success=False, error="Instagram requires at least one image or video")

                if len(media_files) == 1:
                    # Single media
                    media = media_files[0]
                    file_path = media.get("file_path", "")
                    media_type = media.get("file_type", "image")

                    # Step 1: Create media container
                    if media_type == "video":
                        create_params = {
                            "media_type": "REELS",
                            "video_url": file_path,  # Must be a public URL
                            "caption": content[:2200],
                            "access_token": page_token,
                        }
                    else:
                        create_params = {
                            "image_url": file_path,  # Must be a public URL
                            "caption": content[:2200],
                            "access_token": page_token,
                        }

                    create_resp = await client.post(
                        f"https://graph.facebook.com/v19.0/{ig_account_id}/media",
                        data=create_params,
                    )
                    create_data = create_resp.json()

                    if "id" not in create_data:
                        return PublishResult(success=False, error=f"Container creation failed: {create_data}")

                    container_id = create_data["id"]

                    # Step 2: Publish
                    publish_resp = await client.post(
                        f"https://graph.facebook.com/v19.0/{ig_account_id}/media_publish",
                        data={
                            "creation_id": container_id,
                            "access_token": page_token,
                        },
                    )
                    publish_data = publish_resp.json()

                    if "id" in publish_data:
                        return PublishResult(
                            success=True,
                            platform_post_id=publish_data["id"],
                            platform_post_url=f"https://www.instagram.com/p/{publish_data['id']}/",
                        )
                    else:
                        return PublishResult(success=False, error=f"Publish failed: {publish_data}")

                else:
                    # Carousel (2-10 items)
                    container_ids = []
                    for media in media_files[:10]:
                        create_resp = await client.post(
                            f"https://graph.facebook.com/v19.0/{ig_account_id}/media",
                            data={
                                "image_url": media["file_path"],
                                "is_carousel_item": "true",
                                "access_token": page_token,
                            },
                        )
                        create_data = create_resp.json()
                        if "id" in create_data:
                            container_ids.append(create_data["id"])
                        else:
                            return PublishResult(success=False, error=f"Carousel item failed: {create_data}")

                    # Create carousel container
                    carousel_resp = await client.post(
                        f"https://graph.facebook.com/v19.0/{ig_account_id}/media",
                        data={
                            "media_type": "CAROUSEL",
                            "children": ",".join(container_ids),
                            "caption": content[:2200],
                            "access_token": page_token,
                        },
                    )
                    carousel_data = carousel_resp.json()

                    if "id" not in carousel_data:
                        return PublishResult(success=False, error=f"Carousel container failed: {carousel_data}")

                    # Publish carousel
                    publish_resp = await client.post(
                        f"https://graph.facebook.com/v19.0/{ig_account_id}/media_publish",
                        data={
                            "creation_id": carousel_data["id"],
                            "access_token": page_token,
                        },
                    )
                    publish_data = publish_resp.json()

                    if "id" in publish_data:
                        return PublishResult(
                            success=True,
                            platform_post_id=publish_data["id"],
                            platform_post_url=f"https://www.instagram.com/p/{publish_data['id']}/",
                        )
                    else:
                        return PublishResult(success=False, error=f"Publish failed: {publish_data}")

            except Exception as e:
                return PublishResult(success=False, error=str(e))

    def max_caption_length(self) -> int:
        return 2200
