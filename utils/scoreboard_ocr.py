"""
Scoreboard OCR — Blox Strike
Uses Gemini Vision (google-genai) to extract per-player statistics from a
Blox Strike scoreboard screenshot uploaded by a Lobby Captain.

Scoreboard layout (confirmed from screenshot):
  - Two teams: Terrorists (gold rows) and Counter-Terrorists (grey rows)
  - Columns: Money | Kills | Deaths | Assists | MVPs | Score
  - Player name format: DisplayName (@RobloxUsername)
  - No HS% column visible — we ask Gemini to note if it ever appears

The prompt is intentionally strict and JSON-only so we can parse it
reliably. Gemini is told to return 0 for any value it cannot read clearly
rather than guessing, which is safer than a wrong number in the DB.
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model — gemini-2.0-flash is fast, cheap, and Vision-capable
# ---------------------------------------------------------------------------
_MODEL = "gemini-2.0-flash"

_PROMPT = """You are analyzing a Blox Strike (Roblox FPS) scoreboard screenshot.

Extract EVERY player row visible. The scoreboard has two teams:
- TERRORISTS (gold/yellow background rows, shown first)
- COUNTER-TERRORISTS (dark/grey background rows, shown second)

Each player row contains:
  - Player name in format:  DisplayName (@RobloxUsername)
  - Money (e.g. $16,000) — extract as integer, drop $ and commas
  - Kills (integer)
  - Deaths (integer)
  - Assists (integer)
  - MVPs (integer)
  - Score (integer)

If a column value is unclear or missing, use 0. Do NOT guess.

Return ONLY valid JSON, no markdown, no explanation, no backticks.
Schema:
{
  "terrorists": [
    {
      "display_name": "kamarad121212",
      "roblox_username": "kamarad121212",
      "money": 16000,
      "kills": 0,
      "deaths": 0,
      "assists": 0,
      "mvps": 0,
      "score": 0
    }
  ],
  "counter_terrorists": [
    ...same structure...
  ],
  "map": "Oasis",
  "parse_confidence": "high"
}

For parse_confidence use: "high" if everything was clear, "medium" if some
values were ambiguous, "low" if the image was hard to read.
"""


class ScoreboardOCR:
    """
    Wraps the Gemini Vision API call and normalises the result into
    a list of player stat dicts ready to be written to the database.
    """

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to your .env file.\n"
                "Get a free key at https://aistudio.google.com/app/apikey"
            )
        self._client = genai.Client(api_key=api_key)

    async def parse_screenshot(
        self, image_bytes: bytes, mime_type: str = "image/png"
    ) -> Tuple[Optional[Dict], str]:
        """
        Send the screenshot to Gemini Vision and parse the JSON response.

        Returns:
            (parsed_dict, confidence)  on success
            (None, error_message)      on failure
        """
        try:
            image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            response = await self._client.aio.models.generate_content(
                model=_MODEL,
                contents=[_PROMPT, image_part],
                config=types.GenerateContentConfig(
                    temperature=0.0,   # deterministic — we want exact reads, not creative output
                    max_output_tokens=2048,
                ),
            )

            raw_text = response.text.strip()

            # Strip any accidental markdown fences Gemini adds despite instructions
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)

            data = json.loads(raw_text)

            # Basic validation
            if "terrorists" not in data or "counter_terrorists" not in data:
                return None, "Gemini returned JSON but missing team keys — bad screenshot?"

            confidence = data.get("parse_confidence", "unknown")
            logger.info(f"ScoreboardOCR: parsed {len(data['terrorists'])}T + {len(data['counter_terrorists'])}CT players, confidence={confidence}")
            return data, confidence

        except json.JSONDecodeError as e:
            logger.error(f"ScoreboardOCR: JSON parse failed: {e}\nRaw: {raw_text[:500]}")
            return None, f"Gemini response wasn't valid JSON: {e}"
        except Exception as e:
            logger.error(f"ScoreboardOCR: API error: {e}")
            return None, str(e)

    def normalise(self, ocr_data: Dict, match_id: int) -> List[Dict]:
        """
        Flatten the OCR result into a list of per-player stat dicts, each
        with the match_id attached and team side noted.

        {
            'match_id': int,
            'roblox_username': str,
            'display_name': str,
            'team_side': 'T' | 'CT',
            'kills': int,
            'deaths': int,
            'assists': int,
            'mvps': int,
            'score': int,
            'money': int,
        }
        """
        results = []
        for player in ocr_data.get("terrorists", []):
            results.append(self._build_row(player, "T", match_id))
        for player in ocr_data.get("counter_terrorists", []):
            results.append(self._build_row(player, "CT", match_id))
        return results

    @staticmethod
    def _build_row(player: Dict, side: str, match_id: int) -> Dict:
        return {
            "match_id":       match_id,
            "roblox_username": player.get("roblox_username", "").strip().lower(),
            "display_name":   player.get("display_name", "").strip(),
            "team_side":      side,
            "kills":          int(player.get("kills", 0)),
            "deaths":         int(player.get("deaths", 0)),
            "assists":        int(player.get("assists", 0)),
            "mvps":           int(player.get("mvps", 0)),
            "score":          int(player.get("score", 0)),
            "money":          int(player.get("money", 0)),
        }
