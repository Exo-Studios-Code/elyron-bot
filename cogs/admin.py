"""
Admin Cog
Administrative commands for league management, PUG moderation, and season resets.
Updated for Slash Commands and the FACEIT-style Player Matchmaking system.
"""

import discord
from discord import app_commands
from discord.ext import commands
import json
from datetime import datetime
from typing import Optional

from utils.config import Config
from utils.embeds import EmbedBuilder

def is_admin_interaction():
    """Custom check to ensure the user has admin permissions."""
    async def predicate(interaction: discord.Interaction) -> bool:
        # Check if user is a server administrator
        if interaction.user.guild_permissions.administrator:
            return True
            
        # Check if user has one of the configured admin roles
        if hasattr(Config, 'ADMIN_ROLE_IDS') and Config.ADMIN_ROLE_IDS:
            user_role_ids = [role.id for role in interaction.user.roles]
            if any(role_id in Config.ADMIN_ROLE_IDS for role_id in user_role_ids):
                return True
                
        return False
    return app_commands.check(predicate)


class Admin(commands.Cog):
    """Administrative commands for bot and league management."""
    
    # Main Admin Command Group
    admin_group = app_commands.Group(
        name="admin", 
        description="Administrative commands for league and PUG management",
        default_permissions=discord.Permissions(administrator=True)
    )
    
    def __init__(self, bot):
        self.bot = bot
        
    @admin_group.command(name="season_info", description="View statistics and dates for the current season.")
    @is_admin_interaction()
    async def admin_season_info(self, interaction: discord.Interaction):
        """Displays current season statistics[cite: 12]."""
        await interaction.response.defer(ephemeral=True)
        
        season_id = await self.bot.db.get_active_season()
        
        rs = await self.bot.db._exec("SELECT * FROM seasons WHERE season_id = ?", [season_id])
        season = self.bot.db._row(rs)
        
        if not season:
            await interaction.followup.send("❌ No active season found in the database.", ephemeral=True)
            return
            
        start_date = datetime.fromisoformat(season['start_date'])
        end_date = datetime.fromisoformat(season['end_date'])
        
        embed = discord.Embed(
            title="📅 Current League Season",
            color=Config.COLOR_INFO
        )
        
        embed.add_field(name="Season ID", value=str(season_id), inline=True)
        embed.add_field(name="Status", value="Active" if season['is_active'] else "Inactive", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        
        embed.add_field(name="Started", value=start_date.strftime('%Y-%m-%d'), inline=True)
        embed.add_field(name="Ends", value=end_date.strftime('%Y-%m-%d'), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        
        rs2 = await self.bot.db._exec("SELECT COUNT(*) FROM players WHERE season_id = ?", [season_id])
        player_count = self.bot.db._scalar(rs2) or 0
        
        rs3 = await self.bot.db._exec("SELECT COUNT(*) FROM matches WHERE status = 'confirmed'")
        match_count = self.bot.db._scalar(rs3) or 0
        
        embed.add_field(name="Registered Players", value=str(player_count), inline=True)
        embed.add_field(name="Matchrooms Played", value=str(match_count), inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @admin_group.command(name="season_reset", description="End the current season, archive data, and reset all player ELOs.")
    @app_commands.describe(confirm="You MUST set this to True to execute the reset.")
    @is_admin_interaction()
    async def admin_season_reset(self, interaction: discord.Interaction, confirm: bool):
        """Archives the current season and starts a fresh one[cite: 12]."""
        await interaction.response.defer(ephemeral=True)
        
        if not confirm:
            await interaction.followup.send(
                embed=EmbedBuilder.warning(
                    "Reset Cancelled",
                    "You must select `True` for the confirm parameter to wipe the season."
                ),
                ephemeral=True
            )
            return
            
        season_id = await self.bot.db.get_active_season()
        
        # Archive current season data (now focusing on Top Players instead of teams)
        await self._archive_season_data(season_id)
        
        # Create new season (Make sure this DB function resets all ELOs to 1000)
        new_season_id = await self.bot.db.create_new_season()
        
        # Also clear any stuck queues
        await self._clear_all_queues()
        
        # Everyone's ELO just reset to the starting value - resync level roles for the whole server
        level_cog = self.bot.get_cog('LevelSystem')
        if level_cog and interaction.guild:
            await level_cog.sync_all_members(interaction.guild)
        
        embed = EmbedBuilder.success(
            "✅ Season Reset Complete",
            f"Season **{season_id}** has been officially archived.\n"
            f"Season **{new_season_id}** has started! All player ELOs have been reset to {Config.STARTING_ELO}."
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        self.bot.logger.info(f"Season reset initiated by {interaction.user}: {season_id} -> {new_season_id}")
            
    async def _archive_season_data(self, season_id: int):
        """Archive season data to the season_archives table."""
        top_players = await self.bot.db.get_top_players(100)
        await self.bot.db._exec(
            "INSERT INTO season_archives (season_id, data_type, data_json) VALUES (?, 'top_players', ?)",
            [season_id, json.dumps(top_players)],
        )

    @admin_group.command(name="set_elo", description="Manually override a specific player's ELO.")
    @app_commands.describe(member="The player to modify", new_elo="The exact ELO value to assign")
    @is_admin_interaction()
    async def admin_set_elo(self, interaction: discord.Interaction, member: discord.Member, new_elo: int):
        await interaction.response.defer(ephemeral=True)
        
        if new_elo < 0 or new_elo > 4000:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Invalid ELO", "ELO must be between 0 and 4000."),
                ephemeral=True
            )
            return
            
        player = await self.bot.db.get_player(member.id)
        
        if not player:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Player Not Found", f"{member.mention} is not registered in the league."),
                ephemeral=True
            )
            return
            
        old_elo = player['elo']
        await self.bot.db._exec(
            "UPDATE players SET elo = ? WHERE discord_id = ?",
            [new_elo, member.id],
        )
        
        level_cog = self.bot.get_cog('LevelSystem')
        if level_cog and interaction.guild:
            await level_cog.sync_member_role(member, new_elo)
        
        embed = EmbedBuilder.success(
            "Player ELO Updated",
            f"**{member.display_name}** ELO changed: `{old_elo}` ➔ `{new_elo}`"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        self.bot.logger.warning(f"Player ELO force updated by {interaction.user}: {member.display_name} {old_elo} -> {new_elo}")

    @admin_group.command(name="cancel_match", description="Forcibly cancel an active or bugged Matchroom.")
    @app_commands.describe(match_id="The ID of the Matchroom to cancel")
    @is_admin_interaction()
    async def admin_cancel_match(self, interaction: discord.Interaction, match_id: int):
        """Cancels an ongoing Matchroom if a player fails to join or a server crashes."""
        await interaction.response.defer(ephemeral=True)
        
        match = await self.bot.db.get_match(match_id)
        
        if not match:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Match Not Found", f"No Matchroom with ID `#{match_id}` exists."),
                ephemeral=True
            )
            return
            
        if match['status'] == 'confirmed':
            await interaction.followup.send(
                embed=EmbedBuilder.error("Cannot Cancel", "This match has already been confirmed and ELO was distributed."),
                ephemeral=True
            )
            return
            
        await self.bot.db._exec(
            "UPDATE matches SET status = 'cancelled' WHERE match_id = ?",
            [match_id],
        )
        
        embed = EmbedBuilder.success(
            "Match Cancelled",
            f"Matchroom `#{match_id}` has been successfully cancelled and voided."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        self.bot.logger.warning(f"Matchroom #{match_id} forcibly cancelled by {interaction.user}.")

    @admin_group.command(name="clear_queue", description="Empty the entire matchmaking queue (Solo & Party).")
    @is_admin_interaction()
    async def admin_clear_queue(self, interaction: discord.Interaction):
        """Clear the entire matchmaking queue[cite: 12]."""
        await interaction.response.defer(ephemeral=True)
        
        await self._clear_all_queues()
        
        embed = EmbedBuilder.success(
            "Queues Cleared",
            "All players and parties have been successfully removed from the matchmaking queues."
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        self.bot.logger.warning(f"Matchmaking queues forcefully cleared by {interaction.user}")
        
    async def _clear_all_queues(self):
        """Helper method to clear the matchmaking queue table and any active host info."""
        try:
            await self.bot.db._exec("DELETE FROM queue_players")
        except Exception as e:
            self.bot.logger.error(f"Error clearing queues: {e}")
        try:
            await self.bot.db.clear_queue_host_info()
        except Exception as e:
            self.bot.logger.error(f"Error clearing queue host info: {e}")

    @admin_group.command(name="dispute", description="View details of a disputed match and override the result.")
    @app_commands.describe(
        match_id="The Matchroom ID to inspect",
        override_winner="Set to Team 1 or Team 2 to force a winner (leave blank to just view)"
    )
    @app_commands.choices(override_winner=[
        app_commands.Choice(name="Team 1 Wins", value="team1"),
        app_commands.Choice(name="Team 2 Wins", value="team2"),
        app_commands.Choice(name="Cancel Match (no ELO change)", value="cancel"),
    ])
    @is_admin_interaction()
    async def admin_dispute(
        self,
        interaction: discord.Interaction,
        match_id: int,
        override_winner: Optional[app_commands.Choice[str]] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        match = await self.bot.db.get_match(match_id)
        if not match:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Not Found", f"No Matchroom with ID `#{match_id}`."),
                ephemeral=True
            )
            return

        team1 = await self.bot.db.get_team_by_id(match['team1_id'])
        team2 = await self.bot.db.get_team_by_id(match['team2_id'])

        # ── VIEW ONLY (no override requested) ──────────────────────────
        if override_winner is None:
            reported_by_name = "Nobody yet"
            if match.get('reported_by'):
                try:
                    u = await self.bot.fetch_user(match['reported_by'])
                    reported_by_name = f"{u.display_name} ({u.id})"
                except Exception:
                    reported_by_name = str(match['reported_by'])

            current_winner = "Not reported"
            if match.get('winner_id'):
                wt = await self.bot.db.get_team_by_id(match['winner_id'])
                current_winner = wt['name'] if wt else str(match['winner_id'])

            dispute = await self.bot.db.get_dispute(match_id)

            embed = discord.Embed(
                title=f"⚖️ Dispute View — Matchroom #{match_id}",
                color=0xFFA500
            )
            embed.add_field(name="Status", value=match['status'].upper(), inline=True)
            embed.add_field(name="Map", value=match.get('map_played') or 'Unknown', inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)
            embed.add_field(name="🛡️ Team 1", value=team1['name'] if team1 else "?", inline=True)
            embed.add_field(name="🛡️ Team 2", value=team2['name'] if team2 else "?", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)
            embed.add_field(
                name="📋 Reported Result",
                value=f"**Reported winner:** {current_winner}\n**Reported by:** {reported_by_name}",
                inline=False
            )
            if dispute:
                embed.add_field(
                    name="📨 Dispute",
                    value=(
                        f"**Opened by:** <@{dispute['opened_by']}>\n"
                        f"**Reason:** {dispute.get('reason') or 'No reason given'}\n"
                        f"**Status:** {'✅ Resolved' if dispute.get('resolved_by') else '🔴 Open'}"
                    ),
                    inline=False
                )
            embed.add_field(
                name="🔧 To Override",
                value="Re-run this command with the `override_winner` parameter set.",
                inline=False
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # ── OVERRIDE ────────────────────────────────────────────────────
        if match['status'] == 'confirmed' and not match.get('winner_id'):
            await interaction.followup.send(
                embed=EmbedBuilder.error("Already Confirmed", "This match is already confirmed with no dispute."),
                ephemeral=True
            )
            return

        choice = override_winner.value

        if choice == "cancel":
            await self.bot.db._exec(
                "UPDATE matches SET status = 'cancelled' WHERE match_id = ?", [match_id]
            )
            await self.bot.db.resolve_dispute(match_id, interaction.user.id, "Admin cancelled the match — no ELO change.")
            embed = EmbedBuilder.success(
                "Match Cancelled",
                f"Matchroom `#{match_id}` has been cancelled. No ELO was distributed."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            self.bot.logger.warning(f"Admin {interaction.user} cancelled match #{match_id} via dispute.")
            return

        # Determine winning and losing team
        winner_team = team1 if choice == "team1" else team2
        loser_team  = team2 if choice == "team1" else team1

        from utils.elo import ELOCalculator
        new_winner_elo, new_loser_elo, elo_change = ELOCalculator.calculate_match_elo(
            winner_team['elo'], loser_team['elo']
        )

        team1_elo_after = new_winner_elo if choice == "team1" else new_loser_elo
        team2_elo_after = new_loser_elo  if choice == "team1" else new_winner_elo

        await self.bot.db.admin_override_match_winner(
            match_id, winner_team['team_id'],
            interaction.user.id,
            team1_elo_after, team2_elo_after, elo_change
        )
        await self.bot.db.update_team_stats(winner_team['team_id'], new_winner_elo, True)
        await self.bot.db.update_team_stats(loser_team['team_id'],  new_loser_elo,  False)

        # Update individual player Elos
        from utils.elo import ELOCalculator as _ELO
        winner_members = await self.bot.db.get_team_members(winner_team['team_id'])
        loser_members  = await self.bot.db.get_team_members(loser_team['team_id'])
        level_cog = self.bot.get_cog('LevelSystem')

        for m in winner_members:
            new_elo, _, _ = _ELO.calculate_match_elo(m['elo'], loser_team['elo'])
            await self.bot.db.update_player_stats(m['discord_id'], new_elo, True)
            if level_cog and interaction.guild:
                member_obj = interaction.guild.get_member(m['discord_id'])
                if member_obj:
                    await level_cog.sync_member_role(member_obj, new_elo)

        for m in loser_members:
            _, new_elo, _ = _ELO.calculate_match_elo(winner_team['elo'], m['elo'])
            await self.bot.db.update_player_stats(m['discord_id'], new_elo, False)
            if level_cog and interaction.guild:
                member_obj = interaction.guild.get_member(m['discord_id'])
                if member_obj:
                    await level_cog.sync_member_role(member_obj, new_elo)

        await self.bot.db.resolve_dispute(
            match_id, interaction.user.id,
            f"Admin override: {winner_team['name']} declared winner."
        )

        embed = EmbedBuilder.success(
            "Match Overridden",
            f"Matchroom `#{match_id}` result overridden by admin.\n"
            f"**Winner: {winner_team['name']}** (+{elo_change} ELO)\n"
            f"**Loser: {loser_team['name']}** (-{elo_change} ELO)\n\n"
            "Individual player Elos and level roles have been updated."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        self.bot.logger.warning(
            f"Admin {interaction.user} overrode match #{match_id}: winner={winner_team['name']}"
        )

        # Notify both captains
        for cap_id in [team1['captain_id'], team2['captain_id']]:
            try:
                cap = await self.bot.fetch_user(cap_id)
                await cap.send(
                    embed=discord.Embed(
                        title=f"⚖️ Matchroom #{match_id} — Admin Override",
                        description=(
                            f"An administrator has reviewed and overridden the result of this match.\n\n"
                            f"**Declared winner:** {winner_team['name']}\n"
                            f"ELO has been updated accordingly."
                        ),
                        color=0xFFA500
                    )
                )
            except discord.Forbidden:
                pass

    @admin_group.command(name="disputes", description="List all open (unresolved) match disputes.")
    @is_admin_interaction()
    async def admin_disputes(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        open_disputes = await self.bot.db.get_all_open_disputes()

        if not open_disputes:
            await interaction.followup.send(
                embed=EmbedBuilder.success("No Open Disputes", "There are no unresolved match disputes."),
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"⚖️ Open Disputes ({len(open_disputes)})",
            color=0xFF5500
        )

        for d in open_disputes[:10]:  # cap at 10 to avoid embed length limit
            embed.add_field(
                name=f"Matchroom #{d['match_id']} — {d['status'].upper()}",
                value=(
                    f"**Opened by:** <@{d['opened_by']}>\n"
                    f"**Reason:** {d.get('reason') or 'No reason given'}\n"
                    f"**Map:** {d.get('map_played') or 'Unknown'}\n"
                    f"Use `/admin dispute match_id:{d['match_id']}` to view & resolve."
                ),
                inline=False
            )

        if len(open_disputes) > 10:
            embed.set_footer(text=f"Showing 10 of {len(open_disputes)} open disputes.")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @admin_group.command(name="clear_cooldown", description="Remove the queue leave cooldown from a player.")
    @app_commands.describe(member="The player whose cooldown to clear")
    @is_admin_interaction()
    async def admin_clear_cooldown(self, interaction: discord.Interaction, member: discord.Member):
        """Lets an admin forgive a player's queue leave cooldown (e.g. if they disconnected)."""
        await interaction.response.defer(ephemeral=True)
        remaining = await self.bot.db.get_queue_cooldown_remaining(member.id)
        if remaining == 0:
            await interaction.followup.send(
                embed=EmbedBuilder.info("No Cooldown", f"{member.mention} has no active queue cooldown."),
                ephemeral=True
            )
            return
        await self.bot.db.clear_queue_cooldown(member.id)
        await interaction.followup.send(
            embed=EmbedBuilder.success("Cooldown Cleared", f"Queue cooldown removed for {member.mention}."),
            ephemeral=True
        )

    @admin_group.command(name="sync_levels", description="Create/update all 11 FACEIT-style level roles and resync every registered player.")
    @is_admin_interaction()
    async def admin_sync_levels(self, interaction: discord.Interaction):
        """Bulk-creates the level roles and reassigns them across the whole server."""
        await interaction.response.defer(ephemeral=True)

        level_cog = self.bot.get_cog('LevelSystem')
        if not level_cog:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Unavailable", "The LevelSystem cog isn't loaded."),
                ephemeral=True
            )
            return

        synced, skipped = await level_cog.sync_all_members(interaction.guild)

        embed = EmbedBuilder.success(
            "Level Roles Synced",
            f"Created/verified all 11 level roles.\n**{synced}** members synced, **{skipped}** skipped (registered but not currently in this server)."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        self.bot.logger.info(f"Level role sync run by {interaction.user}: {synced} synced, {skipped} skipped.")

    @admin_group.command(name="announce", description="Broadcast an official message to a specific channel.")
    @app_commands.describe(channel="The channel to send the announcement to", message="The announcement text")
    @is_admin_interaction()
    async def admin_announce(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        """
        Broadcast a message to a channel. 
        Replaces the old mass-DM broadcast to prevent Discord rate-limiting[cite: 12].
        """
        await interaction.response.defer(ephemeral=True)
        
        embed = discord.Embed(
            title="📢 Official League Announcement",
            description=message,
            color=Config.COLOR_INFO
        )
        embed.set_footer(text="CS2 League Administration")
        
        try:
            await channel.send(embed=embed)
            await interaction.followup.send(
                embed=EmbedBuilder.success("Announcement Sent", f"Your message has been posted in {channel.mention}."),
                ephemeral=True
            )
            self.bot.logger.info(f"Announcement sent to #{channel.name} by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Missing Permissions", "I do not have permission to send messages in that channel."),
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(Admin(bot))