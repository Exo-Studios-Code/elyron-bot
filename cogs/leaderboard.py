"""
Leaderboard Cog
Shows global player rankings, individual rank lookups, and league-wide
statistics, all using the FACEIT-style Level system.

NOTE: this file previously contained a copy-paste duplicate of
HelpCommand instead of an actual Leaderboard cog, meaning /leaderboard,
/rank, and /stats never existed even though help_command.py advertised
them. This is the real implementation.
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from utils.config import Config
from utils.embeds import EmbedBuilder
from utils import levels as level_utils


class Leaderboard(commands.Cog):
    """Commands for viewing global rankings, individual rank, and league stats."""

    leaderboard_group = app_commands.Group(name="leaderboard", description="View global player rankings")

    def __init__(self, bot):
        self.bot = bot

    @leaderboard_group.command(name="players", description="Shows the top players globally, ranked by Elo.")
    @app_commands.describe(limit="Number of players to show (max 25)")
    async def leaderboard_players(self, interaction: discord.Interaction, limit: int = 10):
        await interaction.response.defer()

        limit = max(1, min(limit, 25))
        top_players = await self.bot.db.get_top_players(limit)

        for entry in top_players:
            entry['is_challenger'] = await level_utils.is_challenger(self.bot.db, entry['discord_id'], entry['elo'])

        embed = EmbedBuilder.leaderboard(top_players, "Top Players - Global Leaderboard")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="rank", description="Shows a player's rank, Elo, and win/loss record.")
    @app_commands.describe(member="The player to look up (defaults to you)")
    async def rank(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await interaction.response.defer()

        target = member or interaction.user
        player = await self.bot.db.get_player(target.id)

        if not player:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Not Registered", f"{target.mention} hasn't played any matches yet."),
                ephemeral=True
            )
            return

        elo = player['elo']
        is_chal = await level_utils.is_challenger(self.bot.db, target.id, elo)
        rank_position = await self.bot.db.get_player_rank_by_elo(target.id)
        level_label = level_utils.get_level_label(elo, is_chal)

        total_matches = player['wins'] + player['losses']
        win_rate = (player['wins'] / total_matches * 100) if total_matches > 0 else 0

        embed = discord.Embed(
            title=f"📊 {target.display_name}'s Rank",
            color=level_utils.get_embed_color(elo, is_chal)
        )

        icon = level_utils.resolve_icon(elo, is_chal)
        files = []
        if icon["thumbnail_url"]:
            embed.set_thumbnail(url=icon["thumbnail_url"])
            if icon["local_path"]:
                files.append(discord.File(icon["local_path"], filename=icon["filename"]))

        embed.add_field(name="🏅 Skill Level", value=f"**{level_label}**", inline=True)
        embed.add_field(name="📊 Elo", value=f"`{elo}`", inline=True)
        embed.add_field(name="🌍 Global Rank", value=f"`#{rank_position}`" if rank_position else "`N/A`", inline=True)
        embed.add_field(
            name="📈 Record",
            value=f"`{player['wins']}W - {player['losses']}L` ({win_rate:.1f}% winrate, {total_matches} matches)",
            inline=False
        )

        embed.set_footer(text="FACEIT-Style Level System")
        await interaction.followup.send(embed=embed, files=files)

    @app_commands.command(name="stats", description="Shows overall league and season statistics.")
    async def stats(self, interaction: discord.Interaction):
        await interaction.response.defer()

        season_id = await self.bot.db.get_active_season()
        all_players = await self.bot.db.get_all_players()
        queue_players = await self.bot.db.get_all_queued_players()

        rs_confirmed = await self.bot.db._exec("SELECT COUNT(*) FROM matches WHERE status = 'confirmed'")
        confirmed_matches = self.bot.db._scalar(rs_confirmed) or 0

        rs_active = await self.bot.db._exec("SELECT COUNT(*) FROM matches WHERE status IN ('pending', 'reported')")
        active_matches = self.bot.db._scalar(rs_active) or 0

        embed = discord.Embed(
            title="📊 League Statistics",
            color=Config.COLOR_INFO
        )

        embed.add_field(name="🗓️ Active Season", value=f"`#{season_id}`" if season_id else "`None`", inline=True)
        embed.add_field(name="👥 Registered Players", value=f"`{len(all_players)}`", inline=True)
        embed.add_field(name="🎮 In Queue Right Now", value=f"`{len(queue_players)}/10`", inline=True)

        embed.add_field(name="✅ Matches Played", value=f"`{confirmed_matches}`", inline=True)
        embed.add_field(name="⚔️ Matches In Progress", value=f"`{active_matches}`", inline=True)

        if all_players:
            avg_elo = sum(p['elo'] for p in all_players) // len(all_players)
            embed.add_field(name="📈 Average Elo", value=f"`{avg_elo}`", inline=True)

        embed.set_footer(text="CS2 PUG League | Blox Strike")
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Leaderboard(bot))
