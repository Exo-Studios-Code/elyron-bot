"""
Queue System Cog
Handles FACEIT-style matchmaking including Solo, Duo, and Party (up to 5) queues.
Features intelligent Snake Draft balancing, Party preservation, Map Vetoes,
and a mandatory Roblox account link gate (since matches are played in a Roblox game).
All text and UI elements are in English.
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Button, View
from discord import ButtonStyle
import asyncio
import random
from typing import List, Dict, Optional
from datetime import datetime
from utils.config import Config
from utils.embeds import EmbedBuilder
from utils.elo import ELOCalculator
from utils import levels as level_utils
from utils.roblox_api import RobloxAPI


# =====================================================================
# SHARED HELPERS (used by both slash commands and persistent UI buttons)
# =====================================================================

def build_registration_required_embed(missing_mentions: Optional[List[str]] = None) -> discord.Embed:
    """Premium error embed shown when someone tries to queue without a linked Roblox account."""
    embed = discord.Embed(
        title="🔒 ｜ Roblox Account Required",
        description=(
            "All Matchrooms are played **in-game on Roblox**, so every player "
            "needs a linked Roblox account before joining the queue."
        ),
        color=0xDC143C
    )

    if missing_mentions:
        embed.add_field(
            name="⚠️ Not Yet Registered",
            value="\n".join(missing_mentions),
            inline=False
        )

    embed.add_field(
        name="✅ How To Fix This",
        value="Run **`/register roblox_username:<YourRobloxName>`** — takes 5 seconds!",
        inline=False
    )
    embed.set_footer(text="CS2 PUG League | Roblox Integration")
    return embed


def build_progress_bar(filled: int, total: int, filled_icon: str = "▰", empty_icon: str = "▱") -> str:
    """Generates a clean visual progress bar e.g. ▰▰▰▰▰▰▱▱▱▱"""
    filled = max(0, min(filled, total))
    return f"{filled_icon * filled}{empty_icon * (total - filled)}"


# =====================================================================
# MAP VETO VIEW
# =====================================================================

class MapVetoView(View):
    """Interactive map veto system for BO1 matches (FACEIT style)."""
    
    def __init__(self, match_id: int, team1: dict, team2: dict, bot):
        super().__init__(timeout=Config.MAP_VETO_TIMEOUT)
        self.match_id = match_id
        self.team1 = team1
        self.team2 = team2
        self.bot = bot
        
        self.available_maps = Config.CS2_MAPS.copy()
        self.current_banner = team1['team_id']  # Team 1's Captain bans first
        self.ban_count = {team1['team_id']: 0, team2['team_id']: 0}
        self.veto_order = 0
        
        self._update_buttons()
        
    def _update_buttons(self):
        """Generates buttons for the available maps."""
        self.clear_items()
        
        for map_name in self.available_maps:
            button = Button(
                label=map_name,
                style=ButtonStyle.danger,
                custom_id=f"ban_{map_name}"
            )
            button.callback = self._make_ban_callback(map_name)
            self.add_item(button)
            
    def _make_ban_callback(self, map_name: str):
        """Creates the callback for each specific map button."""
        async def callback(interaction: discord.Interaction):
            # Check if user is one of the designated captains
            is_t1_captain = (interaction.user.id == self.team1['captain_id'])
            is_t2_captain = (interaction.user.id == self.team2['captain_id'])
            
            if not is_t1_captain and not is_t2_captain:
                await interaction.response.send_message(
                    "❌ Only the designated Lobby Captains can ban maps!",
                    ephemeral=True
                )
                return
                
            user_team_id = self.team1['team_id'] if is_t1_captain else self.team2['team_id']
            
            # Check if it's currently this captain's turn to ban
            if user_team_id != self.current_banner:
                active_team_name = self.team1['name'] if self.current_banner == self.team1['team_id'] else self.team2['name']
                await interaction.response.send_message(
                    f"❌ Please wait! It is **{active_team_name}**'s turn to ban.",
                    ephemeral=True
                )
                return
                
            # Process the ban
            self.veto_order += 1
            await self.bot.db.save_map_ban(
                self.match_id,
                user_team_id,
                map_name,
                self.veto_order
            )
            
            self.available_maps.remove(map_name)
            self.ban_count[user_team_id] += 1
            
            # If only 1 map remains, the veto is complete
            if len(self.available_maps) == 1:
                final_map = self.available_maps[0]
                await self.bot.db.set_match_map(self.match_id, final_map)
                
                vetos = await self.bot.db.get_match_vetos(self.match_id)
                embed = self._create_final_embed(final_map, vetos)
                
                await interaction.response.edit_message(embed=embed, view=None)
                self.stop()
                await self._notify_captains_veto_done(final_map)
                return
                
            # Switch the turn to the other captain
            self.current_banner = (self.team2['team_id'] if self.current_banner == self.team1['team_id']
                                  else self.team1['team_id'])
            
            self._update_buttons()
            embed = await self._create_veto_embed()
            await interaction.response.edit_message(embed=embed, view=self)
            
        return callback
        
    async def _create_veto_embed(self) -> discord.Embed:
        """Builds the active Map Veto embed."""
        embed = discord.Embed(
            title="🗺️ MAP VETO - BO1",
            description="**Lobby Captains:** click the buttons below to ban maps. Everyone else can watch live.",
            color=0xFF6B00  # FACEIT Orange
        )
        
        current_team = self.team1 if self.current_banner == self.team1['team_id'] else self.team2
        embed.add_field(
            name="⏰ Current Turn",
            value=f"**{current_team['name']}** is banning...",
            inline=False
        )
        
        t1_bans = self.ban_count[self.team1['team_id']]
        t2_bans = self.ban_count[self.team2['team_id']]
        
        progress_bar = (
            f"**{self.team1['name']}:** {'🚫' * t1_bans}{'⬜' * (3 - t1_bans)}\n"
            f"**{self.team2['name']}:** {'🚫' * t2_bans}{'⬜' * (3 - t2_bans)}"
        )
        
        embed.add_field(name="📊 Ban Progress", value=progress_bar, inline=False)
        
        if self.available_maps:
            embed.add_field(
                name=f"🗺️ Available Maps ({len(self.available_maps)})",
                value=" • ".join(self.available_maps),
                inline=False
            )
            
        embed.set_footer(text=f"Matchroom ID: #{self.match_id} | FACEIT Veto System")
        return embed
        
    def _create_final_embed(self, final_map: str, vetos: List[Dict]) -> discord.Embed:
        """Builds the embed shown when Map Veto is finished."""
        embed = discord.Embed(
            title="✅ MAP VETO COMPLETE!",
            description=f"## 🗺️ **{final_map}**",
            color=0x00FF00
        )
        
        veto_summary = []
        for veto in vetos:
            team = self.team1 if veto['team_id'] == self.team1['team_id'] else self.team2
            veto_summary.append(f"🚫 **{team['name']}** banned **{veto['map_name']}**")
            
        embed.add_field(name="📋 Veto Summary", value="\n".join(veto_summary), inline=False)
        
        embed.add_field(
            name="📍 Next Steps",
            value=(
                f"1. Create a **Private Server** in Blox Strike on **{final_map}**\n"
                "2. A Captain submits the invite link here with `/matchroom link`\n"
                "3. Everyone joins through that link and plays the match!\n"
                "4. **Both Captains** confirm the result: one runs `/match report`, the other `/match confirm`"
            ),
            inline=False
        )
        
        embed.set_footer(text=f"Matchroom ID: #{self.match_id}")
        return embed

    async def _notify_captains_veto_done(self, final_map: str):
        """Sends a courtesy direct message to captains once veto finishes (the live result is also visible in the Matchroom channel, if one was created)."""
        embed = discord.Embed(
            title="🎮 Veto Complete!",
            description=f"The map selected is **{final_map}**. Get your Private Server set up and invite your players.",
            color=0x00FF00
        )
        for cap_id in [self.team1['captain_id'], self.team2['captain_id']]:
            try:
                user = await self.bot.fetch_user(cap_id)
                await user.send(embed=embed)
            except discord.Forbidden:
                pass

    async def on_timeout(self):
        """If a captain AFKs, pick a random remaining map."""
        if len(self.available_maps) > 1:
            final_map = random.choice(self.available_maps)
            await self.bot.db.set_match_map(self.match_id, final_map)
            # You would ideally also update the message here


# =====================================================================
# PERSISTENT QUEUE UI (buttons delegate to the cog's shared logic)
# =====================================================================

class QueueView(View):
    """Persistent UI View for the Queue message."""
    
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        
    @discord.ui.button(label="➕ Join Queue (Solo/Party)", style=discord.ButtonStyle.success, custom_id="queue_join")
    async def join_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        cog: Optional["QueueSystem"] = self.bot.get_cog('QueueSystem')
        if cog:
            await cog.handle_join(interaction)

    @discord.ui.button(label="➖ Leave Queue", style=discord.ButtonStyle.danger, custom_id="queue_leave")
    async def leave_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        cog: Optional["QueueSystem"] = self.bot.get_cog('QueueSystem')
        if cog:
            await cog.handle_leave(interaction)


# =====================================================================
# MAIN COG
# =====================================================================

class QueueSystem(commands.Cog):
    """
    Cog handling Roblox account registration, the FACEIT-style player
    matchmaking queue, Matchroom generation, and Party management.
    """
    
    queue_group = app_commands.Group(name="queue", description="Join, leave, or check the matchmaking queue")
    party_group = app_commands.Group(name="party", description="Create and manage your FACEIT-style party")
    
    def __init__(self, bot):
        self.bot = bot
        self.matchmaking_lock = asyncio.Lock()
        self.bot.add_view(QueueView(self.bot))
        self.matchmaking_loop.start()
        
    def cog_unload(self):
        self.matchmaking_loop.cancel()

    # =========================================================
    # ROBLOX REGISTRATION
    # =========================================================

    @app_commands.command(name="register", description="Link your Roblox account so you can join the matchmaking queue.")
    @app_commands.describe(roblox_username="Your exact Roblox username (not your display name)")
    async def register(self, interaction: discord.Interaction, roblox_username: str):
        await interaction.response.defer(ephemeral=True)

        await self.bot.db.create_or_get_player(interaction.user.id, str(interaction.user))

        cleaned = roblox_username.strip()
        if not (3 <= len(cleaned) <= 20):
            await interaction.followup.send(
                embed=EmbedBuilder.error(
                    "Invalid Username",
                    "Roblox usernames are between 3 and 20 characters. Double-check and try again."
                ),
                ephemeral=True
            )
            return

        result = await RobloxAPI.resolve_username(cleaned)

        await self.bot.db.set_roblox_account(
            interaction.user.id,
            result["display_username"],
            result["roblox_user_id"],
            result["avatar_url"]
        )

        # Give the player their FACEIT-style level role right away (based on
        # their current Elo - starting Elo for brand new players).
        level_cog = self.bot.get_cog('LevelSystem')
        if level_cog and interaction.guild:
            player_record = await self.bot.db.get_player(interaction.user.id)
            await level_cog.sync_member_role(interaction.user, player_record['elo'])

        embed = discord.Embed(
            title="✅ ｜ Roblox Account Linked",
            description=f"You're all set, **{interaction.user.display_name}**! You can now join the queue.",
            color=0x50C878
        )
        embed.add_field(name="🎮 Roblox Username", value=f"`{result['display_username']}`", inline=True)

        if result["roblox_user_id"]:
            embed.add_field(name="🆔 Roblox ID", value=f"`{result['roblox_user_id']}`", inline=True)

        if result["avatar_url"]:
            embed.set_thumbnail(url=result["avatar_url"])

        if not result["verified"]:
            embed.add_field(
                name="⚠️ Heads Up",
                value=(
                    "I couldn't verify this username against Roblox right now (it may not exist, "
                    "or Roblox's API was briefly unreachable). I saved it as entered — "
                    "run `/register` again if you made a typo."
                ),
                inline=False
            )

        embed.add_field(
            name="🚀 Next Step",
            value="Hit **➕ Join Queue** in the matchmaking channel, or run `/queue join`.",
            inline=False
        )
        embed.set_footer(text="CS2 PUG League | Roblox Integration")

        await interaction.followup.send(embed=embed, ephemeral=True)
        self.bot.logger.info(
            f"{interaction.user} linked Roblox account '{result['display_username']}' "
            f"(verified={result['verified']})"
        )

    # =========================================================
    # SHARED JOIN / LEAVE LOGIC (used by both buttons and slash commands)
    # =========================================================

    async def handle_join(self, interaction: discord.Interaction):
        """Core join logic shared by the QueueView button and /queue join."""
        user = interaction.user

        player = await self.bot.db.get_player(user.id)
        if not player:
            await self.bot.db.create_or_get_player(user.id, str(user))
            player = await self.bot.db.get_player(user.id)

        if await self.bot.db.is_player_in_active_match(user.id):
            await interaction.followup.send(
                embed=EmbedBuilder.error("Already In A Match", "You cannot queue while in an active Matchroom!"),
                ephemeral=True
            )
            return

        party = await self.bot.db.get_player_party(user.id)

        if party:
            if party['leader_id'] != user.id:
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Not The Leader", "Only the Party Leader can queue up the whole party."),
                    ephemeral=True
                )
                return

            if await self.bot.db.is_party_in_queue(party['party_id']):
                await interaction.followup.send(
                    embed=EmbedBuilder.warning("Already Queued", "Your party is already in the matchmaking queue!"),
                    ephemeral=True
                )
                return

            party_members = await self.bot.db.get_party_members(party['party_id'])

            # Registration gate - ALL party members need a linked Roblox account
            unregistered = [m for m in party_members if not m.get('roblox_username')]
            if unregistered:
                mentions = [f"• <@{m['discord_id']}>" for m in unregistered]
                await interaction.followup.send(embed=build_registration_required_embed(mentions), ephemeral=True)
                return

            for member in party_members:
                if await self.bot.db.is_player_in_active_match(member['discord_id']):
                    await interaction.followup.send(
                        embed=EmbedBuilder.error(
                            "Party Member Busy",
                            f"Cannot queue. <@{member['discord_id']}> is currently in an active match."
                        ),
                        ephemeral=True
                    )
                    return

            await self.bot.db.add_party_to_queue(party['party_id'])
            await interaction.followup.send(
                embed=EmbedBuilder.success("Party Queued", f"Your party of **{len(party_members)}** joined the queue!"),
                ephemeral=True
            )

        else:
            # Registration gate - solo player needs a linked Roblox account
            if not player.get('roblox_username'):
                await interaction.followup.send(embed=build_registration_required_embed(), ephemeral=True)
                return

            if await self.bot.db.is_player_in_queue(user.id):
                await interaction.followup.send(
                    embed=EmbedBuilder.warning("Already Queued", "You are already in the matchmaking queue!"),
                    ephemeral=True
                )
                return

            # Anti-abuse cooldown check
            cooldown_secs = await self.bot.db.get_queue_cooldown_remaining(user.id)
            if cooldown_secs > 0:
                mins, secs = divmod(cooldown_secs, 60)
                await interaction.followup.send(
                    embed=EmbedBuilder.warning(
                        "Queue Cooldown",
                        f"You left the queue recently. Please wait **{mins}m {secs}s** before re-joining.\n"
                        "*This cooldown prevents queue abuse.*"
                    ),
                    ephemeral=True
                )
                return

            await self.bot.db.add_solo_player_to_queue(user.id, player['elo'])
            await interaction.followup.send(
                embed=EmbedBuilder.success("Queued Up", "You have joined the matchmaking queue as Solo!"),
                ephemeral=True
            )

        await self.update_all_queue_messages()
        async with self.matchmaking_lock:
            await self._try_create_matches()

    async def handle_leave(self, interaction: discord.Interaction):
        """Core leave logic shared by the QueueView button and /queue leave."""
        user = interaction.user
        party = await self.bot.db.get_player_party(user.id)

        if party:
            if party['leader_id'] != user.id:
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Not The Leader", "Only the Party Leader can remove the party from the queue."),
                    ephemeral=True
                )
                return

            if not await self.bot.db.is_party_in_queue(party['party_id']):
                await interaction.followup.send(
                    embed=EmbedBuilder.warning("Not Queued", "Your party is not in the queue."),
                    ephemeral=True
                )
                return

            await self.bot.db.remove_party_from_queue(party['party_id'])
            # Only the leader gets a cooldown — they chose to leave
            await self.bot.db.set_queue_cooldown(user.id)
            await interaction.followup.send(
                embed=EmbedBuilder.success("Left Queue", "Your party left the matchmaking queue."),
                ephemeral=True
            )
        else:
            if not await self.bot.db.is_player_in_queue(user.id):
                await interaction.followup.send(
                    embed=EmbedBuilder.warning("Not Queued", "You are not in the queue."),
                    ephemeral=True
                )
                return

            await self.bot.db.remove_player_from_queue(user.id)
            await self.bot.db.set_queue_cooldown(user.id)
            await interaction.followup.send(
                embed=EmbedBuilder.success("Left Queue", f"You left the matchmaking queue. You can re-join in **{Config.QUEUE_LEAVE_COOLDOWN_SECONDS // 60} minutes**."),
                ephemeral=True
            )

        await self.update_all_queue_messages()

    # =========================================================
    # SLASH COMMAND EQUIVALENTS OF THE QUEUE BUTTONS
    # =========================================================

    @queue_group.command(name="join", description="Join the matchmaking queue (Solo, or with your Party).")
    async def queue_join(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.handle_join(interaction)

    @queue_group.command(name="leave", description="Leave the matchmaking queue.")
    async def queue_leave(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.handle_leave(interaction)

    @queue_group.command(name="status", description="Check the current matchmaking queue status.")
    async def queue_status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        queue_players = await self.bot.db.get_all_queued_players()
        embed = await self.create_queue_embed(queue_players)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # =========================================================
    # MATCHMAKING LOOP & SNAKE DRAFT
    # =========================================================

    @tasks.loop(seconds=15)
    async def matchmaking_loop(self):
        """Periodically checks queue and creates Matchrooms if 10 players are available."""
        async with self.matchmaking_lock:
            await self._try_create_matches()
            
    @matchmaking_loop.before_loop
    async def before_matchmaking_loop(self):
        await self.bot.wait_until_ready()
        
    async def _try_create_matches(self):
        """
        Gathers queued players/parties, verifies if there are 10,
        and balances them into two teams while keeping parties together.
        """
        queued_players = await self.bot.db.get_all_queued_players() 
        
        if len(queued_players) < 10:
            return 
            
        # Select first 10 players (In advanced logic, you'd select the 10 closest in ELO)
        lobby = queued_players[:10]
        
        team1_players = []
        team2_players = []
        
        # 1. Group players by party to ensure they are not split
        parties_in_lobby = {}
        solo_players = []
        
        for player in lobby:
            party_id = player.get('party_id')
            if party_id:
                if party_id not in parties_in_lobby:
                    parties_in_lobby[party_id] = []
                parties_in_lobby[party_id].append(player)
            else:
                solo_players.append(player)
                
        # 2. Sort parties by average ELO (Highest first)
        sorted_parties = sorted(
            list(parties_in_lobby.values()), 
            key=lambda p: sum(x['elo'] for x in p) / len(p), 
            reverse=True
        )
        
        # Sort solo players by ELO (Highest first)
        solo_players.sort(key=lambda p: p['elo'], reverse=True)
        
        # 3. Simple greedy algorithm to balance team ELO while keeping parties intact
        for party in sorted_parties:
            t1_elo = sum(p['elo'] for p in team1_players)
            t2_elo = sum(p['elo'] for p in team2_players)
            
            if t1_elo <= t2_elo and len(team1_players) + len(party) <= 5:
                team1_players.extend(party)
            elif len(team2_players) + len(party) <= 5:
                team2_players.extend(party)
            else:
                if len(team1_players) + len(party) <= 5:
                    team1_players.extend(party)
                else:
                    team2_players.extend(party)
                    
        # Fill remaining slots with solo players
        for player in solo_players:
            t1_elo = sum(p['elo'] for p in team1_players)
            t2_elo = sum(p['elo'] for p in team2_players)
            
            if t1_elo <= t2_elo and len(team1_players) < 5:
                team1_players.append(player)
            elif len(team2_players) < 5:
                team2_players.append(player)
            else:
                if len(team1_players) < 5:
                    team1_players.append(player)
                else:
                    team2_players.append(player)
                    
        # 4. Assign Captains (Player with the highest ELO on each drafted team)
        team1_players.sort(key=lambda p: p['elo'], reverse=True)
        team2_players.sort(key=lambda p: p['elo'], reverse=True)
        
        captain1 = team1_players[0]
        captain2 = team2_players[0]
        
        # Remove these 10 players/parties from the queue
        for player in lobby:
            if player.get('party_id'):
                await self.bot.db.remove_party_from_queue(player['party_id'])
            else:
                await self.bot.db.remove_player_from_queue(player['discord_id'])
        
        # Clear the host info - it belongs to this specific queue session only
        await self.bot.db.clear_queue_host_info()
                
        # Create temporary PUG teams in DB
        team1_id = await self.bot.db.create_pug_team(f"Team {captain1['username']}", captain1['discord_id'], [p['discord_id'] for p in team1_players])
        team2_id = await self.bot.db.create_pug_team(f"Team {captain2['username']}", captain2['discord_id'], [p['discord_id'] for p in team2_players])
        
        team1_data = await self.bot.db.get_team_by_id(team1_id)
        team2_data = await self.bot.db.get_team_by_id(team2_id)
        
        await self._create_matchroom(team1_data, team2_data, team1_players, team2_players)
        await self.update_all_queue_messages()

    async def _create_matchroom(self, team1: dict, team2: dict, roster1: list, roster2: list):
        """Creates the Matchroom's private channels, then runs the live Map Veto inside the lobby."""
        team1_avg_elo = sum(p['elo'] for p in roster1) // 5
        team2_avg_elo = sum(p['elo'] for p in roster2) // 5
        
        match_id = await self.bot.db.create_match(
            team1['team_id'], team2['team_id'], team1_avg_elo, team2_avg_elo
        )
        
        team1_prob, team2_prob = ELOCalculator.calculate_win_probability(team1_avg_elo, team2_avg_elo)
        
        # Create the private per-match Discord channels (1 shared lobby text
        # channel + 1 voice channel per team) BEFORE the veto starts, so the
        # veto itself can run live, in the open, inside the lobby channel.
        # If MatchRooms isn't loaded or channel creation fails, this returns
        # None and the match falls back to a DM-based veto instead.
        match_rooms_cog = self.bot.get_cog('MatchRooms')
        created_channels = None
        if match_rooms_cog:
            created_channels = await match_rooms_cog.create_match_channels(
                match_id, team1, team2, roster1, roster2
            )
        
        veto_view = MapVetoView(match_id, team1, team2, self.bot)
        veto_embed = await veto_view._create_veto_embed()
        
        cap1_user = await self.bot.fetch_user(team1['captain_id'])
        cap2_user = await self.bot.fetch_user(team2['captain_id'])
        
        if created_channels and created_channels.get('lobby'):
            # PRIMARY FLOW: veto happens live, visible to everyone, inside the
            # lobby channel - both captains click buttons on the SAME message.
            lobby_channel = created_channels['lobby']
            try:
                await lobby_channel.send(
                    content=f"🚨 <@{team1['captain_id']}> <@{team2['captain_id']}> — Map Veto starts now!",
                    embed=veto_embed,
                    view=veto_view
                )
            except discord.Forbidden:
                pass
        else:
            # FALLBACK: no Matchroom channel could be created (missing
            # permissions, etc.) - run the veto via DM instead. Both
            # captains get the SAME view instance so either of them can
            # actually click buttons when it's their turn.
            for cap_user in (cap1_user, cap2_user):
                try:
                    await cap_user.send(embed=veto_embed, view=veto_view)
                except discord.Forbidden:
                    pass
        
        # Roster/overview card, DM'd to both Captains
        embed = discord.Embed(
            title="🎮 Matchroom Generated!",
            description=(
                f"Map Veto is happening live in {created_channels['lobby'].mention} — head over there!"
                if created_channels and created_channels.get('lobby')
                else "Map Veto is starting now in your DMs - check your messages."
            ),
            color=Config.COLOR_INFO
        )
        
        t1_mentions = "\n".join([
            f"• <@{p['discord_id']}> 🎮 `{p.get('roblox_username') or 'N/A'}` — `{p['elo']} ELO` {level_utils.get_level_label(p['elo'])}"
            for p in roster1
        ])
        embed.add_field(
            name=f"🛡️ {team1['name']} (Avg: {team1_avg_elo})",
            value=f"**Win Probability:** {team1_prob*100:.1f}%\n\n**Roster:**\n{t1_mentions}",
            inline=True
        )
        
        embed.add_field(name="⚔️", value="VS", inline=True)
        
        t2_mentions = "\n".join([
            f"• <@{p['discord_id']}> 🎮 `{p.get('roblox_username') or 'N/A'}` — `{p['elo']} ELO` {level_utils.get_level_label(p['elo'])}"
            for p in roster2
        ])
        embed.add_field(
            name=f"🛡️ {team2['name']} (Avg: {team2_avg_elo})",
            value=f"**Win Probability:** {team2_prob*100:.1f}%\n\n**Roster:**\n{t2_mentions}",
            inline=True
        )
        
        embed.set_footer(text=f"Matchroom ID: #{match_id} | FACEIT PUG System")
        
        if created_channels:
            embed.add_field(
                name="📂 Private Match Channels",
                value=(
                    f"🗺️ Map Veto / Server Link: {created_channels['lobby'].mention}\n"
                    f"🔊 {team1['name']} Voice: {created_channels['team1_voice'].mention}\n"
                    f"🔊 {team2['name']} Voice: {created_channels['team2_voice'].mention}\n"
                    "*(these channels are deleted automatically once the match ends)*"
                ),
                inline=False
            )
        
        for cap in [cap1_user, cap2_user]:
            try:
                await cap.send(embed=embed)
            except discord.Forbidden:
                continue
                
        self.bot.logger.info(f"Matchroom #{match_id} created: {team1['name']} vs {team2['name']}")

    # =========================================================
    # QUEUE PANEL EMBED (premium visual style)
    # =========================================================

    async def update_all_queue_messages(self):
        """Updates all deployed Queue UI embeds."""
        queue_messages = await self.bot.db.get_queue_messages()
        queue_players = await self.bot.db.get_all_queued_players()
        
        embed = await self.create_queue_embed(queue_players)
        
        for msg_data in queue_messages:
            try:
                channel = self.bot.get_channel(msg_data['channel_id'])
                if not channel:
                    continue
                message = await channel.fetch_message(msg_data['message_id'])
                await message.edit(embed=embed)
            except (discord.NotFound, discord.Forbidden):
                await self.bot.db.delete_queue_message(msg_data['message_id'])

    async def create_queue_embed(self, queue_players: list) -> discord.Embed:
        """Constructs a clean, professional, FACEIT-style queue embed."""
        player_count = len(queue_players)
        slots_left = 10 - player_count
        
        embed = discord.Embed(
            title="🎮 BLOX STRIKE MATCHMAKING | LIVE QUEUE",
            description=f"**{build_progress_bar(player_count, 10)}**  `{player_count}/10`",
            color=0xFF5500  # FACEIT Orange
        )

        # Show host info (server link + friend link) if someone started the queue
        host_info = await self.bot.db.get_queue_host_info()
        if host_info:
            embed.add_field(
                name="🏠 Queue Host",
                value=(
                    f"<@{host_info['host_id']}>\n"
                    f"🔗 [**Private Server Link**]({host_info['server_link']})\n"
                    f"👤 [**Friend Request / Profile**]({host_info['friend_link']})"
                ),
                inline=False
            )

        if player_count == 0:
            embed.add_field(
                name="👥 Players in Queue",
                value="> *The queue is currently empty. Click the button below to join.*",
                inline=False
            )
        else:
            player_list = []
            for p in queue_players:
                joined_time = datetime.strptime(p['joined_at'], "%Y-%m-%d %H:%M:%S")
                roblox_tag = f" 🎮 `{p['roblox_username']}`" if p.get('roblox_username') else ""
                party_tag = " 🎉" if p.get('party_id') else ""
                level_tag = level_utils.get_level_label(p['elo'])
                player_list.append(
                    f"🔹 **{p['username']}**{party_tag}{roblox_tag} — 💠 `{p['elo']} ELO` {level_tag} — 🕒 `{joined_time.strftime('%H:%M')}`"
                )

            header = f"📊 ACTIVE PLAYERS ({player_count}/10)" if player_count < 10 else "🟢 QUEUE FULL - MATCH STARTING"
            embed.add_field(
                name=header,
                value="\n".join(player_list),
                inline=False
            )

        if slots_left > 0:
            embed.add_field(
                name="⏳ WAITING FOR...",
                value=f"**{slots_left}** more players needed to start the match.",
                inline=False
            )

        embed.add_field(
            name="⚙️ SETTINGS",
            value=(
                "• Platform: **Roblox** (Blox Strike)\n"
                "• Format: **Solo / Party (max 5)**\n"
                "• Draft: **Automated Snake Draft**\n"
                "• Registration: **`/register` required**"
            ),
            inline=True
        )

        embed.set_footer(text="Blox Strike PUG System")
        embed.timestamp = discord.utils.utcnow()

        return embed

    # =========================================================
    # QUEUE ADMIN COMMANDS
    # =========================================================

    # =========================================================
    # QUEUE HOST MODAL
    # =========================================================

    class QueueHostModal(discord.ui.Modal, title="Start The Queue"):
        """
        Shown to non-admins when they want to start the matchmaking queue.
        They must provide a Roblox Private Server link and a Friend Request
        link (or profile URL) so other players know how to join / add them.
        """
        server_link = discord.ui.TextInput(
            label="Roblox Private Server Link",
            placeholder="https://www.roblox.com/games/... (paste your Private Server link)",
            style=discord.TextStyle.short,
            required=True,
            max_length=500,
        )
        friend_link = discord.ui.TextInput(
            label="Your Roblox Profile / Friend Request Link",
            placeholder="https://www.roblox.com/users/... (so players can add you)",
            style=discord.TextStyle.short,
            required=True,
            max_length=500,
        )

        def __init__(self, cog):
            super().__init__()
            self.cog = cog

        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)

            server_link = self.server_link.value.strip()
            friend_link = self.friend_link.value.strip()

            # Basic validation - must at least look like Roblox URLs
            if "roblox.com" not in server_link.lower():
                await interaction.followup.send(
                    "❌ The Private Server link doesn't look like a valid Roblox URL.\n"
                    "It should start with `https://www.roblox.com/games/...`",
                    ephemeral=True,
                )
                return
            if "roblox.com" not in friend_link.lower():
                await interaction.followup.send(
                    "❌ The profile link doesn't look like a valid Roblox URL.\n"
                    "It should start with `https://www.roblox.com/users/...`",
                    ephemeral=True,
                )
                return

            # Save the host info to the DB
            await self.cog.bot.db.set_queue_host_info(
                interaction.user.id, server_link, friend_link
            )

            # Now deploy the persistent queue UI
            queue_players = await self.cog.bot.db.get_all_queued_players()
            embed = await self.cog.create_queue_embed(queue_players)
            view = QueueView(self.cog.bot)

            message = await interaction.channel.send(embed=embed, view=view)
            await self.cog.bot.db.save_queue_message(message.id, interaction.channel.id, interaction.guild.id)

            await interaction.followup.send(
                "✅ Queue is live! Your Roblox links have been saved and will be shown to players once the match pops.",
                ephemeral=True,
            )

    @queue_group.command(name="setup", description="Start the matchmaking queue in this channel. Admins deploy instantly; others must provide Roblox links first.")
    async def queue_setup(self, interaction: discord.Interaction):
        is_admin = (
            interaction.user.guild_permissions.administrator
            or (
                hasattr(Config, 'ADMIN_ROLE_IDS')
                and any(r.id in Config.ADMIN_ROLE_IDS for r in interaction.user.roles)
            )
        )

        if is_admin:
            # Admins deploy straight away - no links required
            await interaction.response.defer(ephemeral=True)
            queue_players = await self.bot.db.get_all_queued_players()
            embed = await self.create_queue_embed(queue_players)
            view = QueueView(self.bot)
            message = await interaction.channel.send(embed=embed, view=view)
            await self.bot.db.save_queue_message(message.id, interaction.channel.id, interaction.guild.id)
            await interaction.followup.send("✅ Queue UI deployed.", ephemeral=True)
        else:
            # Non-admins must submit their Roblox links first via a Modal
            await interaction.response.send_modal(QueueSystem.QueueHostModal(self))

    # =========================================================
    # PARTY SYSTEM COMMANDS
    # =========================================================

    @party_group.command(name="invite", description="Invite a player to your party.")
    @app_commands.describe(member="The player you want to invite")
    async def party_invite(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        
        if member.id == interaction.user.id:
            await interaction.followup.send("❌ You cannot invite yourself.", ephemeral=True)
            return
            
        # Register both users if not in DB
        await self.bot.db.create_or_get_player(interaction.user.id, str(interaction.user))
        await self.bot.db.create_or_get_player(member.id, str(member))
        
        party = await self.bot.db.get_player_party(interaction.user.id)
        
        if not party:
            # Create a new party if the user doesn't have one
            party_id = await self.bot.db.create_party(interaction.user.id)
            party = await self.bot.db.get_party_by_id(party_id)
        elif party['leader_id'] != interaction.user.id:
            await interaction.followup.send("❌ You are not the leader of your current party.", ephemeral=True)
            return
            
        party_members = await self.bot.db.get_party_members(party['party_id'])
        if len(party_members) >= 5:
            await interaction.followup.send("❌ Your party is full (Max 5).", ephemeral=True)
            return
            
        # Check if target is already in a party
        target_party = await self.bot.db.get_player_party(member.id)
        if target_party:
            await interaction.followup.send(f"❌ {member.display_name} is already in a party.", ephemeral=True)
            return
            
        # Send an invite (Simplified logic: Auto-adds for this example, but you could implement an Accept/Decline view)
        await self.bot.db.add_player_to_party(party['party_id'], member.id)
        
        try:
            await member.send(f"🎉 **{interaction.user.display_name}** has added you to their FACEIT Party! Queue up together.")
        except discord.Forbidden:
            pass

        warning = ""
        target_player = await self.bot.db.get_player(member.id)
        if not target_player or not target_player.get('roblox_username'):
            warning = f"\n⚠️ Heads up: {member.display_name} still needs to run `/register` before your party can queue."

        await interaction.followup.send(
            f"✅ Successfully added **{member.display_name}** to your party.{warning}",
            ephemeral=True
        )

    @party_group.command(name="leave", description="Leave your current party.")
    async def party_leave(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        party = await self.bot.db.get_player_party(interaction.user.id)
        if not party:
            await interaction.followup.send("❌ You are not in a party.", ephemeral=True)
            return
            
        # If leader leaves, reassign leader or disband
        if party['leader_id'] == interaction.user.id:
            party_members = await self.bot.db.get_party_members(party['party_id'])
            if len(party_members) > 1:
                # Assign new leader
                new_leader = next(m for m in party_members if m['discord_id'] != interaction.user.id)
                await self.bot.db.set_party_leader(party['party_id'], new_leader['discord_id'])
                await self.bot.db.remove_player_from_party(interaction.user.id)
                await interaction.followup.send("✅ You left the party. Leadership transferred.", ephemeral=True)
            else:
                # Disband party
                await self.bot.db.delete_party(party['party_id'])
                await interaction.followup.send("✅ You left and disbanded the party.", ephemeral=True)
        else:
            await self.bot.db.remove_player_from_party(interaction.user.id)
            await interaction.followup.send("✅ You left the party.", ephemeral=True)
            
        # If party was in queue, remove it to prevent ghost queues
        if await self.bot.db.is_party_in_queue(party['party_id']):
            await self.bot.db.remove_party_from_queue(party['party_id'])
            
        await self.update_all_queue_messages()

    @party_group.command(name="view", description="View your current party members.")
    async def party_view(self, interaction: discord.Interaction):
        party = await self.bot.db.get_player_party(interaction.user.id)
        if not party:
            await interaction.response.send_message("❌ You are not in a party.", ephemeral=True)
            return
            
        members = await self.bot.db.get_party_members(party['party_id'])
        
        embed = discord.Embed(
            title="👥 Your Current Party",
            color=0x5865F2
        )
        
        member_text = ""
        for m in members:
            icon = "👑" if m['discord_id'] == party['leader_id'] else "👤"
            roblox_tag = f" 🎮 `{m['roblox_username']}`" if m.get('roblox_username') else " ⚠️ *(not registered)*"
            member_text += f"{icon} <@{m['discord_id']}> ({m['elo']} ELO){roblox_tag}\n"
            
        embed.description = member_text
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(QueueSystem(bot))