import asyncio
import json
from app.database import get_db
from app.adapters import get_adapter


async def publish_post(post: dict, media_files: list[dict], platform_entries: list[dict]) -> list[dict]:
    """
    Publish a post to all selected platforms in parallel.
    Returns list of {platform, success, platform_post_id, platform_post_url, error}.
    """
    async def publish_to_platform(entry: dict) -> dict:
        platform = entry["platform"]
        adapter = get_adapter(platform)

        if adapter is None:
            return {
                "platform": platform,
                "success": False,
                "error": f"No adapter for {platform}",
            }

        # Build account dict
        account = {
            "access_token": entry.get("access_token", ""),
            "account_id": entry.get("pa_account_id", entry.get("account_id", "")),
            "account_name": entry.get("account_name", ""),
            "metadata": entry.get("account_metadata", "{}"),
        }

        # Filter media by platform support
        platform_media = [
            m for m in media_files
            if adapter.supports_media_type(m.get("file_type", "image"))
        ][:adapter.max_media_count()]

        # Truncate content
        content = (post.get("content") or "")[:adapter.max_caption_length()]
        link_url = post.get("link_url") or ""

        try:
            result = await adapter.publish(account, content, platform_media, link_url)
            return {
                "platform": platform,
                "success": result.success,
                "platform_post_id": result.platform_post_id,
                "platform_post_url": result.platform_post_url,
                "error": result.error,
            }
        except Exception as e:
            return {
                "platform": platform,
                "success": False,
                "error": str(e),
            }

    # Publish to all platforms in parallel
    tasks = [publish_to_platform(entry) for entry in platform_entries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle exceptions
    final_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            final_results.append({
                "platform": platform_entries[i]["platform"],
                "success": False,
                "error": str(result),
            })
        else:
            final_results.append(result)

    return final_results
