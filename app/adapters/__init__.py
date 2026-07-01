from abc import ABC, abstractmethod
from typing import Optional
from fastapi import Request
import httpx


class PublishResult:
    def __init__(self, success: bool, platform_post_id: str = "", platform_post_url: str = "", error: str = ""):
        self.success = success
        self.platform_post_id = platform_post_id
        self.platform_post_url = platform_post_url
        self.error = error


class BasePlatformAdapter(ABC):
    platform_name: str = ""

    @abstractmethod
    async def get_auth_url(self, request: Request, user_id: int) -> Optional[str]:
        """Return OAuth URL or None if manual connection."""
        ...

    @abstractmethod
    async def handle_callback(self, request: Request, user_id: int) -> dict:
        """Process OAuth callback, return account data dict."""
        ...

    async def handle_manual_connect(self, form: dict, user_id: int) -> dict:
        """Handle manual connection (e.g., bot token). Override if needed."""
        raise NotImplementedError("Manual connection not supported for this platform")

    @abstractmethod
    async def validate_credentials(self, account: dict) -> bool:
        """Check if stored credentials are still valid."""
        ...

    @abstractmethod
    async def publish(self, account: dict, content: str, media_files: list[dict], link_url: str = "") -> PublishResult:
        """Publish a post to the platform."""
        ...

    def supports_media_type(self, media_type: str) -> bool:
        return media_type in ("image", "video")

    def max_media_count(self) -> int:
        return 10

    def max_caption_length(self) -> int:
        return 5000


# Platform info for UI
PLATFORM_INFO = {
    "twitter": {
        "name": "Twitter / X",
        "icon": "𝕏",
        "color": "#1da1f2",
        "description": "Post tweets with media via X API v2",
        "auth_type": "oauth2",
        "max_caption": 280,
        "media_types": ["image", "video"],
        "max_media": 4,
    },
    "facebook": {
        "name": "Facebook",
        "icon": "📘",
        "color": "#1877f2",
        "description": "Post to Facebook Pages via Graph API",
        "auth_type": "oauth2",
        "max_caption": 63206,
        "media_types": ["image", "video"],
        "max_media": 10,
    },
    "instagram": {
        "name": "Instagram",
        "icon": "📷",
        "color": "#e4405f",
        "description": "Post to Instagram Business accounts via Graph API",
        "auth_type": "oauth2",
        "max_caption": 2200,
        "media_types": ["image", "video"],
        "max_media": 10,
    },
    "tiktok": {
        "name": "TikTok",
        "icon": "🎵",
        "color": "#000000",
        "description": "Post videos to TikTok via Content Posting API",
        "auth_type": "oauth2",
        "max_caption": 2200,
        "media_types": ["video"],
        "max_media": 1,
    },
    "linkedin": {
        "name": "LinkedIn",
        "icon": "💼",
        "color": "#0a66c2",
        "description": "Post to LinkedIn via Community Management API",
        "auth_type": "oauth2",
        "max_caption": 3000,
        "media_types": ["image", "video", "document"],
        "max_media": 9,
    },
    "youtube": {
        "name": "YouTube",
        "icon": "▶️",
        "color": "#ff0000",
        "description": "Upload videos to YouTube via Data API v3",
        "auth_type": "oauth2",
        "max_caption": 5000,
        "media_types": ["video"],
        "max_media": 1,
    },
    "pinterest": {
        "name": "Pinterest",
        "icon": "📌",
        "color": "#e60023",
        "description": "Create Pins on Pinterest via v5 API",
        "auth_type": "oauth2",
        "max_caption": 500,
        "media_types": ["image", "video"],
        "max_media": 1,
    },
}


def get_adapter(platform: str) -> Optional[BasePlatformAdapter]:
    """Factory: return the adapter for a given platform."""
    if platform == "twitter":
        from app.adapters.twitter import TwitterAdapter
        return TwitterAdapter()
    if platform == "facebook":
        from app.adapters.facebook import FacebookAdapter
        return FacebookAdapter()
    if platform == "instagram":
        from app.adapters.instagram import InstagramAdapter
        return InstagramAdapter()
    return None
