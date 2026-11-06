"""
Discord Embed Utilities
Provides luxurious, consistent, and premium UI components across the bot.
Tailored for the FACEIT-style PUG Matchmaking System.
"""

import discord
from datetime import datetime
from typing import Optional, List, Dict
from utils.config import Config
from utils import levels as level_utils

class EmbedBuilder:
    """Helper class for creating premium Discord embeds."""
    
    # Premium Color Palette
    COLOR_SUCCESS = 0x50C878  # Emerald Green
    COLOR_ERROR = 0xDC143C    # Crimson Red
    COLOR_INFO = 0x4169E1     # Royal Blue
    COLOR_WARNING = 0xFFD700  # Premium Gold
    COLOR_FACEIT = 0xFF5500   # FACEIT Orange
    COLOR_DARK = 0x2B2D31     # Discord Dark Gray (Invisible background)

    @staticmethod
    def create_base_embed(title: str, description: str = "", color: int = COLOR_INFO) -> discord.Embed:
        """Create a sleek, minimal base embed."""
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="CS2 Premium League", icon_url="https://i.imgur.com/KzxbT3P.png") # Optional: Add your bot's icon URL here
        return embed
    
    @staticmethod
    def success(title: str, description: str = "") -> discord.Embed:
        """Create a luxurious success embed (Emerald)."""
        return EmbedBuilder.create_base_embed(
            f"✅ ｜ {title}", 
            f"> {description}" if description else "", 
            EmbedBuilder.COLOR_SUCCESS
        )
    
    @staticmethod
    def error(title: str, description: str = "") -> discord.Embed:
        """Create a striking error embed (Crimson)."""
        return EmbedBuilder.create_base_embed(
            f"🛑 ｜ {title}", 
            f"> {description}" if description else "", 
            EmbedBuilder.COLOR_ERROR
        )
    
    @staticmethod
    def info(title: str, description: str = "") -> discord.Embed:
        """Create a clean info embed (Royal Blue)."""
        return EmbedBuilder.create_base_embed(
            f"💠 ｜ {title}", 
            description, 
            EmbedBuilder.COLOR_INFO
        )
    
    @staticmethod
    def warning(title: str, description: str = "") -> discord.Embed:
        """Create a premium warning embed (Gold)."""
        return EmbedBuilder.create_base_embed(
            f"⚠️ ｜ {title}", 
            f"> {description}" if description else "", 
            EmbedBuilder.COLOR_WARNING
        )
    
    @staticmethod
    def party_info(party: Dict, members: List[Dict]) -> discord.Embed:
        """
        Create a luxurious embed showing Party information, using
        FACEIT-style level badges instead of the old Bronze/Silver ranks.
        """
        avg_elo = sum(m['elo'] for m in members) // len(members) if members else 0
        level_label = level_utils.get_level_label(avg_elo)
        
        embed = discord.Embed(
            title="🎉 ｜ Active Party",
            description="Currently queued or resting in the lobby.",
            color=level_utils.get_embed_color(avg_elo),
            timestamp=datetime.utcnow()
        )
        
        embed.add_field(
            name="📊 Party Statistics",
            value=(
                f"**Members:** `{len(members)}/5`\n"
                f"**Average ELO:** `{avg_elo}`\n"
                f"**Average Level:** {level_label}"
            ),
            inline=False
        )
        
        # Format member list beautifully
        if members:
            member_lines = []
            for m in members:
                is_leader = m['discord_id'] == party['leader_id']
                icon = "👑" if is_leader else "👤"
                role = "**Leader**" if is_leader else "Member"
                member_level = level_utils.get_level_label(m['elo'])
                member_lines.append(f"{icon} <@{m['discord_id']}> — `{m['elo']} ELO` {member_level} *({role})*")
                
            embed.add_field(
                name="👥 Roster",
                value="\n".join(member_lines),
                inline=False
            )
            
        embed.set_footer(text="CS2 Matchmaking System")
        return embed
    
    @staticmethod
    def player_stats(player: Dict, party: Optional[Dict] = None, is_challenger: bool = False, rank: Optional[int] = None) -> discord.Embed:
        """
        Create a premium, FACEIT-style player profile embed: level icon,
        level badge color, and a progress bar towards the next level.
        `is_challenger` and `rank` should be pre-computed by the caller
        (they require async DB lookups this static method can't do itself).
        """
        elo = player['elo']
        level_label = level_utils.get_level_label(elo, is_challenger)
        color = level_utils.get_embed_color(elo, is_challenger)
        icon_url = level_utils.get_icon_url(elo, is_challenger)
        
        embed = discord.Embed(
            title=f"💎 ｜ {player['username']}'s Profile",
            color=color,
            timestamp=datetime.utcnow()
        )
        
        if icon_url:
            embed.set_thumbnail(url=icon_url)
        
        total_matches = player['wins'] + player['losses']
        win_rate = (player['wins'] / total_matches * 100) if total_matches > 0 else 0
        
        embed.add_field(
            name="🏅 Skill Level",
            value=f"**{level_label}**" + (f"\n🌍 Global Rank `#{rank}`" if rank else ""),
            inline=True
        )
        embed.add_field(name="📊 Elo", value=f"`{elo}`", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        
        embed.add_field(
            name="📈 Performance Metrics",
            value=(
                f"**Overall Record:** `{player['wins']}W` - `{player['losses']}L`\n"
                f"**Win Rate:** `{win_rate:.1f}%`\n"
                f"**Matches Played:** `{total_matches}`"
            ),
            inline=False
        )
        
        if player.get('roblox_username'):
            embed.add_field(name="🎮 Roblox Account", value=f"`{player['roblox_username']}`", inline=False)
        
        if party:
            embed.add_field(
                name="🎉 Current Status",
                value="Playing in an active Party.",
                inline=False
            )
        else:
            embed.add_field(
                name="👤 Current Status",
                value="Playing Solo Queue.",
                inline=False
            )
        
        embed.set_footer(text="FACEIT-Style Level System")
        return embed
    
    @staticmethod
    def match_result(match: Dict, team1: Dict, team2: Dict, elo_change: int, is_upset: bool) -> discord.Embed:
        """Create a stunning post-match result screen."""
        winner = team1 if match['winner_id'] == team1['team_id'] else team2
        loser = team2 if match['winner_id'] == team1['team_id'] else team1
        
        title = "🏆 ｜ MATCH CONCLUDED"
        color = EmbedBuilder.COLOR_SUCCESS
        
        if is_upset:
            title = "🔥 ｜ MASSIVE UPSET VICTORY!"
            color = EmbedBuilder.COLOR_WARNING
        
        embed = discord.Embed(
            title=title,
            description=f"### **{winner['name']}** absolutely dominated **{loser['name']}**",
            color=color,
            timestamp=datetime.utcnow()
        )
        
        # Winner stats (Green emphasis)
        winner_elo_before = match['team1_elo_before'] if winner['team_id'] == team1['team_id'] else match['team2_elo_before']
        winner_elo_after = match['team1_elo_after'] if winner['team_id'] == team1['team_id'] else match['team2_elo_after']
        
        embed.add_field(
            name="🟢 WINNERS",
            value=(
                f"**{winner['name']}**\n"
                f"ELO: `{winner_elo_before}` ➔ `{winner_elo_after}` **(+{elo_change})** 📈\n"
            ),
            inline=True
        )
        
        # Vertical divider
        embed.add_field(name="⚔️", value="**VS**", inline=True)
        
        # Loser stats (Red emphasis)
        loser_elo_before = match['team2_elo_before'] if loser['team_id'] == team2['team_id'] else match['team1_elo_before']
        loser_elo_after = match['team2_elo_after'] if loser['team_id'] == team2['team_id'] else match['team1_elo_after']
        
        embed.add_field(
            name="🔴 DEFEATED",
            value=(
                f"**{loser['name']}**\n"
                f"ELO: `{loser_elo_before}` ➔ `{loser_elo_after}` **(-{elo_change})** 📉\n"
            ),
            inline=True
        )
        
        if match.get('map_played'):
            embed.add_field(name="🗺️ Map Played", value=f"`{match['map_played']}`", inline=False)
            
        embed.set_footer(text=f"Matchroom ID: #{match['match_id']} | FACEIT ELO System")
        return embed
    
    @staticmethod
    def leaderboard(entries: List[Dict], title: str) -> discord.Embed:
        """
        Create a highly polished, FACEIT-style leaderboard embed.
        Each entry dict may optionally include 'is_challenger': bool,
        pre-computed by the caller, to show the Challenger badge instead
        of a plain Level 10 badge.
        """
        embed = discord.Embed(
            title=f"🌟 ｜ {title}",
            description="The most elite players in the league.",
            color=EmbedBuilder.COLOR_WARNING,
            timestamp=datetime.utcnow()
        )
        
        if not entries:
            embed.description = "> *The arena is empty. No players have ranked up yet.*"
            return embed
        
        leaderboard_text = []
        medals = ["👑", "🥈", "🥉"]
        
        for i, entry in enumerate(entries, 1):
            medal = medals[i-1] if i <= 3 else f"`{i:02d}.`"
            name = entry['username']
            elo = entry['elo']
            is_challenger = entry.get('is_challenger', False)
            level_label = level_utils.get_level_label(elo, is_challenger)
            
            wins = entry['wins']
            losses = entry['losses']
            total = wins + losses
            wr = (wins / total * 100) if total > 0 else 0
            
            # Format the line with inline code blocks for a clean grid look
            line = f"{medal} **{name}** — `{elo} ELO` {level_label}\n└ 🗡️ `{wins}W` - `{losses}L` *(Winrate: {wr:.1f}%)*"
            leaderboard_text.append(line)
        
        embed.description = "\n\n".join(leaderboard_text)
        embed.set_footer(text="CS2 Global Rankings | FACEIT-Style Levels")
        return embed