"""
Database Migration Script
Migrates existing database to support roster management and queue messages.

Run this ONCE after updating the bot code.
Usage: python migrate_db.py
"""

import sqlite3
import sys
from pathlib import Path

def migrate_database():
    """Add new columns and tables for roster management."""
    
    db_path = Path("data/cs2_league.db")
    
    if not db_path.exists():
        print("❌ Database not found at data/cs2_league.db")
        print("   If this is a fresh install, just run the bot - no migration needed!")
        return False
    
    print("🔄 Starting database migration...")
    print(f"📁 Database: {db_path}")
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Check if migration already done
        cursor.execute("PRAGMA table_info(players)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'is_active_roster' in columns:
            print("✅ Migration already completed!")
            print("   Database is up to date.")
            conn.close()
            return True
        
        print("\n📝 Adding new columns and tables...")
        
        # 1. Add is_active_roster to players table
        print("   • Adding is_active_roster to players table...")
        try:
            cursor.execute("""
                ALTER TABLE players 
                ADD COLUMN is_active_roster BOOLEAN DEFAULT 0
            """)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
            print("     (already exists, skipping)")
        
        # 2. Add player statistics columns
        print("   • Adding player statistics columns...")
        stat_columns = [
            ("individual_rating", "REAL DEFAULT 0.0"),
            ("kills", "INTEGER DEFAULT 0"),
            ("deaths", "INTEGER DEFAULT 0"),
            ("assists", "INTEGER DEFAULT 0"),
            ("mvp_stars", "INTEGER DEFAULT 0"),
            ("matches_played", "INTEGER DEFAULT 0")
        ]
        
        for col_name, col_type in stat_columns:
            try:
                cursor.execute(f"ALTER TABLE players ADD COLUMN {col_name} {col_type}")
                print(f"     ✓ Added {col_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
                print(f"     (  {col_name} already exists)")
        
        # 3. Create queue_messages table
        print("   • Creating queue_messages table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS queue_messages (
                message_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 4. Add map_played column to matches
        print("   • Adding map_played to matches table...")
        try:
            cursor.execute("ALTER TABLE matches ADD COLUMN map_played TEXT")
            print("     ✓ Added map_played")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
            print("     (map_played already exists)")
            
        # 5. Create map_vetos table
        print("   • Creating map_vetos table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS map_vetos (
                veto_id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                map_name TEXT NOT NULL,
                veto_order INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(match_id),
                FOREIGN KEY (team_id) REFERENCES teams(team_id)
            )
        """)
        
        # 6. Add Discord integration fields to teams
        print("   • Adding Discord fields to teams table...")
        discord_fields = [
            ("discord_role_id", "INTEGER"),
            ("discord_category_id", "INTEGER"),
            ("discord_text_channel_id", "INTEGER"),
            ("discord_voice_channel_id", "INTEGER")
        ]
        
        for field_name, field_type in discord_fields:
            try:
                cursor.execute(f"ALTER TABLE teams ADD COLUMN {field_name} {field_type}")
                print(f"     ✓ Added {field_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
                print(f"     ({field_name} already exists)")
        
        # 7. Add FACEIT/server fields to matches
        print("   • Adding server integration fields to matches...")
        server_fields = [
            ("faceit_match_url", "TEXT"),
            ("server_info", "TEXT")
        ]
        
        for field_name, field_type in server_fields:
            try:
                cursor.execute(f"ALTER TABLE matches ADD COLUMN {field_name} {field_type}")
                print(f"     ✓ Added {field_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
                print(f"     ({field_name} already exists)")
        
        # Commit changes
        conn.commit()
        
        print("\n✅ Migration completed successfully!")
        print("\n📊 Summary:")
        print("   • Added 'is_active_roster' column to players")
        print("   • Added player statistics columns (K/D/A, rating, MVP)")
        print("   • Created 'queue_messages' table")
        print("   • Added 'map_played' column to matches")
        print("   • Created 'map_vetos' table")
        print("   • Added Discord integration fields to teams")
        print("   • Added FACEIT/server fields to matches")
        print("\n🎉 Database is now ready for:")
        print("   ✓ Active roster selection (5 from 8 players)")
        print("   ✓ Individual player ratings and stats")
        print("   ✓ Persistent queue embeds with buttons")
        print("   ✓ Interactive map veto system (BO1)")
        print("   ✓ Discord roles, channels & categories per team")
        print("   ✓ FACEIT Hub integration")
        
        conn.close()
        return True
        
    except sqlite3.Error as e:
        print(f"\n❌ Migration failed: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return False

def backup_database():
    """Create a backup before migration."""
    from datetime import datetime
    import shutil
    
    db_path = Path("data/cs2_league.db")
    if not db_path.exists():
        return True
    
    backup_dir = Path("backups")
    backup_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"cs2_league_pre_migration_{timestamp}.db"
    
    try:
        shutil.copy2(db_path, backup_path)
        print(f"✅ Backup created: {backup_path}")
        return True
    except Exception as e:
        print(f"⚠️  Backup failed: {e}")
        print("   Continue anyway? (y/n): ", end='')
        return input().lower() == 'y'

def main():
    print("=" * 60)
    print("CS2 League Bot - Database Migration")
    print("=" * 60)
    print()
    print("This script will update your database to support:")
    print("  • Active roster selection (5 players from 8)")
    print("  • Persistent queue embed messages")
    print()
    
    # Create backup
    print("📦 Creating backup...")
    if not backup_database():
        print("❌ Aborting migration.")
        sys.exit(1)
    
    print()
    
    # Run migration
    success = migrate_database()
    
    print()
    print("=" * 60)
    
    if success:
        print("✅ Migration complete!")
        print("\nNext steps:")
        print("  1. Start your bot: python bot.py")
        print("  2. Create queue embed: !queue create")
        print("  3. Set team rosters: !team roster")
        sys.exit(0)
    else:
        print("❌ Migration failed!")
        print("\nPlease check the error messages above.")
        print("If you need help, check the logs or documentation.")
        sys.exit(1)

if __name__ == "__main__":
    main()
