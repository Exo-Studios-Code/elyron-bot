"""
Help Command Cog
Shows the FACEIT-style Slash Command list and Quick Start Guide.
Reflects the dynamic PUG / Matchmaking system, Roblox registration,
private Matchrooms, and the FACEIT-style Level system.
"""

import discord
from discord import app_commands
from discord.ext import commands

class HelpCommand(commands.Cog):
    """Cog for displaying the interactive Help menu."""
    
    def __init__(self, bot):
        self.bot = bot
        
    @app_commands.command(name="help", description="Show all available commands and a quick start guide.")
    async def help_command(self, interaction: discord.Interaction):
        """Displays the comprehensive command list and FACEIT-style system guide."""
        
        embed = discord.Embed(
            title="🎮 Blox Strike PUG League - Help & Commands",
            description=(
                "**FACEIT-Style Matchmaking System**\n"
                "Solo/Party Queue + Map Veto + Dynamic Snake Draft + Skill Levels\n"
                "─────────────────────────────"
            ),
            color=0xFF6B00  # FACEIT Orange
        )
        
        # GETTING STARTED
        embed.add_field(
            name="🆕 GETTING STARTED",
            value=(
                "**`/register roblox_username:`**\n"
                "Links your Roblox account - required before you can queue\n\n"
                "**`/level [@player]`**\n"
                "View your (or someone else's) FACEIT-style Skill Level, Elo, and progress bar"
            ),
            inline=False
        )
        
        # PARTY COMMANDS
        embed.add_field(
            name="🎉 PARTY MANAGEMENT",
            value=(
                "**`/party invite @player`**\n"
                "Invites a player to your party (max 5 players)\n\n"
                "**`/party leave`**\n"
                "Leaves your current party, or disbands it if you're the leader\n\n"
                "**`/party view`**\n"
                "Shows your current party members and leader status"
            ),
            inline=False
        )
        
        # QUEUE COMMANDS  
        embed.add_field(
            name="🎯 QUEUE & MATCHMAKING",
            value=(
                "**`Queue UI Buttons`**\n"
                "Use the Join/Leave buttons in the matchmaking channel\n\n"
                "**`/queue join`** | **`/queue leave`**\n"
                "Slash command alternatives to the buttons\n\n"
                "**`/queue status`**\n"
                "Shows the current queue and player count (x/10)\n\n"
                "**`/queue setup`** _(Admin)_\n"
                "Deploys the persistent queue UI panel"
            ),
            inline=False
        )
        
        # MATCHROOM COMMANDS
        embed.add_field(
            name="⚔️ MATCHROOMS (Lobby Captains)",
            value=(
                "**`/matchroom link match_id: link:`**\n"
                "Posts your Roblox private server link for the match\n\n"
                "**`/matchroom close match_id:`**\n"
                "Manually closes a Matchroom's private channels\n\n"
                "**`/match report match_id: result:`**\n"
                "Reports the match result (Win/Loss)\n\n"
                "**`/match confirm match_id:`**\n"
                "Confirms the opponent's report and distributes Elo\n\n"
                "**`/match dispute match_id: reason:`**\n"
                "Formally dispute a reported result — opens a case for admin review\n\n"
                "**`/match history limit:`**\n"
                "Shows your recent match history and Elo changes"
            ),
            inline=False
        )
        
        # STATS
        embed.add_field(
            name="📊 MATCH STATISTICS (Scoreboard OCR)",
            value=(
                "**`/stats upload match_id: screenshot:`**\n"
                "Captain uploads scoreboard screenshot → Gemini Vision parses stats automatically\n\n"
                "**`/stats match match_id:`**\n"
                "View the full parsed scoreboard for any match (K/D/A, MVPs, Score)\n\n"
                "**`/stats player [@player]`**\n"
                "Career stats + last 5 matches breakdown for you or any player"
            ),
            inline=False
        )

        # LEADERBOARD COMMANDS
        embed.add_field(
            name="🏆 LEADERBOARDS & STATISTICS",
            value=(
                "**`/leaderboard players limit:`**\n"
                "Shows the top players globally, ranked by Elo\n\n"
                "**`/rank [@player]`**\n"
                "Shows a player's Skill Level, Elo, and win/loss record\n\n"
                "**`/stats`**\n"
                "Shows overall league and season statistics"
            ),
            inline=False
        )
        
        # ADMIN COMMANDS
        embed.add_field(
            name="⚙️ ADMIN COMMANDS",
            value=(
                "**`/admin season_info`** | **`/admin season_reset`**\n"
                "**`/admin set_elo`** | **`/admin cancel_match`**\n"
                "**`/admin clear_queue`** | **`/admin announce`**\n"
                "**`/admin sync_levels`** - create/refresh all 11 level roles\n"
                "**`/admin dispute match_id: [override_winner:]`** - view or force-override a match result\n"
                "**`/admin disputes`** - list all open unresolved disputes\n"
                "**`/admin clear_cooldown @player`** - remove a player's queue leave cooldown\n"
            ),
            inline=False
        )
        
        # AUTOMATIC SYSTEMS
        embed.add_field(
            name="🤖 AUTOMATIC SYSTEMS",
            value=(
                "• **Snake Draft:** Auto-balances teams using player Elo (10-man PUGs).\n"
                "• **Party Preservation:** Ensures party members stay on the same team.\n"
                "• **Map Veto:** Captains (highest Elo) receive DMs to ban maps.\n"
                "• **Private Match Channels:** Auto-created text/voice rooms per team.\n"
                "• **FACEIT-Style Levels:** Elo automatically maps to Level 1-10 (or "
                "Challenger), with a matching Discord role assigned automatically."
            ),
            inline=False
        )
        
        # QUICK START GUIDE
        embed.add_field(
            name="🚀 QUICK START GUIDE",
            value=(
                "**1.** Run `/register` and link your Roblox username.\n"
                "**2.** Click **➕ Join Queue** (or use `/party invite` first for a group).\n"
                "**3.** Wait for 10 players. Highest-Elo players become Captains and veto maps via DM.\n"
                "**4.** Your private team channels appear - the Captain posts the Roblox private "
                "server link with `/matchroom link`.\n"
                "**5.** Play the match, then Captains use `/match report` and `/match confirm` to "
                "log the result and update Elo."
            ),
            inline=False
        )
        
        embed.set_footer(text="Blox Strike PUG League Bot • Fully Slash Command Integrated")
        
        # Use ephemeral=True so the help menu doesn't clog up the chat channels
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(HelpCommand(bot))