# CS2 League Bot

A production-ready Discord bot for managing competitive CS2 leagues with an ELO-based ranking system.

## Features

### 🎮 Core System
- **Open Queue System**: Unlimited teams can participate in ranked matchmaking
- **ELO-Based Ranking**: Proper ELO calculations with K-factor adjustments
- **Seasonal Play**: 6-month seasons with full statistics archival
- **Rank Tiers**: Bronze → Silver → Gold → Platinum → Diamond → Master → Elite

### 🛡️ Team Management
- Create custom teams with names, logos, and descriptions
- Team captains with full roster control
- Player invitation system
- Team statistics and match history
- Up to 5 players per team

### ⚔️ Match System
- Automated matchmaking based on ELO proximity
- Dual-confirmation system (prevents fake results)
- Both captains must confirm match results
- Detailed match history
- Upset detection and bonus ELO

### 📊 Statistics & Leaderboards
- Team and player leaderboards
- Individual player statistics
- Match history tracking
- Real-time ELO updates
- Win/loss records and win rates

### 🔧 Admin Tools
- Season management and resets
- Manual ELO adjustments
- Team removal
- Queue management
- Broadcast messaging to all captains

## Installation

### Prerequisites
- Python 3.8 or higher
- Discord Bot Token ([Create one here](https://discord.com/developers/applications))

### Setup Steps

1. **Clone the repository**
```bash
git clone <repository-url>
cd cs2_league_bot
```

2. **Create virtual environment** (recommended)
```bash
python -m venv venv

# Activate on Windows
venv\Scripts\activate

# Activate on Linux/Mac
source venv/bin/activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure the bot**
```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your bot token
# DISCORD_TOKEN=your_actual_bot_token_here
```

5. **Run the bot**
```bash
python bot.py
```

## Configuration

### Environment Variables (.env)
```env
DISCORD_TOKEN=your_bot_token_here
COMMAND_PREFIX=!
ADMIN_ROLE_IDS=123456789,987654321  # Optional: comma-separated role IDs
```

### Bot Settings (utils/config.py)
You can customize various settings:
- Starting ELO (default: 1000)
- K-factors for different ELO ranges
- Rank thresholds
- Team size limits
- Season duration
- Match confirmation timeout
- ELO matchmaking range

## Usage Guide

### For Players

#### Creating a Team
```
!team create Team Name
!team description We are a competitive CS2 team
!team logo (attach image)
```

#### Joining a Team
```
!team invite @player
!team join Team Name
```

#### Playing Matches
1. Captain joins queue: `!queue join`
2. Bot automatically matches teams
3. Play your match
4. Winner reports: `!match report 123 win`
5. Loser confirms: `!match confirm 123`
6. ELO updates automatically!

#### Viewing Stats
```
!rank                    # Your personal stats
!rank @player           # Another player's stats
!team info              # Your team's info
!leaderboard teams      # Top teams
!leaderboard players    # Top players
```

### For Administrators

#### Season Management
```
!admin season info           # View current season
!admin season reset          # End season and start new one
!admin season confirm-reset  # Confirm the reset
```

#### Team Management
```
!admin removeteam Team Name  # Remove a team
!admin forceelo Team 1500    # Manually set team ELO
!admin clearqueue            # Clear matchmaking queue
```

#### Communication
```
!admin broadcast Important announcement for all teams!
```

## ELO System

### How ELO Works
- **Starting ELO**: 1000
- **K-Factor**: Determines how much ELO changes per match
  - Low ELO (<1000): K=40 (faster movement)
  - Normal ELO (1000-2000): K=32
  - High ELO (>2000): K=24 (more stable)

### Rank Tiers
| Rank | ELO Range |
|------|-----------|
| Bronze | 0 - 799 |
| Silver | 800 - 999 |
| Gold | 1000 - 1199 |
| Platinum | 1200 - 1399 |
| Diamond | 1400 - 1599 |
| Master | 1600 - 1799 |
| Elite | 1800+ |

### Matchmaking
- Teams are matched within ±300 ELO
- Queue checks every 30 seconds
- Closest ELO matches are prioritized
- Upsets (lower ELO wins) = more ELO gained

## Database Schema

The bot uses SQLite with the following main tables:
- `seasons` - Season information
- `teams` - Team data and statistics
- `players` - Player data and statistics
- `matches` - Match records and results
- `queue` - Current matchmaking queue
- `team_invitations` - Pending team invitations
- `season_archives` - Historical season data

## Security Features

### Anti-Cheat Measures
1. **Dual Confirmation**: Both captains must confirm match results
2. **Captain-Only Actions**: Only captains can report matches or join queue
3. **Team Validation**: Minimum team size required to play
4. **Match Integrity**: Prevents duplicate reports and fake results

### Data Integrity
- Foreign key constraints
- Transaction safety
- Automatic rollback on errors
- Comprehensive logging

## File Structure

```
cs2_league_bot/
├── bot.py                  # Main entry point
├── requirements.txt        # Python dependencies
├── .env.example           # Environment template
├── utils/
│   ├── config.py          # Configuration settings
│   ├── database.py        # Database operations
│   ├── elo.py            # ELO calculations
│   ├── embeds.py         # Discord embed builders
│   └── logger.py         # Logging setup
├── cogs/
│   ├── team_management.py # Team commands
│   ├── queue_system.py    # Queue & matchmaking
│   ├── match_system.py    # Match reporting
│   ├── leaderboard.py     # Rankings & stats
│   ├── admin.py          # Admin commands
│   └── help_command.py    # Custom help
└── data/
    ├── cs2_league.db      # SQLite database
    └── team_logos/        # Team logo storage
```

## Troubleshooting

### Bot won't start
- Check your bot token in `.env`
- Ensure all dependencies are installed: `pip install -r requirements.txt`
- Check logs in `logs/bot.log`

### Commands not working
- Verify the command prefix (default: `!`)
- Check bot permissions in Discord server
- Ensure bot has "Message Content Intent" enabled in Discord Developer Portal

### Database errors
- Delete `data/cs2_league.db` to reset (WARNING: loses all data)
- Check file permissions on the `data/` directory

### Match confirmation issues
- Both captains must confirm within the timeout period
- Only captains can report/confirm matches
- Match ID must be correct

## Advanced Features

### Custom K-Factors
The bot automatically adjusts K-factors based on ELO:
- Helps new teams move quickly to their skill level
- Stabilizes high-ELO teams to prevent volatility
- Controls ELO inflation over time

### Season Archives
When a season ends:
- All team/player data is archived
- Top 100 teams and players are saved
- Full ELO reset for fresh start
- Previous season data retrievable by admins

### Matchmaking Algorithm
1. Teams join queue with timestamp
2. Every 30 seconds, bot checks for matches
3. Teams sorted by ELO
4. Best matches within ±300 ELO created
5. Teams removed from queue
6. Captains notified via DM

## Support & Development

### Getting Help
- Check the in-bot help: `!help`
- Review the documentation above
- Check logs in `logs/bot.log`

### Contributing
This is a production-ready bot with modular architecture designed for easy expansion:
- Add new cogs in `cogs/`
- Extend database in `utils/database.py`
- Modify settings in `utils/config.py`

### Future Enhancements
Potential features to add:
- Map vetoing system
- Server integration (auto-create game servers)
- Advanced statistics (K/D tracking, map stats)
- Team tournament brackets
- Role-based permissions (managers, coaches)
- Multi-region support
- Integration with CS2 game servers

## License

This project is provided as-is for educational and competitive gaming purposes.

## Credits

Developed for competitive CS2 league management with a focus on fairness, scalability, and ease of use.

---

**For additional support or feature requests, contact your server administrator.**
