"""
ELO calculation system for CS2 League Bot.
Implements individual player ELO rating calculations.
"""

import math
from typing import Tuple
from utils.config import Config

class ELOCalculator:
    """Handles all ELO calculations for individual players."""
    
    @staticmethod
    def calculate_expected_score(player_rating: int, opponent_team_avg_rating: int) -> float:
        """
        Calculate expected score for a player against an opponent team's average.
        """
        return 1 / (1 + math.pow(10, (opponent_team_avg_rating - player_rating) / 400))
    
    @staticmethod
    def calculate_new_rating(current_rating: int, expected: float, 
                            actual: float, k_factor: int) -> int:
        """Calculate new ELO rating after a match."""
        change = k_factor * (actual - expected)
        new_rating = current_rating + change
        return max(0, round(new_rating))
    
    @staticmethod
    def calculate_player_elo_change(player_elo: int, opponent_avg_elo: int, won: bool) -> int:
        """
        Calculate the specific ELO change for one player based on match result.
        
        Args:
            player_elo: Hráčovo aktuální ELO
            opponent_avg_elo: Průměrné ELO soupeřova týmu
            won: True pokud hráč vyhrál, False pokud prohrál
            
        Returns:
            elo_change: Počet bodů, o které se ELO změní
        """
        expected = ELOCalculator.calculate_expected_score(player_elo, opponent_avg_elo)
        actual = 1.0 if won else 0.0
        
        k_factor = Config.calculate_k_factor(player_elo)
        new_rating = ELOCalculator.calculate_new_rating(player_elo, expected, actual, k_factor)
        
        return new_rating - player_elo

    @staticmethod
    def is_upset(player_elo: int, opponent_avg_elo: int) -> bool:
        """Určí, zda šlo o překvapení (hráč s nižším ELO porazil silnější tým)."""
        return player_elo < opponent_avg_elo

    @staticmethod
    def calculate_match_elo(winner_elo: int, loser_elo: int) -> Tuple[int, int, int]:
        """
        Zachováváme tuto metodu pro kompatibilitu s lobby/týmovým ELO průměrem, 
        pokud bys ji potřeboval pro zobrazení v Matchroomu.
        """
        winner_expected = ELOCalculator.calculate_expected_score(winner_elo, loser_elo)
        loser_expected = ELOCalculator.calculate_expected_score(loser_elo, winner_elo)
        
        winner_k = Config.calculate_k_factor(winner_elo)
        loser_k = Config.calculate_k_factor(loser_elo)
        
        new_winner_elo = ELOCalculator.calculate_new_rating(winner_elo, winner_expected, 1.0, winner_k)
        new_loser_elo = ELOCalculator.calculate_new_rating(loser_elo, loser_expected, 0.0, loser_k)
        
        return new_winner_elo, new_loser_elo, (new_winner_elo - winner_elo)

    @staticmethod
    def calculate_win_probability(team1_elo: int, team2_elo: int) -> Tuple[float, float]:
        """
        Vrátí pravděpodobnost výhry (0.0 - 1.0) pro oba týmy na základě rozdílu ELO.
        Používá se v queue_system.py pro zobrazení predikce před zápasem (Matchroom embed).

        NOTE: Tato metoda v originálním kódu chyběla, ale queue_system.py ji volal -
        způsobovalo by to AttributeError při vytváření Matchroomu. Doplněno.
        """
        team1_prob = ELOCalculator.calculate_expected_score(team1_elo, team2_elo)
        team2_prob = 1.0 - team1_prob
        return team1_prob, team2_prob

    @staticmethod
    def can_players_match(elo1: int, elo2: int) -> bool:
        """Determine if two players can be matched (např. pro Solo/Duo queue)."""
        return abs(elo1 - elo2) <= Config.ELO_MATCH_RANGE
