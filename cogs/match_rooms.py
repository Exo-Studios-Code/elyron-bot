"""
Match Rooms Cog
Handles everything related to a Matchroom's private Discord presence:

  1. Auto-creates a private category with ONE shared lobby text channel
     (used for the live Map Veto and later the Roblox private server link)
     plus ONE voice channel per team, the moment a match is drafted.
  2. Lets a Lobby Captain submit the Roblox PRIVATE SERVER invite link for
     Blox Strike (matches are played inside a Roblox private server, not on
     an external game server - someone has to host one and share the link).
  3. Automatically tears the channels down once the match is confirmed or
     cancelled (or after a 6-hour safety timeout), so the server doesn't
     fill up with stale channels.

This cog is intentionally decoupled from QueueSystem: QueueSystem looks it
up via `bot.get_cog('MatchRooms')` and calls `create_match_channels(...)`
right after drafting two teams, then runs the live Map Veto inside the
returned lobby channel. If this cog isn't loaded, or channel creation fails
(e.g. missing permissions), the match still proceeds via a DM-based Map
Veto flow as a fallback.
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
from typing import Dict, List, Optional

from utils.config import Config
from utils.embeds import EmbedBuilder

VALID_ROBLOX_LINK_PREFIXES = (
    "https://www.roblox.com/",
    "https://roblox.com/",
    "https://ro.blox.com/",
)


class MatchRooms(commands.Cog):
    """Cog managing per-match private channels and the Roblox server link handoff."""

    matchroom_group = app_commands.Group(
        name="matchroom",
        description="Manage your Matchroom's private channels and Roblox server link"
    )

    def __init__(self, bot):
        self.bot = bot
        self.cleanup_loop.start()

    def cog_unload(self):
        self.cleanup_loop.cancel()

    # =========================================================
    # CHANNEL CREATION (called by QueueSystem when a match is drafted)
    # =========================================================

    async def create_match_channels(
        self,
        match_id: int,
        team1: Dict,
        team2: Dict,
        roster1: List[Dict],
        roster2: List[Dict],
    ) -> Optional[Dict]:
        """
        Creates a private category containing:
          - ONE shared lobby text channel (visible to all 10 players) -
            used for the live Map Veto and later the Roblox server link
          - ONE voice channel for Team 1
          - ONE voice channel for Team 2

        Returns a dict of the created discord.abc.GuildChannel objects, or
        None if creation was skipped/failed (no guild available, or the bot
        is missing the Manage Channels permission).
        """
        guild = await self._get_match_guild()
        if guild is None:
            self.bot.logger.warning(
                f"MatchRooms: no guild available, skipping channel creation for Matchroom #{match_id}."
            )
            return None

        try:
            category = await guild.create_category(
                name=f"match-{match_id}",
                overwrites={guild.default_role: discord.PermissionOverwrite(view_channel=False)},
                reason=f"Blox Strike Matchroom #{match_id}"
            )

            lobby_overwrites = self._build_overwrites(guild, roster1 + roster2)
            lobby = await guild.create_text_channel(
                name=f"match-{match_id}-lobby",
                category=category,
                overwrites=lobby_overwrites,
                topic=(
                    f"Matchroom #{match_id} | {team1['name']} vs {team2['name']} | "
                    "Map Veto happens here, then post the Roblox private server link with /matchroom link"
                ),
                reason=f"Matchroom #{match_id} lobby"
            )

            team1_overwrites = self._build_overwrites(guild, roster1)
            team1_voice = await guild.create_voice_channel(
                name=f"🔊 {team1['name']}",
                category=category,
                overwrites=team1_overwrites,
                reason=f"Matchroom #{match_id} Team 1 voice"
            )

            team2_overwrites = self._build_overwrites(guild, roster2)
            team2_voice = await guild.create_voice_channel(
                name=f"🔊 {team2['name']}",
                category=category,
                overwrites=team2_overwrites,
                reason=f"Matchroom #{match_id} Team 2 voice"
            )

            await self.bot.db.save_match_channels(
                match_id, guild.id, category.id, lobby.id,
                team1_voice.id, team2_voice.id
            )

            created = {
                "category": category,
                "lobby": lobby,
                "team1_voice": team1_voice,
                "team2_voice": team2_voice,
            }

            await self._send_welcome_message(created, team1, team2, roster1, roster2, match_id)

            self.bot.logger.info(f"MatchRooms: created private channels for Matchroom #{match_id} in guild {guild.id}.")
            return created

        except discord.Forbidden:
            self.bot.logger.error(
                f"MatchRooms: missing permissions to create channels for Matchroom #{match_id}. "
                "Make sure the bot role has 'Manage Channels'."
            )
            return None
        except discord.HTTPException as e:
            self.bot.logger.error(f"MatchRooms: failed to create channels for Matchroom #{match_id}: {e}")
            return None

    async def _get_match_guild(self) -> Optional[discord.Guild]:
        """
        Picks the guild to create match channels in. Uses the guild tied to
        a deployed queue panel (since that's where players are queueing
        from); falls back to the bot's first guild for single-server setups.
        """
        queue_messages = await self.bot.db.get_queue_messages()
        for msg in queue_messages:
            guild = self.bot.get_guild(msg['guild_id'])
            if guild:
                return guild

        if self.bot.guilds:
            return self.bot.guilds[0]

        return None

    def _build_overwrites(self, guild: discord.Guild, roster: List[Dict]) -> Dict:
        """Builds permission overwrites so only the given roster (+ the bot) can see/use a channel."""
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, connect=True, manage_channels=True
            ),
        }
        for p in roster:
            member = guild.get_member(p['discord_id'])
            if member:
                overwrites[member] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    connect=True,
                    speak=True,
                )
        return overwrites

    @staticmethod
    def _slugify(text: str) -> str:
        """Turns a team name into a safe, lowercase, hyphenated channel-name fragment."""
        cleaned = "".join(c if c.isalnum() else "-" for c in text.lower())
        while "--" in cleaned:
            cleaned = cleaned.replace("--", "-")
        cleaned = cleaned.strip("-")[:20]
        return cleaned or "team"

    async def _send_welcome_message(
        self, created: Dict, team1: Dict, team2: Dict,
        roster1: List[Dict], roster2: List[Dict], match_id: int
    ):
        """Posts a welcome embed in the shared lobby channel."""
        all_mentions = " ".join(f"<@{p['discord_id']}>" for p in roster1 + roster2)

        lobby_embed = discord.Embed(
            title="🎮 Welcome To Your Matchroom!",
            description=(
                f"**{team1['name']}** vs **{team2['name']}**\n\n"
                "This match is played **in Blox Strike, inside a Roblox private server.** "
                "Someone needs to host one and share the invite link here."
            ),
            color=0xFF5500
        )
        lobby_embed.add_field(
            name="📋 Next Steps",
            value=(
                "1. **Map Veto happens right here** - your Captains will see ban buttons below.\n"
                "2. Once the map is set, one player creates a **Private Server** in Blox Strike on that map.\n"
                "3. A **Captain** submits the link here with `/matchroom link`.\n"
                "4. Everyone joins through the link posted in this channel. Use your team's voice "
                "channel in this category for comms.\n"
                "5. After the match, **both Captains** confirm the result: one runs `/match report`, "
                "the other runs `/match confirm`."
            ),
            inline=False
        )
        lobby_embed.add_field(
            name="🔗 Roblox Server Link",
            value="*Not submitted yet — waiting on a Captain to run `/matchroom link`.*",
            inline=False
        )
        lobby_embed.set_footer(text=f"Matchroom ID: #{match_id} | Blox Strike PUG System | This channel is deleted after the match")

        captain1_avatar = self._captain_avatar(roster1, team1['captain_id'])
        if captain1_avatar:
            lobby_embed.set_thumbnail(url=captain1_avatar)

        try:
            await created["lobby"].send(content=all_mentions, embed=lobby_embed)
        except discord.Forbidden:
            pass

    @staticmethod
    def _captain_avatar(roster: List[Dict], captain_id: int) -> Optional[str]:
        """Grabs the captain's linked Roblox avatar (if any) for a nice embed thumbnail."""
        for p in roster:
            if p['discord_id'] == captain_id:
                return p.get('roblox_avatar_url')
        return None

    # =========================================================
    # ROBLOX PRIVATE SERVER LINK SUBMISSION
    # =========================================================

    @matchroom_group.command(name="link", description="Submit the Roblox private server invite link for your match.")
    @app_commands.describe(
        match_id="Your Matchroom ID",
        link="The Roblox private server invite link (from Blox Strike's Private Servers menu)"
    )
    async def matchroom_link(self, interaction: discord.Interaction, match_id: int, link: str):
        await interaction.response.defer(ephemeral=True)

        match = await self.bot.db.get_match(match_id)
        if not match:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Match Not Found", f"No Matchroom with ID `#{match_id}` exists."),
                ephemeral=True
            )
            return

        team1 = await self.bot.db.get_team_by_id(match['team1_id'])
        team2 = await self.bot.db.get_team_by_id(match['team2_id'])

        is_captain = interaction.user.id in (team1['captain_id'], team2['captain_id'])
        if not is_captain:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Captains Only", "Only one of the two Lobby Captains can submit the server link."),
                ephemeral=True
            )
            return

        link = link.strip()
        if not link.startswith(VALID_ROBLOX_LINK_PREFIXES):
            await interaction.followup.send(
                embed=EmbedBuilder.warning(
                    "That Doesn't Look Like A Roblox Link",
                    "Make sure you copied the Private Server invite link from Roblox, then try again."
                ),
                ephemeral=True
            )
            return

        await self.bot.db.set_match_server_link(match_id, link)
        channels = await self.bot.db.get_match_channels(match_id)

        announce_embed = discord.Embed(
            title="🔗 Roblox Private Server Ready!",
            description=f"**{interaction.user.display_name}** submitted the server link. Join now!",
            color=0x50C878
        )
        announce_embed.add_field(
            name="🎮 Join The Match",
            value=f"[**Click here to join the Private Server**]({link})",
            inline=False
        )
        announce_embed.set_footer(text=f"Matchroom ID: #{match_id} | Blox Strike PUG System")

        posted_in_channel = False
        if channels:
            lobby_channel = self.bot.get_channel(channels['lobby_channel_id'])
            if lobby_channel:
                try:
                    await lobby_channel.send(embed=announce_embed)
                    posted_in_channel = True
                except discord.Forbidden:
                    pass

        if not posted_in_channel:
            # Fallback: DM both captains directly if the lobby channel is unavailable
            for cap_id in (team1['captain_id'], team2['captain_id']):
                try:
                    user = await self.bot.fetch_user(cap_id)
                    await user.send(embed=announce_embed)
                except discord.Forbidden:
                    pass

        await interaction.followup.send(
            embed=EmbedBuilder.success(
                "Link Submitted",
                "Posted in your Matchroom lobby channel." if posted_in_channel else "Sent directly to both Captains via DM."
            ),
            ephemeral=True
        )
        self.bot.logger.info(f"Matchroom #{match_id}: server link submitted by {interaction.user}.")

    # =========================================================
    # MANUAL CLOSE (Captains or Admins)
    # =========================================================

    @matchroom_group.command(name="close", description="Manually close and delete this match's private channels.")
    @app_commands.describe(match_id="The Matchroom ID to close")
    async def matchroom_close(self, interaction: discord.Interaction, match_id: int):
        await interaction.response.defer(ephemeral=True)

        match = await self.bot.db.get_match(match_id)
        if not match:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Match Not Found", f"No Matchroom with ID `#{match_id}` exists."),
                ephemeral=True
            )
            return

        is_admin = interaction.user.guild_permissions.administrator
        is_captain = False
        team1 = await self.bot.db.get_team_by_id(match['team1_id'])
        team2 = await self.bot.db.get_team_by_id(match['team2_id'])
        if team1 and team2:
            is_captain = interaction.user.id in (team1['captain_id'], team2['captain_id'])

        if not (is_admin or is_captain):
            await interaction.followup.send(
                embed=EmbedBuilder.error("Not Allowed", "Only the Lobby Captains or an Admin can close this Matchroom."),
                ephemeral=True
            )
            return

        closed = await self._close_match_channels(match_id)
        if closed:
            await interaction.followup.send(
                embed=EmbedBuilder.success("Matchroom Closed", f"Private channels for Matchroom #{match_id} have been removed."),
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                embed=EmbedBuilder.warning("Nothing To Close", "No active channels were found for that Matchroom."),
                ephemeral=True
            )

    # =========================================================
    # CHANNEL TEARDOWN (manual + automatic)
    # =========================================================

    async def _close_match_channels(self, match_id: int) -> bool:
        """Deletes all Discord channels tied to a Matchroom and clears the DB record."""
        record = await self.bot.db.get_match_channels(match_id)
        if not record:
            return False

        guild = self.bot.get_guild(record['guild_id'])

        channel_ids = [
            record.get('lobby_channel_id'),
            record.get('team1_voice_id'),
            record.get('team2_voice_id'),
        ]

        for cid in channel_ids:
            if not cid:
                continue
            channel = (guild.get_channel(cid) if guild else None) or self.bot.get_channel(cid)
            if channel:
                try:
                    await channel.delete(reason=f"Matchroom #{match_id} closed")
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    pass

        if guild and record.get('category_id'):
            category = guild.get_channel(record['category_id'])
            if category:
                try:
                    await category.delete(reason=f"Matchroom #{match_id} closed")
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    pass

        await self.bot.db.delete_match_channels_record(match_id)
        return True

    @tasks.loop(minutes=5)
    async def cleanup_loop(self):
        """Automatically removes channels for matches that are confirmed, cancelled, or stale."""
        try:
            to_clean = await self.bot.db.get_finished_match_channels()
            for record in to_clean:
                await self._close_match_channels(record['match_id'])
                self.bot.logger.info(f"MatchRooms: auto-cleaned channels for finished Matchroom #{record['match_id']}.")
        except Exception as e:
            self.bot.logger.error(f"MatchRooms cleanup loop error: {e}")

    @cleanup_loop.before_loop
    async def before_cleanup_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(MatchRooms(bot))
