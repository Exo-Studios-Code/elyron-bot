"""
Level System Cog
Converts player Elo into a FACEIT-style Skill Level (1-10 + Challenger),
auto-assigns a matching Discord role, and exposes a /level profile card.

Other cogs call into this one (via bot.get_cog('LevelSystem')) any time a
player's Elo changes, so their Discord role always reflects their current
level: after /register (starting Elo), after /match confirm, and after
/admin set_elo or /admin season_reset.
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, Tuple

from utils.config import Config
from utils.embeds import EmbedBuilder
from utils import levels as level_utils


class LevelSystem(commands.Cog):
    """Cog handling FACEIT-style levels, Discord role sync, and the /level command."""

    def __init__(self, bot):
        self.bot = bot

    # =========================================================
    # ROLE MANAGEMENT
    # =========================================================

    async def ensure_level_roles(self, guild: discord.Guild) -> dict:
        """
        Makes sure all 11 level roles (Level 1-10, Challenger) exist on the
        guild, creating any missing ones with a matching color. Returns a
        dict mapping level key (int 1-10, or 'challenger') -> discord.Role.
        """
        roles = {}

        for bracket in level_utils.LEVEL_BRACKETS:
            role = await self._get_or_create_role(
                guild, Config.LEVEL_ROLE_NAMES[bracket["level"]], bracket["color"]
            )
            roles[bracket["level"]] = role

        roles["challenger"] = await self._get_or_create_role(
            guild, Config.LEVEL_ROLE_NAMES["challenger"], level_utils.CHALLENGER_BRACKET["color"]
        )

        return roles

    async def _get_or_create_role(self, guild: discord.Guild, name: str, color: int) -> Optional[discord.Role]:
        existing = discord.utils.get(guild.roles, name=name)
        if existing:
            return existing
        try:
            return await guild.create_role(
                name=name,
                color=discord.Color(color),
                reason="FACEIT-style level role auto-setup"
            )
        except discord.Forbidden:
            self.bot.logger.error(f"LevelSystem: missing permissions to create role '{name}' in guild {guild.id}.")
            return None

    async def sync_member_role(self, member: discord.Member, elo: int):
        """
        Ensures `member` has exactly one level role - the one matching
        their current Elo (or Challenger, if they qualify) - removing any
        other level roles they previously held. Safe to call often; no-ops
        cleanly if the bot lacks the Manage Roles permission.
        """
        guild = member.guild
        is_chal = await level_utils.is_challenger(self.bot.db, member.id, elo)
        target_key = "challenger" if is_chal else level_utils.get_level_number(elo)
        target_name = Config.LEVEL_ROLE_NAMES[target_key]
        target_color = level_utils.get_embed_color(elo, is_chal)

        all_level_role_names = set(Config.LEVEL_ROLE_NAMES.values())
        target_role = discord.utils.get(guild.roles, name=target_name)

        if target_role is None:
            target_role = await self._get_or_create_role(guild, target_name, target_color)
            if target_role is None:
                return  # No permission to create roles - skip silently, nothing else we can do

        roles_to_remove = [
            r for r in member.roles
            if r.name in all_level_role_names and r.id != target_role.id
        ]

        try:
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="FACEIT-style level role sync")
            if target_role not in member.roles:
                await member.add_roles(target_role, reason="FACEIT-style level role sync")
        except discord.Forbidden:
            self.bot.logger.warning(
                f"LevelSystem: missing permissions to sync roles for {member} in guild {guild.id}. "
                "Make sure the bot role has 'Manage Roles' and sits above the level roles."
            )

    async def sync_all_members(self, guild: discord.Guild) -> Tuple[int, int]:
        """
        Ensures the 11 level roles exist, then resyncs every registered
        player who is currently a member of this guild. Returns
        (synced_count, skipped_count).
        """
        await self.ensure_level_roles(guild)

        players = await self.bot.db.get_all_players()
        synced = 0
        skipped = 0

        for player in players:
            member = guild.get_member(player['discord_id'])
            if member is None:
                skipped += 1
                continue
            await self.sync_member_role(member, player['elo'])
            synced += 1

        return synced, skipped

    # =========================================================
    # /level PROFILE CARD
    # =========================================================

    @app_commands.command(name="level", description="View your (or someone else's) FACEIT-style skill level.")
    @app_commands.describe(member="Whose level to check (defaults to you)")
    async def level(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=False)

        target = member or interaction.user
        player = await self.bot.db.get_player(target.id)

        if not player:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Not Registered Yet", f"{target.mention} hasn't played any matches yet."),
                ephemeral=True
            )
            return

        elo = player['elo']
        is_chal = await level_utils.is_challenger(self.bot.db, target.id, elo)
        progress = level_utils.get_progress_to_next_level(elo)
        rank = await self.bot.db.get_player_rank_by_elo(target.id)

        embed = discord.Embed(
            title=f"{level_utils.get_level_label(elo, is_chal)} ｜ {target.display_name}",
            color=level_utils.get_embed_color(elo, is_chal)
        )

        icon = level_utils.resolve_icon(elo, is_chal)
        files = []
        if icon["thumbnail_url"]:
            embed.set_thumbnail(url=icon["thumbnail_url"])
            if icon["local_path"]:
                files.append(discord.File(icon["local_path"], filename=icon["filename"]))

        total_matches = player['wins'] + player['losses']
        win_rate = (player['wins'] / total_matches * 100) if total_matches > 0 else 0

        embed.add_field(name="📊 Elo", value=f"`{elo}`", inline=True)
        embed.add_field(name="🌍 Global Rank", value=f"`#{rank}`" if rank else "`N/A`", inline=True)
        embed.add_field(name="📈 Record", value=f"`{player['wins']}W - {player['losses']}L` ({win_rate:.1f}%)", inline=True)

        if progress["is_max"]:
            bar = "▰" * 10
            note = "*Max regular level reached - Challenger is the only way up.*" if not is_chal else "*You're a Challenger - the best of the best!*"
            embed.add_field(name="🏁 Progress", value=f"{bar}\n{note}", inline=False)
        else:
            filled = int(progress["progress_pct"] // 10)
            bar = ("▰" * filled) + ("▱" * (10 - filled))
            embed.add_field(
                name="📶 Progress To Next Level",
                value=f"{bar}  `{progress['progress_pct']:.0f}%`\nNeed **{progress['next_min']}** Elo for the next level.",
                inline=False
            )

        if player.get('roblox_username'):
            embed.add_field(name="🎮 Roblox Account", value=f"`{player['roblox_username']}`", inline=False)
            if player.get('roblox_avatar_url'):
                embed.set_author(name="Blox Strike Profile", icon_url=player['roblox_avatar_url'])

        embed.set_footer(text="FACEIT-Style Level System")
        await interaction.followup.send(embed=embed, files=files)


async def setup(bot):
    await bot.add_cog(LevelSystem(bot))
