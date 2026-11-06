"""
Roblox API Helper
------------------
Lightweight async wrapper around Roblox's public, unauthenticated endpoints.

Used by the registration flow (/register) to:
  1. Confirm a typed Roblox username actually exists (catches typos).
  2. Fetch the exact-cased username + numeric UserId.
  3. Fetch a small avatar headshot thumbnail to show in embeds.

IMPORTANT: This performs NO ownership verification. Anyone can type any
existing Roblox username and link it to their Discord account. That is
intentional per project requirements - this is a "linking", not a
"claiming" system. If you ever need real ownership proof, the usual pattern
is a one-time code the user must paste into their Roblox profile bio, which
the bot then checks for - that is NOT implemented here on purpose.
"""

import aiohttp
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

USERNAME_LOOKUP_URL = "https://users.roblox.com/v1/usernames/users"
AVATAR_THUMBNAIL_URL = "https://thumbnails.roblox.com/v1/users/avatar-headshot"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=6)


class RobloxAPI:
    """Static helper methods for talking to Roblox's public REST API."""

    @staticmethod
    async def get_user_by_username(username: str) -> Optional[Dict]:
        """
        Look up a Roblox account by its username.

        Returns a dict like {'id': 123, 'name': 'ExactCasedName', 'displayName': '...'}
        if found, or None if the account doesn't exist OR the Roblox API
        could not be reached (network issue, rate limit, etc).

        Callers should treat 'None' as "couldn't verify" rather than always
        as "definitely doesn't exist", and fail open (since this project
        does not require strict verification).
        """
        payload = {"usernames": [username.strip()], "excludeBannedUsers": False}

        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                async with session.post(USERNAME_LOOKUP_URL, json=payload) as resp:
                    if resp.status != 200:
                        logger.warning(f"Roblox username lookup returned status {resp.status}")
                        return None

                    data = await resp.json()
                    results = data.get("data", [])

                    if not results:
                        return None

                    return results[0]

        except Exception as e:
            logger.warning(f"Roblox username lookup failed (network/API issue): {e}")
            return None

    @staticmethod
    async def get_avatar_headshot_url(roblox_user_id: int) -> Optional[str]:
        """
        Fetch a 150x150 PNG headshot thumbnail URL for a given Roblox UserId.
        Returns None if it can't be fetched (non-fatal - registration still succeeds).
        """
        params = {
            "userIds": str(roblox_user_id),
            "size": "150x150",
            "format": "Png",
            "isCircular": "false",
        }

        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                async with session.get(AVATAR_THUMBNAIL_URL, params=params) as resp:
                    if resp.status != 200:
                        return None

                    data = await resp.json()
                    results = data.get("data", [])

                    if not results:
                        return None

                    return results[0].get("imageUrl")

        except Exception as e:
            logger.warning(f"Roblox avatar thumbnail fetch failed: {e}")
            return None

    @staticmethod
    async def resolve_username(typed_username: str) -> Dict:
        """
        Convenience wrapper used by the /register command.

        Always returns a dict with keys:
            display_username: str   - exact-cased name from Roblox, or the typed value as fallback
            roblox_user_id: Optional[int]
            avatar_url: Optional[str]
            verified: bool          - True if Roblox confirmed the account exists
        """
        roblox_user = await RobloxAPI.get_user_by_username(typed_username)

        if roblox_user is None:
            return {
                "display_username": typed_username.strip(),
                "roblox_user_id": None,
                "avatar_url": None,
                "verified": False,
            }

        roblox_user_id = roblox_user.get("id")
        avatar_url = await RobloxAPI.get_avatar_headshot_url(roblox_user_id) if roblox_user_id else None

        return {
            "display_username": roblox_user.get("name", typed_username.strip()),
            "roblox_user_id": roblox_user_id,
            "avatar_url": avatar_url,
            "verified": True,
        }
