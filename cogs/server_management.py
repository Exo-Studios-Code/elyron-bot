"""
Server Management Cog
FACEIT Hub integration, permanent hub link, and Matchroom notifications.
Updated for Slash Commands and the dynamic PUG Matchmaking system.
"""

import discord
from discord import app_commands
from discord.ext import commands
from utils.config import Config
from utils.embeds import EmbedBuilder

class ServerManagement(commands.Cog):
    """Commands for FACEIT Hub and Matchroom management."""
    
    def __init__(self, bot):
        self.bot = bot
        
        # ═══════════════════════════════════════════════════
        # SET YOUR FACEIT HUB LINK HERE!
        # ═══════════════════════════════════════════════════
        self.faceit_hub_url = "https://www.faceit.com/cs/club/b6b68c8f-e31d-4e56-9b1f-84249cca9146"
        # Example: https://www.faceit.com/en/hub/a1b2c3d4-1234-5678
        # ═══════════════════════════════════════════════════
    
    @app_commands.command(name="server", description="Display FACEIT Hub link and match instructions.")
    @app_commands.describe(match_id="Optional: Specific Matchroom ID to get detailed instructions.")
    async def server(self, interaction: discord.Interaction, match_id: int = None):
        """
        Display FACEIT Hub link and instructions.
        Can be used generally or for a specific match.
        """
        await interaction.response.defer(ephemeral=False)
        
        if match_id:
            await self._show_match_info(interaction, match_id)
        else:
            await self._show_hub_info(interaction)
            
    @app_commands.command(name="faceit", description="Displays general FACEIT Hub information and link.")
    async def faceit(self, interaction: discord.Interaction):
        """Alias for /server - displays general FACEIT Hub info."""
        await interaction.response.defer(ephemeral=False)
        await self._show_hub_info(interaction)
    
    @app_commands.command(name="notify", description="Ping all 10 players in a match with FACEIT instructions.")
    @app_commands.describe(match_id="The Matchroom ID to notify players for.")
    @app_commands.default_permissions(manage_messages=True) # Usually reserved for admins or captains
    async def notify(self, interaction: discord.Interaction, match_id: int):
        """Pings all players in a match to join the FACEIT Hub."""
        await interaction.response.defer()
        
        match = await self.bot.db.get_match(match_id)
        if not match:
            await interaction.followup.send("❌ Match not found.", ephemeral=True)
            return
        
        team1 = await self.bot.db.get_team_by_id(match['team1_id'])
        team2 = await self.bot.db.get_team_by_id(match['team2_id'])
        
        # In the PUG system, the team members are exactly the 5 drafted players
        members1 = await self.bot.db.get_team_members(match['team1_id'])
        members2 = await self.bot.db.get_team_members(match['team2_id'])
        
        # Create mentions for all 10 players
        mentions = []
        for p in members1 + members2:
            mentions.append(f"<@{p['discord_id']}>")
        
        embed = discord.Embed(
            title=f"🚨 MATCHROOM #{match_id} IS STARTING!",
            description=f"**{team1['name']}** vs **{team2['name']}**",
            color=0xFF0000
        )
        
        if match['map_played']:
            embed.add_field(name="🗺️ Map", value=f"**{match['map_played']}**", inline=True)
        else:
            embed.add_field(name="🗺️ Map", value="*Veto in progress...*", inline=True)
            
        embed.add_field(
            name="🔗 FACEIT Hub",
            value=f"[**JOIN THE LOBBY NOW**]({self.faceit_hub_url})",
            inline=False
        )
        
        embed.add_field(
            name="📋 What To Do Next",
            value=(
                "1. Click the link above to join the FACEIT Hub.\n"
                "2. **Captains:** Coordinate who will host the lobby.\n"
                "3. Invite all 10 drafted players to the lobby.\n"
                f"4. Set the map to: **{match['map_played'] or 'TBD'}**\n"
                "5. Everyone readys up → Server automatically deploys!"
            ),
            inline=False
        )
        
        await interaction.followup.send(content=" ".join(mentions), embed=embed)
    
    async def _show_match_info(self, interaction: discord.Interaction, match_id: int):
        """Helper to show match-specific FACEIT info."""
        match = await self.bot.db.get_match(match_id)
        if not match:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Match Not Found", f"No match exists with ID `#{match_id}`.")
            )
            return
        
        team1 = await self.bot.db.get_team_by_id(match['team1_id'])
        team2 = await self.bot.db.get_team_by_id(match['team2_id'])
        
        members1 = await self.bot.db.get_team_members(match['team1_id'])
        members2 = await self.bot.db.get_team_members(match['team2_id'])
        
        embed = discord.Embed(
            title=f"🎮 FACEIT Matchroom #{match_id}",
            description=f"**{team1['name']}** vs **{team2['name']}**",
            color=0xFF6B00 # FACEIT Orange
        )
        
        if match['map_played']:
            embed.add_field(name="🗺️ Selected Map", value=f"**{match['map_played']}**", inline=True)
        else:
            embed.add_field(name="🗺️ Selected Map", value="*Pending Veto*", inline=True)
            
        embed.add_field(name="📊 Status", value=match['status'].upper(), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        
        embed.add_field(
            name="🔗 FACEIT Hub",
            value=f"[**Click here to join the Hub**]({self.faceit_hub_url})",
            inline=False
        )
        
        # Rosters
        r1 = "\n".join([f"• {p['username']}" for p in members1]) or "N/A"
        r2 = "\n".join([f"• {p['username']}" for p in members2]) or "N/A"
        
        embed.add_field(name=f"👥 {team1['name']}", value=r1, inline=True)
        embed.add_field(name=f"👥 {team2['name']}", value=r2, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        
        embed.add_field(
            name="📋 How To Play Your Match",
            value=(
                "**1.** Click the FACEIT Hub link above.\n"
                "**2.** Log in to FACEIT (if you aren't already).\n"
                "**3.** Inside the Hub, click **Play** or **Find Match**.\n"
                "**4.** Captains: Create a lobby OR join the existing one.\n"
                "**5.** **CRITICAL:** Invite all 10 drafted players!\n"
                f"**6.** Set map to: **{match['map_played'] or 'TBD'}**\n"
                "**7.** All 10 players must Ready Up.\n"
                "**8.** The CS2 Server will be created automatically!"
            ),
            inline=False
        )
        
        embed.add_field(
            name="⚠️ Important Requirements",
            value=(
                f"• **Map:** Must match the veto result: **{match['map_played'] or 'TBD'}**\n"
                "• **Lobby:** Must contain the exact 10 players shown above.\n"
                "• **Captains:** Communicate via Discord to sync up.\n"
                "• **FACEIT AC:** The Anti-Cheat client must be running."
            ),
            inline=False
        )
        
        embed.add_field(
            name="📝 Post-Match: Reporting Results",
            value=(
                "**1.** Winning Captain uses: `/match report match_id:{id} result:Win`\n"
                "**2.** Losing Captain uses: `/match confirm match_id:{id}`\n"
                "**3.** *Both captains must complete their steps for ELO to be distributed!*\n"
            ),
            inline=False
        )
        
        embed.set_footer(text=f"Matchroom ID: #{match_id} | FACEIT Integration")
        await interaction.followup.send(embed=embed)
    
    async def _show_hub_info(self, interaction: discord.Interaction):
        """Helper to show general Hub info."""
        embed = discord.Embed(
            title="🎮 FACEIT Hub - CS2 PUG League",
            description="All official matchmaking games are hosted on our dedicated FACEIT Hub.",
            color=0xFF6B00 # FACEIT Orange
        )
        
        embed.add_field(
            name="🔗 FACEIT Hub Link",
            value=f"[**Click here to join**]({self.faceit_hub_url})",
            inline=False
        )
        
        embed.add_field(
            name="📋 How The System Works",
            value=(
                "**1.** Log in to your FACEIT account.\n"
                "**2.** Join the Hub using the link above.\n"
                "**3.** Queue up in Discord using `/queue setup` UI.\n"
                "**4.** When the queue pops (10 players), wait for the Map Veto.\n"
                "**5.** Lobby Captains create the FACEIT lobby and invite the drafted players.\n"
                "**6.** Set the exact map chosen during the veto.\n"
                "**7.** Ready up -> Connect to the server automatically -> Play!"
            ),
            inline=False
        )
        
        embed.add_field(
            name="💡 Useful Commands & Tips",
            value=(
                "• **Captains:** Decide who hosts the lobby to avoid confusion.\n"
                "• **Voice Comms:** Use the generated Discord voice channels.\n"
                "• **Map Integrity:** Always play the map decided by the Discord bot.\n"
                "• **Specific Match Info:** `/server match_id:<id>`\n"
                "• **Ping Lobby:** `/notify match_id:<id>`"
            ),
            inline=False
        )
        
        embed.add_field(
            name="📝 Post-Match: Reporting Results",
            value=(
                "**Lobby Captains must report and confirm the result:**\n"
                "**1.** Winning Captain: `/match report match_id:<id> result:Win`\n"
                "**2.** Losing Captain: `/match confirm match_id:<id>`\n\n"
                "⚠️ **The match will not conclude and ELO will not update until both steps are done!**"
            ),
            inline=False
        )
        
        embed.set_footer(text="FACEIT Hub | CS2 Anti-Cheat Protected")
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(ServerManagement(bot))