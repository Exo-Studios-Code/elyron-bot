"""
Configuration settings for the Blox Strike PUG League Bot.
"""

import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Bot configuration constants."""
    
    # Bot settings
    TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")
    PREFIX = os.getenv("COMMAND_PREFIX", "!")  # Bot is fully Slash Command based; discord.py's Bot() still requires this argument
    
    # Database
    DATABASE_PATH = "data/cs2_league.db"
    
    # ELO settings
    STARTING_ELO = 1000
    K_FACTOR_BASE = 32
    K_FACTOR_HIGH = 24  # For players above 2000 ELO
    K_FACTOR_LOW = 40   # For players below 1000 ELO
    ELO_MATCH_RANGE = 300  # Maximum ELO difference for matchmaking
    
    # Season settings
    SEASON_DURATION_DAYS = 180  # 6 months
    
    # Logging
    LOG_LEVEL = "INFO"
    LOG_FILE = "logs/bot.log"
    
    # Map Pool
    CS2_MAPS = [
        "Ancient",
        "Anubis", 
        "Dust2",
        "Mirage",
        "Inferno",
        "Nuke",
        "Vertigo"
    ]
    
    # Map veto settings
    MAP_VETO_TIMEOUT = 120  # 2 minutes per ban
    
    # Admin roles (role IDs that can use admin commands, in addition to server Administrators)
    ADMIN_ROLE_IDS = []  # Add role IDs here, e.g., [123456789, 987654321]
    
    # General-purpose embed color (used outside of EmbedBuilder's own helpers)
    COLOR_INFO = 0x3498DB
    
    # ==========================================
    # FACEIT-STYLE LEVEL SYSTEM
    # ==========================================
    # Point this at wherever you host the level icon images
    # (1.png ... 10.png, challenger.png). Can be a GitHub raw URL, your own
    # web host, or any image CDN. Leave empty to skip thumbnails entirely -
    # level numbers, names, and colors still work fine without it.
    #
    # The final icon URL the bot builds is simply: LEVEL_ICON_BASE_URL + "/" + filename
    # e.g. with the example below, Level 7 resolves to:
    # "https://raw.githubusercontent.com/you/repo/main/assets/levels/7.png"
    LEVEL_ICON_BASE_URL = ""  # e.g. "https://raw.githubusercontent.com/you/repo/main/assets/levels"

    # ALTERNATIVE to the URL above - no external hosting needed. Drop the
    # 11 files (1.png ... 10.png, challenger.png) directly into this folder
    # inside the bot's own project, and the bot will attach them straight
    # from disk. Only used if LEVEL_ICON_BASE_URL above is left empty.
    LEVEL_ICON_LOCAL_DIR = "assets/levels"

    # How many top players (by Elo, must also be Level 10) get the special
    # "Challenger" badge instead of a plain "Level 10" badge. Real FACEIT
    # uses 1000 per region - lower this for a smaller Discord community so
    # Challenger stays achievable.
    CHALLENGER_TOP_N = 1000

    # Discord role names the bot will auto-create (if missing) and assign
    # based on each player's current FACEIT-style level.
    LEVEL_ROLE_NAMES = {
        1: "Level 1", 2: "Level 2", 3: "Level 3", 4: "Level 4", 5: "Level 5",
        6: "Level 6", 7: "Level 7", 8: "Level 8", 9: "Level 9", 10: "Level 10",
        "challenger": "Challenger",
    }
    
    @staticmethod
    def calculate_k_factor(elo: int) -> int:
        """Calculate K-factor based on ELO."""
        if elo >= 2000:
            return Config.K_FACTOR_HIGH
        elif elo <= 1000:
            return Config.K_FACTOR_LOW
        else:
            return Config.K_FACTOR_BASE
