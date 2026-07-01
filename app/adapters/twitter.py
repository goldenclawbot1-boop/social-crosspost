from typing import Optional
from fastapi import Request
from app.adapters import BasePlatformAdapter, PublishResult
from app.config import settings
import httpx
import secrets
import hashlib
import base64
import urllib.parse


class TwitterAdapter(BasePlatformAdapter):
    platform_name = "twitter"

    # OAuth 2.0 PKCE
    async def get_auth_url(self, request: Request, user_id: int) -> Optional[str]:
        if not settings.TWITTER_CLIENT_ID:
            raise ValueError("Twitter client ID not configured")

        # Generate PKCE code verifier and challenge
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()

        state = secrets.token_urlsafe(32)

        # Store in session (we'll use a simple approach — pass state with user_id encoded)
        state_data = f"{user_id}:{code_verifier}:{state}"
        # In production, store in DB/Redis. For now, encode in state param.
        # The callback will receive state back.

        params = {
            "response_type": "code",
            "client_id": settings.TWITTER_CLIENT_ID,
            "redirect_uri": f"{settings.BASE_URL}/platforms/twitter/callback",
            "scope": "tweet.read tweet.write users.read offline.access media.write",
            "state": state_data,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"https://twitter.com/i/oauth2/authorize?{urllib.parse.urlencode(params)}"

    async def handle_callback(self, request: Request, user_id: int) -> dict:
        code = request.query_params.get("code")
        state = request.query_params.get("state", "")

        if not code:
            raise ValueError("No authorization code received")

        # Extract code_verifier from state
        parts = state.split(":")
        if len(parts) >= 2:
            code_verifier = parts[1]
        else:
            raise ValueError("Invalid state parameter")

        # Exchange code for token
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.twitter.com/2/oauth2/token",
                data={
                    "code": code,
                    "grant_type": "authorization_code",
                    "client_id": settings.TWITTER_CLIENT_ID,
                    "redirect_uri": f"{settings.BASE_URL}/platforms/twitter/callback",
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code != 200:
                raise ValueError(f"Token exchange failed: {resp.text}")

            token_data = resp.json()

        # Get user info
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.twitter.com/2/users/me",
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
            if resp.status_code != 200:
                raise ValueError(f"Failed to get user info: {resp.text}")
            user_data = resp.json()["data"]

        return {
            "account_name": f"@{user_data['username']}",
            "account_id": user_data["id"],
            "access_token": token_data.get("access_token"),
            "refresh_token": token_data.get("refresh_token"),
            "scopes": token_data.get("scope", "").split(),
            "metadata": {
                "name": user_data.get("name", ""),
                "username": user_data.get("username", ""),
            },
        }

    async def validate_credentials(self, account: dict) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.twitter.com/2/users/me",
                    headers={"Authorization": f"Bearer {account['access_token']}"},
                    timeout=10,
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def publish(self, account: dict, content: str, media_files: list[dict], link_url: str = "") -> PublishResult:
        """Publish a tweet with optional media."""
        async with httpx.AsyncClient(timeout=60) as client:
            headers = {"Authorization": f"Bearer {account['access_token']}"}
            try:
                media_ids = []

                # Upload media first
                for media in media_files:
                    file_path = media.get("file_path", "")
                    media_type = media.get("file_type", "image")

                    with open(file_path, "rb") as f:
                        if media_type == "video":
                            # Video upload is multipart/chunked — simplified here
                            upload_resp = await client.post(
                                "https://upload.twitter.com/1.1/media/upload.json",
                                params={"media_category": "tweet_video"},
                                files={"media": f},
                                headers=headers,
                            )
                        else:
                            upload_resp = await client.post(
                                "https://upload.twitter.com/1.1/media/upload.json",
                                files={"media": f},
                                headers=headers,
                            )

                    if upload_resp.status_code == 200:
                        media_ids.append(upload_resp.json()["media_id_string"])
                    else:
                        return PublishResult(success=False, error=f"Media upload failed: {upload_resp.text}")

                # Create tweet
                tweet_data = {"text": content[:280]}
                if media_ids:
                    tweet_data["media"] = {"media_ids": media_ids}

                resp = await client.post(
                    "https://api.twitter.com/2/tweets",
                    json=tweet_data,
                    headers={**headers, "Content-Type": "application/json"},
                )

                if resp.status_code in (200, 201):
                    data = resp.json()["data"]
                    tweet_id = data["id"]
                    username = account.get("account_name", "").lstrip("@")
                    return PublishResult(
                        success=True,
                        platform_post_id=tweet_id,
                        platform_post_url=f"https://twitter.com/{username}/status/{tweet_id}" if username else "",
                    )
                else:
                    return PublishResult(success=False, error=resp.text)

            except Exception as e:
                return PublishResult(success=False, error=str(e))

    def max_caption_length(self) -> int:
        return 280
