"""
Match System Cog
Handles result reporting, confirmation, and match history for FACEIT-style
PUG Matchrooms. Fully on Slash Commands.

IMPORTANT FIX: players no longer have a permanent team_id - every match
drafts a brand new temporary PUG team - so this cog now looks up a
player's CURRENT active team (and their full match history) through
utils/database.py's get_active_team_for_player() / get_player_match_history()
helpers instead of the old (and broken) `player['team_id']` lookups.
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from utils.config import Config
from utils.embeds import EmbedBuilder
from utils.elo import ELOCalculator


class MatchSystem(commands.Cog):
    """Commands for managing FACEIT-style Matchrooms, Elo, and results."""

    match_group = app_commands.Group(name="match", description="Manage FACEIT matches, Elo, and results")

    def __init__(self, bot):
        self.bot = bot

    @match_group.command(name="report", description="Report your match result (Lobby Captains only).")
    @app_commands.describe(
        match_id="Your Matchroom ID",
        result="Whether your team won or lost"
    )
    @app_commands.choices(result=[
        app_commands.Choice(name="🏆 Win", value="win"),
        app_commands.Choice(name="💀 Loss", value="loss")
    ])
    async def match_report(self, interaction: discord.Interaction, match_id: int, result: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=False)

        match = await self.bot.db.get_match(match_id)
        if not match:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Match Not Found",
                f"No Matchroom with ID `#{match_id}` exists."
            ))
            return

        if match['status'] == 'confirmed':
            await interaction.followup.send(embed=EmbedBuilder.warning(
                "Already Confirmed",
                "This match has already been confirmed and Elo has been distributed."
            ))
            return

        user_team = await self.bot.db.get_active_team_for_player(interaction.user.id)
        if not user_team:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "No Active Matchroom",
                "You're not part of any team in an active Matchroom right now."
            ))
            return

        if user_team['captain_id'] != interaction.user.id:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Not A Captain",
                "Only the designated Lobby Captain can report a result."
            ))
            return

        if user_team['team_id'] not in [match['team1_id'], match['team2_id']]:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Wrong Match",
                "Your lobby isn't part of this Matchroom."
            ))
            return

        if result.value == 'win':
            winner_id = user_team['team_id']
        else:
            winner_id = (match['team2_id'] if user_team['team_id'] == match['team1_id']
                        else match['team1_id'])

        if match['status'] != 'pending':
            return

        await self.bot.db.update_match_report(match_id, winner_id, interaction.user.id)

        other_team_id = (match['team2_id'] if user_team['team_id'] == match['team1_id']
                       else match['team1_id'])
        other_team = await self.bot.db.get_team_by_id(other_team_id)

        embed = EmbedBuilder.info(
            "Result Reported",
            f"Result has been recorded. Waiting for confirmation from the opposing Captain: **{other_team['name']}**"
        )
        embed.add_field(
            name="Reported Winner",
            value=f"🏆 **{await self._get_team_name(winner_id)}**",
            inline=False
        )

        await interaction.followup.send(embed=embed)

        try:
            other_captain = await self.bot.fetch_user(other_team['captain_id'])
            notify_embed = EmbedBuilder.info(
                "Match Confirmation Needed",
                f"A result for Matchroom `#{match_id}` was just reported."
            )
            notify_embed.add_field(
                name="Reported Winner",
                value=f"**{await self._get_team_name(winner_id)}**",
                inline=False
            )

            if winner_id == other_team_id:
                notify_embed.add_field(
                    name="Next Steps",
                    value=f"Use `/match confirm match_id:{match_id}` to confirm your win and distribute Elo.",
                    inline=False
                )
            else:
                notify_embed.add_field(
                    name="Confirming A Loss",
                    value=f"If this is correct, use `/match confirm match_id:{match_id}`.\nIf it's wrong, contact an admin via support.",
                    inline=False
                )

            await other_captain.send(embed=notify_embed)
        except discord.Forbidden:
            pass  # Captain has DMs disabled

        self.bot.logger.info(f"Match {match_id} reported by {interaction.user}: winner={winner_id}")

    @match_group.command(name="confirm", description="Confirm the match result and recalculate FACEIT-style Elo.")
    @app_commands.describe(match_id="Your Matchroom ID")
    async def match_confirm(self, interaction: discord.Interaction, match_id: int):
        await interaction.response.defer(ephemeral=False)

        match = await self.bot.db.get_match(match_id)
        if not match:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Match Not Found",
                f"No Matchroom with ID `#{match_id}` exists."
            ))
            return

        if match['status'] != 'reported':
            if match['status'] == 'confirmed':
                await interaction.followup.send(embed=EmbedBuilder.warning(
                    "Already Confirmed",
                    "This match has already been closed and Elo was distributed."
                ))
            else:
                await interaction.followup.send(embed=EmbedBuilder.error(
                    "Not Reported Yet",
                    "Nobody has reported this match yet. Use `/match report` first."
                ))
            return

        user_team = await self.bot.db.get_active_team_for_player(interaction.user.id)
        if not user_team:
            await interaction.followup.send(embed=EmbedBuilder.error("No Active Matchroom", "You're not in any active team/lobby."))
            return

        if user_team['captain_id'] != interaction.user.id:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Not A Captain",
                "Only the Lobby Captain can confirm a match."
            ))
            return

        if user_team['team_id'] not in [match['team1_id'], match['team2_id']]:
            await interaction.followup.send(embed=EmbedBuilder.error("Wrong Match", "You aren't part of this lobby."))
            return

        if match['reported_by'] == interaction.user.id:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Waiting On The Opponent",
                "You reported this result. The opposing Captain now needs to confirm it."
            ))
            return

        team1 = await self.bot.db.get_team_by_id(match['team1_id'])
        team2 = await self.bot.db.get_team_by_id(match['team2_id'])
        winner_team = await self.bot.db.get_team_by_id(match['winner_id'])
        loser_team = team2 if winner_team['team_id'] == team1['team_id'] else team1

        # FACEIT-style Elo math: recompute the average team Elo (mostly for the Matchroom embed)
        new_winner_elo, new_loser_elo, elo_change = ELOCalculator.calculate_match_elo(
            winner_team['elo'],
            loser_team['elo']
        )

        await self.bot.db.confirm_match(
            match_id,
            interaction.user.id,
            new_winner_elo if winner_team['team_id'] == team1['team_id'] else new_loser_elo,
            new_loser_elo if winner_team['team_id'] == team1['team_id'] else new_winner_elo,
            elo_change
        )

        await self.bot.db.update_team_stats(winner_team['team_id'], new_winner_elo, True)
        await self.bot.db.update_team_stats(loser_team['team_id'], new_loser_elo, False)

        # PER-PLAYER Elo: every player's own Elo moves based on the enemy team's average Elo
        winner_members = await self.bot.db.get_team_members(winner_team['team_id'])
        loser_members = await self.bot.db.get_team_members(loser_team['team_id'])

        level_cog = self.bot.get_cog('LevelSystem')

        for member in winner_members:
            new_player_elo, _, _ = ELOCalculator.calculate_match_elo(
                member['elo'],
                loser_team['elo']
            )
            await self.bot.db.update_player_stats(member['discord_id'], new_player_elo, True)
            await self._sync_level_role(level_cog, interaction.guild, member['discord_id'], new_player_elo)

        for member in loser_members:
            _, new_player_elo, _ = ELOCalculator.calculate_match_elo(
                winner_team['elo'],
                member['elo']
            )
            await self.bot.db.update_player_stats(member['discord_id'], new_player_elo, False)
            await self._sync_level_role(level_cog, interaction.guild, member['discord_id'], new_player_elo)

        is_upset = ELOCalculator.is_upset(winner_team['elo'], loser_team['elo'])

        embed = EmbedBuilder.match_result(match, team1, team2, elo_change, is_upset)

        await interaction.followup.send(embed=embed)

        # If a scoreboard screenshot was already submitted for this match,
        # roll those per-match stats into career aggregates now that it's official.
        try:
            existing_stats = await self.bot.db.get_match_player_stats(match_id)
            if existing_stats:
                await self.bot.db.update_career_stats_from_match(match_id)
        except Exception as e:
            self.bot.logger.warning(f"Career stats rollup failed for match #{match_id}: {e}")

        try:
            other_captain_id = (team1['captain_id'] if interaction.user.id == team2['captain_id']
                              else team2['captain_id'])
            other_captain = await self.bot.fetch_user(other_captain_id)
            await other_captain.send(
                content=f"✅ Match `#{match_id}` has been closed and Elo distributed!",
                embed=embed
            )
        except discord.Forbidden:
            pass

        self.bot.logger.info(
            f"Match {match_id} closed: {winner_team['name']} defeated {loser_team['name']} "
            f"(+{elo_change}/-{elo_change} Elo)"
        )

    @match_group.command(name="dispute", description="Open a dispute on a reported match result.")
    @app_commands.describe(
        match_id="The Matchroom ID you want to dispute",
        reason="Brief reason for the dispute"
    )
    async def match_dispute(self, interaction: discord.Interaction, match_id: int, reason: str):
        await interaction.response.defer(ephemeral=True)

        match = await self.bot.db.get_match(match_id)
        if not match:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Not Found", f"No Matchroom with ID `#{match_id}`."), ephemeral=True)
            return

        if match['status'] not in ('reported', 'pending'):
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Cannot Dispute",
                "Only matches that are pending or already reported can be disputed.\n"
                "If the match is already confirmed, contact an admin directly."
            ), ephemeral=True)
            return

        # Make sure they're part of this match
        user_team = await self.bot.db.get_active_team_for_player(interaction.user.id)
        if not user_team or user_team['team_id'] not in [match['team1_id'], match['team2_id']]:
            await interaction.followup.send(embed=EmbedBuilder.error(
                "Not In This Match", "You are not part of this Matchroom."), ephemeral=True)
            return

        # Check if a dispute already exists
        existing = await self.bot.db.get_dispute(match_id)
        if existing and not existing.get('resolved_by'):
            await interaction.followup.send(embed=EmbedBuilder.warning(
                "Already Disputed",
                f"A dispute for Matchroom `#{match_id}` is already open. Admins have been notified."
            ), ephemeral=True)
            return

        await self.bot.db.open_dispute(match_id, interaction.user.id, reason)

        await interaction.followup.send(
            embed=EmbedBuilder.success(
                "Dispute Opened",
                f"Your dispute for Matchroom `#{match_id}` has been logged.\n"
                f"**Reason:** {reason}\n\n"
                "An admin will review it using `/admin dispute`. "
                "Do **not** run `/match confirm` — wait for the admin's decision."
            ), ephemeral=True
        )

        # Notify all admins via the announcement channel if configured, or log it
        self.bot.logger.warning(
            f"DISPUTE: Match #{match_id} disputed by {interaction.user} ({interaction.user.id}). Reason: {reason}"
        )

    @match_group.command(name="history", description="View your recent match history and Elo changes.")
    @app_commands.describe(limit="Number of matches to show (max 25)")
    async def match_history(self, interaction: discord.Interaction, limit: int = 10):
        if limit > 25:
            limit = 25

        player = await self.bot.db.get_player(interaction.user.id)
        if not player:
            await interaction.response.send_message(embed=EmbedBuilder.error(
                "No History",
                "You haven't registered or played any matches yet."
            ), ephemeral=True)
            return

        matches = await self.bot.db.get_player_match_history(interaction.user.id, limit)

        if not matches:
            await interaction.response.send_message(embed=EmbedBuilder.info(
                "No Matches Yet",
                "You haven't played any confirmed FACEIT matches yet."
            ), ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📜 Match History - {player['username']}",
            color=Config.COLOR_INFO,
        )

        for match in matches:
            # Figure out which side this player's team was on for this specific match
            team1 = await self.bot.db.get_team_by_id(match['team1_id'])
            team2 = await self.bot.db.get_team_by_id(match['team2_id'])

            team1_members = await self.bot.db.get_team_members(match['team1_id'])
            on_team1 = any(m['discord_id'] == interaction.user.id for m in team1_members)

            own_team = team1 if on_team1 else team2
            opponent = team2 if on_team1 else team1

            won = match['winner_id'] == own_team['team_id']

            elo_before = match['team1_elo_before'] if on_team1 else match['team2_elo_before']
            elo_after = match['team1_elo_after'] if on_team1 else match['team2_elo_after']
            elo_change = (elo_after or elo_before) - elo_before

            result_emoji = "🟢" if won else "🔴"
            result_text = "Victory" if won else "Defeat"
            elo_text = f"+{elo_change}" if elo_change >= 0 else str(elo_change)

            embed.add_field(
                name=f"{result_emoji} {result_text} vs {opponent['name']}",
                value=(
                    f"**Lobby Elo:** {elo_before} → {elo_after} ({elo_text})\n"
                    f"**Matchroom ID:** `#{match['match_id']}`"
                ),
                inline=False
            )

        embed.set_footer(text=f"Showing your last {len(matches)} matches | FACEIT Elo System")
        await interaction.response.send_message(embed=embed)

    async def _sync_level_role(self, level_cog, guild: Optional[discord.Guild], discord_id: int, new_elo: int):
        """Best-effort level role sync after an Elo change - never blocks the match flow if it fails."""
        if not level_cog or not guild:
            return
        member = guild.get_member(discord_id)
        if member is None:
            return
        try:
            await level_cog.sync_member_role(member, new_elo)
        except Exception as e:
            self.bot.logger.warning(f"MatchSystem: level role sync failed for {discord_id}: {e}")

    async def _get_team_name(self, team_id: int) -> str:
        """Helper to fetch the name of a temporary PUG team/lobby."""
        team = await self.bot.db.get_team_by_id(team_id)
        return team['name'] if team else "Unknown Team"


async def setup(bot):
    await bot.add_cog(MatchSystem(bot))