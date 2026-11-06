"""
FACEIT-Style Level System
--------------------------
Converts a player's Elo into a FACEIT-style Skill Level (1-10), plus the
special "Challenger" tier for the best players - mirroring how FACEIT
itself presents skill levels for CS2.

The brackets below are FACEIT's real CS2 Elo -> Level brackets. Challenger
is NOT a fixed Elo range - it's a leaderboard position (top N players who
are already Level 10) - see is_challenger().

Icon filenames match exactly what was provided for this project
(1.png ... 10.png, challenger.png). Two ways to provide the actual images:
  1. Local folder (no hosting needed): drop the 11 files into
     Config.LEVEL_ICON_LOCAL_DIR (relative to the bot's working directory)
     and resolve_icon() will have the bot attach them directly to messages.
  2. Remote URL: host them anywhere (GitHub raw, your own CDN, etc.) and
     set Config.LEVEL_ICON_BASE_URL - this takes priority over the local
     folder if both are set.

NOTE: the embed colors below are a tasteful grey -> yellow -> orange -> red
progression inspired by FACEIT's general look, not guaranteed pixel-exact
to FACEIT's official branding. They're trivial to tweak below if needed.
"""

import os
from typing import Dict, List, Optional

from utils.config import Config

# (level, min_elo, max_elo or None for "no ceiling", icon filename, embed color)
LEVEL_BRACKETS: List[Dict] = [
    {"level": 1,  "min_elo": 100,  "max_elo": 500,  "icon": "1.png",  "color": 0xB0B0B0},
    {"level": 2,  "min_elo": 501,  "max_elo": 750,  "icon": "2.png",  "color": 0xB0B0B0},
    {"level": 3,  "min_elo": 751,  "max_elo": 900,  "icon": "3.png",  "color": 0xB0B0B0},
    {"level": 4,  "min_elo": 901,  "max_elo": 1050, "icon": "4.png",  "color": 0xFFC107},
    {"level": 5,  "min_elo": 1051, "max_elo": 1200, "icon": "5.png",  "color": 0xFFC107},
    {"level": 6,  "min_elo": 1201, "max_elo": 1350, "icon": "6.png",  "color": 0xFFC107},
    {"level": 7,  "min_elo": 1351, "max_elo": 1530, "icon": "7.png",  "color": 0xFF7700},
    {"level": 8,  "min_elo": 1531, "max_elo": 1750, "icon": "8.png",  "color": 0xFF7700},
    {"level": 9,  "min_elo": 1751, "max_elo": 2000, "icon": "9.png",  "color": 0xE53935},
    {"level": 10, "min_elo": 2001, "max_elo": None, "icon": "10.png", "color": 0x8B0000},
]

CHALLENGER_BRACKET: Dict = {"level": "challenger", "icon": "challenger.png", "color": 0xFFD700}


def get_level_bracket(elo: int) -> Dict:
    """Returns the bracket dict (level, min_elo, max_elo, icon, color) for a given Elo."""
    safe_elo = max(elo, LEVEL_BRACKETS[0]["min_elo"])
    for bracket in LEVEL_BRACKETS:
        if safe_elo >= bracket["min_elo"] and (bracket["max_elo"] is None or safe_elo <= bracket["max_elo"]):
            return bracket
    return LEVEL_BRACKETS[-1]


def get_level_number(elo: int) -> int:
    """Returns just the numeric level (1-10) for a given Elo, ignoring Challenger status."""
    return get_level_bracket(elo)["level"]


def get_icon_filename(elo: int, is_challenger: bool = False) -> str:
    if is_challenger:
        return CHALLENGER_BRACKET["icon"]
    return get_level_bracket(elo)["icon"]


def get_icon_url(elo: int, is_challenger: bool = False) -> Optional[str]:
    """Builds the full remote icon URL using Config.LEVEL_ICON_BASE_URL + the bracket's filename. Returns None if LEVEL_ICON_BASE_URL isn't set."""
    base = getattr(Config, "LEVEL_ICON_BASE_URL", "")
    if not base:
        return None
    filename = get_icon_filename(elo, is_challenger)
    return f"{base.rstrip('/')}/{filename}"


def get_icon_local_path(elo: int, is_challenger: bool = False) -> Optional[str]:
    """Returns the local filesystem path to the icon if it exists in Config.LEVEL_ICON_LOCAL_DIR, else None."""
    local_dir = getattr(Config, "LEVEL_ICON_LOCAL_DIR", "")
    if not local_dir:
        return None
    filename = get_icon_filename(elo, is_challenger)
    candidate = os.path.join(local_dir, filename)
    return candidate if os.path.isfile(candidate) else None


def resolve_icon(elo: int, is_challenger: bool = False) -> Dict:
    """
    Decides where the level icon comes from, in priority order:
      1. Config.LEVEL_ICON_BASE_URL (a remote URL), if set.
      2. A matching file inside Config.LEVEL_ICON_LOCAL_DIR, if it exists.
      3. Nothing - no icon available.

    Returns {'thumbnail_url': str|None, 'local_path': str|None, 'filename': str}.
    'thumbnail_url' is what to pass to embed.set_thumbnail(url=...).
    If 'local_path' is set, you MUST also attach that file to the message
    (e.g. discord.File(local_path, filename=filename)) for the thumbnail
    to actually render, since 'thumbnail_url' will be "attachment://<filename>".
    """
    filename = get_icon_filename(elo, is_challenger)

    remote_url = get_icon_url(elo, is_challenger)
    if remote_url:
        return {"thumbnail_url": remote_url, "local_path": None, "filename": filename}

    local_path = get_icon_local_path(elo, is_challenger)
    if local_path:
        return {"thumbnail_url": f"attachment://{filename}", "local_path": local_path, "filename": filename}

    return {"thumbnail_url": None, "local_path": None, "filename": filename}


def get_embed_color(elo: int, is_challenger: bool = False) -> int:
    if is_challenger:
        return CHALLENGER_BRACKET["color"]
    return get_level_bracket(elo)["color"]


def get_level_label(elo: int, is_challenger: bool = False) -> str:
    """Human readable label, e.g. 'Level 7' or 'Challenger'."""
    if is_challenger:
        return "Challenger"
    return f"Level {get_level_number(elo)}"


def get_progress_to_next_level(elo: int) -> Dict:
    """
    Returns progress info towards the next level:
    {'current_min': int, 'next_min': Optional[int], 'progress_pct': float, 'is_max': bool}
    Level 10 has no ceiling, so is_max becomes True once a player reaches it.
    """
    bracket = get_level_bracket(elo)
    if bracket["max_elo"] is None:
        return {"current_min": bracket["min_elo"], "next_min": None, "progress_pct": 100.0, "is_max": True}

    span = bracket["max_elo"] - bracket["min_elo"] + 1
    progressed = elo - bracket["min_elo"]
    pct = max(0.0, min(100.0, (progressed / span) * 100))
    next_min = bracket["max_elo"] + 1
    return {"current_min": bracket["min_elo"], "next_min": next_min, "progress_pct": pct, "is_max": False}


async def is_challenger(db, discord_id: int, elo: int) -> bool:
    """
    A player is Challenger if they're Level 10 (2001+ Elo) AND ranked within
    the top Config.CHALLENGER_TOP_N players league-wide by Elo. Real FACEIT
    uses 1000 per region - lower CHALLENGER_TOP_N in config.py for a
    smaller community so the badge stays attainable.
    """
    if elo < 2001:
        return False
    rank = await db.get_player_rank_by_elo(discord_id)
    if rank is None:
        return False
    return rank <= Config.CHALLENGER_TOP_N
