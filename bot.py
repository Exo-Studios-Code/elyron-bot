"""
CS2 PUG League Bot - Main Entry Point
A production-ready Discord bot for managing competitive FACEIT-style CS2 Matchmaking.
Updated for Slash Commands and Dynamic PUG Queues.
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import logging
from pathlib import Path
import sys
from dotenv import load_dotenv
load_dotenv()
from utils.config import Config
from utils.database import Database
from utils.logger import setup_logger

class CS2LeagueBot(commands.Bot):
    """Main bot class with initialization and cog management."""
    
    def __init__(self):
        # Setup intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        
        super().__init__(
            command_prefix=Config.PREFIX,
            intents=intents,
            help_command=None  # Disables the default help command to prevent conflicts
        )
        
        self.config = Config
        self.logger = setup_logger()
        self.db = None
        
    async def setup_hook(self):
        """Initialize database, load cogs, and sync slash commands."""
        self.logger.info("Initializing database...")
        self.db = Database()
        await self.db.initialize()
        
        self.logger.info("Loading cogs...")
        # Note: 'cogs.team_management' has been permanently removed for the PUG system.
        cogs = [
            'cogs.queue_system',
            'cogs.match_rooms',
            'cogs.levels',
            'cogs.match_system',
            'cogs.leaderboard',
            'cogs.admin',
            'cogs.help_command',
        ]
        
        for cog in cogs:
            try:
                await self.load_extension(cog)
                self.logger.info(f"Loaded cog: {cog}")
            except Exception as e:
                self.logger.error(f"Failed to load cog {cog}: {e}")
                
        # Register the custom tree error handler
        self.tree.on_error = self.on_tree_error
                
        # Sync slash commands to Discord
        self.logger.info("Syncing slash commands...")
        try:
            synced = await self.tree.sync()
            self.logger.info(f"Successfully synced {len(synced)} slash commands globally.")
        except Exception as e:
            self.logger.error(f"Failed to sync slash commands: {e}")
                
    async def on_ready(self):
        """Event triggered when bot is ready."""
        self.logger.info(f"Bot is ready! Logged in as {self.user.name} ({self.user.id})")
        self.logger.info(f"Connected to {len(self.guilds)} guilds")
        
        # Set bot status indicating the use of slash commands
        await self.change_presence(
            activity=discord.Game(name="/help | CS2 FACEIT PUGs")
        )
        
    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Global error handler for Slash Commands."""
        if isinstance(error, app_commands.CommandNotFound):
            return
            
        elif isinstance(error, app_commands.MissingPermissions):
            error_msg = "❌ You don't have the required permissions to use this command."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)
                
        elif isinstance(error, app_commands.CommandOnCooldown):
            error_msg = f"⏰ This command is on cooldown. Try again in {error.retry_after:.1f}s."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)
                
        else:
            self.logger.error(f"Unhandled slash command error in {interaction.command.name}: {error}", exc_info=error)
            error_msg = "❌ An unexpected error occurred. Please contact an administrator."
            
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(error_msg, ephemeral=True)
                else:
                    await interaction.response.send_message(error_msg, ephemeral=True)
            except discord.InteractionResponded:
                pass

    async def on_command_error(self, ctx, error):
        """Fallback global error handler for any remaining text (prefix) commands."""
        if isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing required argument: `{error.param.name}`")
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use this command.")
        else:
            self.logger.error(f"Unhandled prefix command error in {ctx.command}: {error}", exc_info=error)


def main():
    """Main entry point."""
    # Create necessary directories
    Path("data").mkdir(exist_ok=True)
    Path("data/team_logos").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)
    
    # Initialize and run bot
    bot = CS2LeagueBot()
    
    try:
        bot.run(Config.TOKEN)
    except discord.LoginFailure:
        logging.error("Invalid bot token!")
        sys.exit(1)
    except KeyboardInterrupt:
        logging.info("Bot shutdown requested")
        sys.exit(0)

if __name__ == "__main__":
    main()