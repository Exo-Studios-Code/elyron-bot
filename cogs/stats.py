"""
Stats Cog
Handles Blox Strike scoreboard screenshot submission, Gemini Vision OCR
parsing, and per-player / career statistics display.

Flow:
  1. After playing a match, a Lobby Captain runs /stats upload in the
     Matchroom lobby channel (or any channel) and attaches the scoreboard
     screenshot.
  2. The bot sends it to Gemini Vision, gets back a JSON with all 10
     players' stats (kills, deaths, assists, MVPs, score).
  3. The bot shows a preview embed and asks the Captain to confirm or
     discard (in case OCR got something wrong).
  4. On confirmation the stats are written to the DB. Career aggregates
     are updated at the same time.
  5. Anyone can view:
       /stats match <match_id>   — full scoreboard for that match
       /stats player [@member]   — career stats + last 5 matches table
"""

import io
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

from utils.config import Config
from utils.embeds import EmbedBuilder
from utils.scoreboard_ocr import ScoreboardOCR
from utils import levels as level_utils


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kd(kills: int, deaths: int) -> str:
    if deaths == 0:
        return f"{kills:.1f}" if kills else "0.0"
    return f"{kills / deaths:.2f}"

def _adr_placeholder() -> str:
    return "N/A"  # Blox Strike scoreboard doesn't expose ADR


# ---------------------------------------------------------------------------
# Confirm / discard view shown after OCR preview
# ---------------------------------------------------------------------------

class StatsConfirmView(discord.ui.View):
    def __init__(self, cog, match_id: int, rows, confidence: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.match_id = match_id
        self.rows = rows
        self.confidence = confidence
        self.result = None

    @discord.ui.button(label="✅ Confirm & Save", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = True
        self.stop()
        await interaction.response.defer()
        await self.cog._save_stats(interaction, self.match_id, self.rows, self.confidence)

    @discord.ui.button(label="❌ Discard", style=discord.ButtonStyle.danger)
    async def discard(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = False
        self.stop()
        await interaction.response.send_message(
            "Stats discarded. You can upload a clearer screenshot and try again.",
            ephemeral=True,
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Stats(commands.Cog):
    """Commands for submitting and viewing per-match and career statistics."""

    stats_group = app_commands.Group(name="stats", description="Match statistics and scoreboard OCR")

    def __init__(self, bot):
        self.bot = bot
        self._ocr = ScoreboardOCR()

    # ------------------------------------------------------------------
    # /stats upload
    # ------------------------------------------------------------------

    @stats_group.command(name="upload", description="Upload a scoreboard screenshot to extract match stats.")
    @app_commands.describe(
        match_id="The Matchroom ID this screenshot belongs to",
        screenshot="Screenshot of the Blox Strike end-of-match scoreboard"
    )
    async def stats_upload(
        self,
        interaction: discord.Interaction,
        match_id: int,
        screenshot: discord.Attachment,
    ):
        await interaction.response.defer(ephemeral=False)

        # Validate the match exists
        match = await self.bot.db.get_match(match_id)
        if not match:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Match Not Found", f"No Matchroom with ID `#{match_id}` exists."),
                ephemeral=True,
            )
            return

        # Only Lobby Captains or Admins should submit stats
        user_team = await self.bot.db.get_active_team_for_player(interaction.user.id)
        is_captain = user_team and user_team["captain_id"] == interaction.user.id
        is_admin = interaction.user.guild_permissions.administrator
        if not is_captain and not is_admin:
            await interaction.followup.send(
                embed=EmbedBuilder.error(
                    "Captains Only",
                    "Only a Lobby Captain (or an admin) can submit match stats.",
                ),
                ephemeral=True,
            )
            return

        # Check it's an image
        if not screenshot.content_type or not screenshot.content_type.startswith("image/"):
            await interaction.followup.send(
                embed=EmbedBuilder.error("Not An Image", "Please attach a PNG or JPG screenshot."),
                ephemeral=True,
            )
            return

        # Download the attachment
        await interaction.followup.send("🔍 Analysing screenshot with Gemini Vision…", ephemeral=False)

        image_bytes = await screenshot.read()
        mime_type = screenshot.content_type.split(";")[0].strip()

        ocr_data, confidence = await self._ocr.parse_screenshot(image_bytes, mime_type)

        if ocr_data is None:
            await interaction.channel.send(
                embed=EmbedBuilder.error(
                    "OCR Failed",
                    f"Gemini couldn't parse the screenshot: `{confidence}`\n"
                    "Try a cleaner, full-resolution screenshot.",
                )
            )
            return

        rows = self._ocr.normalise(ocr_data, match_id)

        if not rows:
            await interaction.channel.send(
                embed=EmbedBuilder.error("No Players Found", "Gemini returned data but no player rows were found.")
            )
            return

        # Check if stats already exist for this match
        existing = await self.bot.db.get_match_player_stats(match_id)
        if existing:
            await interaction.channel.send(
                embed=EmbedBuilder.warning(
                    "Stats Already Submitted",
                    f"Stats for Matchroom `#{match_id}` were already saved. "
                    "Use `/stats match` to view them, or contact an admin to reset.",
                )
            )
            return

        # Show preview embed for Captain to confirm
        preview = self._build_preview_embed(match_id, ocr_data, rows, confidence)
        view = StatsConfirmView(self, match_id, rows, confidence)
        await interaction.channel.send(embed=preview, view=view)

    # ------------------------------------------------------------------
    # Internal: save confirmed stats
    # ------------------------------------------------------------------

    async def _save_stats(self, interaction: discord.Interaction, match_id: int, rows, confidence: str):
        try:
            await self.bot.db.save_match_player_stats(rows, confidence)
            await self.bot.db.update_career_stats_from_match(match_id)

            saved = await self.bot.db.get_match_player_stats(match_id)

            embed = discord.Embed(
                title=f"✅ Stats Saved — Matchroom #{match_id}",
                description=f"**{len(saved)}** players recorded. Career stats updated.",
                color=0x00C853,
            )
            embed.add_field(
                name="View Full Scoreboard",
                value=f"`/stats match match_id:{match_id}`",
                inline=True,
            )
            embed.add_field(
                name="View Your Stats",
                value="`/stats player`",
                inline=True,
            )
            await interaction.channel.send(embed=embed)

        except Exception as e:
            self.bot.logger.error(f"Stats save error for match #{match_id}: {e}")
            await interaction.channel.send(
                embed=EmbedBuilder.error("Save Failed", f"Database error: `{e}`")
            )

    # ------------------------------------------------------------------
    # /stats match
    # ------------------------------------------------------------------

    @stats_group.command(name="match", description="View the full parsed scoreboard for a match.")
    @app_commands.describe(match_id="The Matchroom ID to view stats for")
    async def stats_match(self, interaction: discord.Interaction, match_id: int):
        await interaction.response.defer()

        match = await self.bot.db.get_match(match_id)
        if not match:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Not Found", f"No Matchroom `#{match_id}`."),
                ephemeral=True,
            )
            return

        stat_rows = await self.bot.db.get_match_player_stats(match_id)
        if not stat_rows:
            await interaction.followup.send(
                embed=EmbedBuilder.info(
                    "No Stats Yet",
                    f"No scoreboard has been submitted for Matchroom `#{match_id}` yet.\n"
                    "A Captain can upload one with `/stats upload`.",
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"📊 Matchroom #{match_id} — Scoreboard",
            description=f"Map: **{match.get('map_played') or 'Unknown'}**",
            color=0xFF5500,
        )

        t_rows  = [r for r in stat_rows if r["team_side"] == "T"]
        ct_rows = [r for r in stat_rows if r["team_side"] == "CT"]

        for team_label, team_rows, emoji in (
            ("🟡 Terrorists", t_rows, "🟡"),
            ("🔵 Counter-Terrorists", ct_rows, "🔵"),
        ):
            if not team_rows:
                continue
            lines = []
            for r in team_rows:
                kd = _kd(r["kills"], r["deaths"])
                mention = f"<@{r['discord_id']}>" if r.get("discord_id") else f"`{r['display_name']}`"
                lines.append(
                    f"{mention} — "
                    f"**{r['kills']}** K / **{r['deaths']}** D / **{r['assists']}** A  "
                    f"(`KD {kd}`) — ⭐ {r['mvps']} MVP — Score **{r['score']}**"
                )
            embed.add_field(name=team_label, value="\n".join(lines), inline=False)

        conf = stat_rows[0].get("ocr_confidence", "unknown") if stat_rows else "unknown"
        embed.set_footer(text=f"OCR confidence: {conf} | Stats submitted via Gemini Vision")

        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /stats player
    # ------------------------------------------------------------------

    @stats_group.command(name="player", description="View career stats and last 5 matches for a player.")
    @app_commands.describe(member="The player to look up (defaults to you)")
    async def stats_player(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await interaction.response.defer()

        target = member or interaction.user
        player = await self.bot.db.get_player(target.id)

        if not player:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Not Registered", f"{target.mention} hasn't registered yet."),
                ephemeral=True,
            )
            return

        career = await self.bot.db.get_player_career_stats(target.id)
        recent = await self.bot.db.get_player_recent_match_stats(target.id, 5)

        elo = player["elo"]
        is_chal = await level_utils.is_challenger(self.bot.db, target.id, elo)

        embed = discord.Embed(
            title=f"📈 {target.display_name} — Stats",
            color=level_utils.get_embed_color(elo, is_chal),
        )

        icon = level_utils.resolve_icon(elo, is_chal)
        files = []
        if icon["thumbnail_url"]:
            embed.set_thumbnail(url=icon["thumbnail_url"])
            if icon["local_path"]:
                import discord as _d
                files.append(_d.File(icon["local_path"], filename=icon["filename"]))

        # Career block
        if career and career.get("matches_with_stats", 0) > 0:
            m = career["matches_with_stats"]
            k = career["total_kills"]
            d = career["total_deaths"]
            a = career["total_assists"]
            avg_k  = k / m
            avg_d  = d / m
            avg_a  = a / m
            kd_str = _kd(k, d)

            embed.add_field(
                name="🏆 Career (all matches with stats)",
                value=(
                    f"**Matches:** `{m}`\n"
                    f"**Total K/D/A:** `{k}` / `{d}` / `{a}`\n"
                    f"**K/D Ratio:** `{kd_str}`\n"
                    f"**Avg per match:** `{avg_k:.1f}K` / `{avg_d:.1f}D` / `{avg_a:.1f}A`\n"
                    f"**Total MVPs:** `{career['total_mvps']}`\n"
                    f"**Total Score:** `{career['total_score']}`"
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name="🏆 Career Stats",
                value="*No stats yet — waiting for a Captain to submit a scoreboard.*",
                inline=False,
            )

        # Last 5 matches block
        if recent:
            lines = []
            for r in recent:
                map_name = r.get("map_played") or "?"
                side_emoji = "🟡" if r["team_side"] == "T" else "🔵"
                kd = _kd(r["kills"], r["deaths"])
                lines.append(
                    f"{side_emoji} **{map_name}** — "
                    f"`{r['kills']}K/{r['deaths']}D/{r['assists']}A` "
                    f"KD `{kd}` ⭐ `{r['mvps']}` MVP"
                )
            embed.add_field(
                name=f"🕹️ Last {len(recent)} Matches",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="🕹️ Recent Matches",
                value="*No match stats found.*",
                inline=False,
            )

        embed.set_footer(text=f"Elo: {elo} | {level_utils.get_level_label(elo, is_chal)}")
        await interaction.followup.send(embed=embed, files=files)

    # ------------------------------------------------------------------
    # Preview embed (shown before Captain confirms)
    # ------------------------------------------------------------------

    def _build_preview_embed(self, match_id: int, ocr_data: dict, rows: list, confidence: str) -> discord.Embed:
        conf_color = {"high": 0x00C853, "medium": 0xFFC107, "low": 0xFF5252}.get(confidence, 0x607D8B)

        embed = discord.Embed(
            title=f"🔍 OCR Preview — Matchroom #{match_id}",
            description=(
                f"Gemini Vision parsed the screenshot with **{confidence}** confidence.\n"
                f"Map: **{ocr_data.get('map', 'Unknown')}**\n\n"
                "Check the stats below — if everything looks correct, click **Confirm**.\n"
                "If something's wrong (wrong numbers, missing players), click **Discard** and try a clearer screenshot."
            ),
            color=conf_color,
        )

        t_rows  = [r for r in rows if r["team_side"] == "T"]
        ct_rows = [r for r in rows if r["team_side"] == "CT"]

        for label, team_rows in (("🟡 Terrorists", t_rows), ("🔵 Counter-Terrorists", ct_rows)):
            if not team_rows:
                continue
            lines = []
            for r in team_rows:
                kd = _kd(r["kills"], r["deaths"])
                lines.append(
                    f"**{r['display_name']}** (`@{r['roblox_username']}`)\n"
                    f"  K `{r['kills']}` D `{r['deaths']}` A `{r['assists']}` "
                    f"KD `{kd}` ⭐ `{r['mvps']}` Score `{r['score']}`"
                )
            embed.add_field(name=label, value="\n".join(lines), inline=False)

        embed.set_footer(text="Stats will only be saved if you click Confirm below.")
        return embed


async def setup(bot):
    await bot.add_cog(Stats(bot))
