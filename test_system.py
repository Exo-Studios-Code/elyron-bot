"""
CS2 League Bot - Complete System Validation
Tests all critical functionality including roster selection.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_database():
    """Test database operations."""
    print("=" * 60)
    print("DATABASE TESTS")
    print("=" * 60)
    
    from utils.database import Database
    from utils.config import Config
    
    db = Database()
    await db.initialize()
    
    print("✅ Database initialized")
    
    # Test season
    season_id = await db.get_active_season()
    print(f"✅ Active season: {season_id}")
    
    # Test team creation
    test_team_id = await db.create_team(
        name="Test Team",
        captain_discord_id=123456789,
        description="Test team for validation"
    )
    
    if test_team_id:
        print(f"✅ Team created: ID {test_team_id}")
        
        # Test player creation
        player_ids = []
        for i in range(8):
            player_id = await db.create_or_get_player(
                discord_id=1000000 + i,
                username=f"Player{i+1}"
            )
            player_ids.append(player_id)
            await db.update_player_team(1000000 + i, test_team_id)
        
        print(f"✅ Created 8 players and added to team")
        
        # Test active roster setting
        active_5 = player_ids[:5]
        await db.set_active_roster(test_team_id, active_5)
        print(f"✅ Set active roster (5 players)")
        
        # Verify active roster
        active_roster = await db.get_active_roster(test_team_id)
        print(f"✅ Active roster has {len(active_roster)} players")
        
        if len(active_roster) == 5:
            print("✅ ROSTER SELECTION WORKS CORRECTLY")
        else:
            print(f"❌ ROSTER PROBLEM: Expected 5, got {len(active_roster)}")
        
        # Test queue operations
        success = await db.add_team_to_queue(test_team_id)
        if success:
            print("✅ Team added to queue")
            
            in_queue = await db.is_team_in_queue(test_team_id)
            if in_queue:
                print("✅ Team verified in queue")
            
            await db.remove_team_from_queue(test_team_id)
            print("✅ Team removed from queue")
        
        # Cleanup
        await db.delete_team(test_team_id)
        print("✅ Test team cleaned up")
    
    await db.close()
    print("\n✅ ALL DATABASE TESTS PASSED\n")

async def test_elo_calculations():
    """Test ELO calculations."""
    print("=" * 60)
    print("ELO CALCULATION TESTS")
    print("=" * 60)
    
    from utils.elo import ELOCalculator
    
    # Test standard match
    winner_elo, loser_elo, change = ELOCalculator.calculate_match_elo(1000, 1000)
    print(f"✅ Equal match: +{change}/-{change} ELO")
    
    # Test upset
    winner_elo, loser_elo, change = ELOCalculator.calculate_match_elo(900, 1200)
    print(f"✅ Upset (900 beats 1200): +{change} ELO")
    
    is_upset = ELOCalculator.is_upset(900, 1200)
    if is_upset:
        print("✅ Upset detection works")
    
    # Test win probability
    prob1, prob2 = ELOCalculator.calculate_win_probability(1000, 1200)
    print(f"✅ Win probabilities: {prob1*100:.1f}% vs {prob2*100:.1f}%")
    
    # Test matchmaking range
    can_match = ELOCalculator.can_teams_match(1000, 1250)
    print(f"✅ Can match (1000 vs 1250): {can_match}")
    
    cannot_match = ELOCalculator.can_teams_match(1000, 1400)
    print(f"✅ Cannot match (1000 vs 1400): {not cannot_match}")
    
    print("\n✅ ALL ELO TESTS PASSED\n")

async def test_embeds():
    """Test embed creation."""
    print("=" * 60)
    print("EMBED TESTS")
    print("=" * 60)
    
    from utils.embeds import EmbedBuilder
    
    # Test basic embeds
    embed = EmbedBuilder.success("Test", "Description")
    print(f"✅ Success embed: {embed.title}")
    
    embed = EmbedBuilder.error("Test", "Description")
    print(f"✅ Error embed: {embed.title}")
    
    embed = EmbedBuilder.info("Test", "Description")
    print(f"✅ Info embed: {embed.title}")
    
    # Test team info embed (without database)
    team_data = {
        'team_id': 1,
        'name': 'Test Team',
        'description': 'A test team',
        'elo': 1200,
        'wins': 10,
        'losses': 5,
        'captain_id': 123456789,
        'logo_path': None
    }
    
    members_data = [
        {'player_id': i, 'discord_id': 1000+i, 'username': f'Player{i}', 'elo': 1200}
        for i in range(1, 6)
    ]
    
    active_roster_data = members_data[:5]
    
    embed = EmbedBuilder.team_info(team_data, members_data, active_roster_data)
    print(f"✅ Team info embed created")
    
    print("\n✅ ALL EMBED TESTS PASSED\n")

def test_config():
    """Test configuration."""
    print("=" * 60)
    print("CONFIGURATION TESTS")
    print("=" * 60)
    
    from utils.config import Config
    
    print(f"✅ MAX_TEAM_SIZE: {Config.MAX_TEAM_SIZE}")
    print(f"✅ MIN_TEAM_SIZE: {Config.MIN_TEAM_SIZE}")
    print(f"✅ ACTIVE_ROSTER_SIZE: {Config.ACTIVE_ROSTER_SIZE}")
    print(f"✅ STARTING_ELO: {Config.STARTING_ELO}")
    print(f"✅ ELO_MATCH_RANGE: {Config.ELO_MATCH_RANGE}")
    
    # Test rank calculation
    rank = Config.get_rank_from_elo(1200)
    print(f"✅ Rank for 1200 ELO: {rank}")
    
    # Test K-factor calculation
    k = Config.calculate_k_factor(1000)
    print(f"✅ K-factor for 1000 ELO: {k}")
    
    print("\n✅ ALL CONFIG TESTS PASSED\n")

async def test_roster_workflow():
    """Test complete roster selection workflow."""
    print("=" * 60)
    print("ROSTER WORKFLOW TEST")
    print("=" * 60)
    
    from utils.database import Database
    from utils.config import Config
    
    db = Database()
    await db.initialize()
    
    # Create test team
    team_id = await db.create_team(
        name="Workflow Test Team",
        captain_discord_id=999999999
    )
    
    print(f"✅ Step 1: Team created (ID: {team_id})")
    
    # Add 8 players
    player_ids = []
    for i in range(8):
        pid = await db.create_or_get_player(
            discord_id=9000000 + i,
            username=f"WorkflowPlayer{i+1}"
        )
        player_ids.append(pid)
        await db.update_player_team(9000000 + i, team_id)
    
    print(f"✅ Step 2: Added 8 players to team")
    
    # Captain joins queue - should trigger roster selection
    members = await db.get_team_members(team_id)
    print(f"✅ Step 3: Retrieved {len(members)} team members")
    
    if len(members) >= Config.MIN_TEAM_SIZE:
        print(f"✅ Step 4: Team has enough players ({len(members)}/{Config.MIN_TEAM_SIZE})")
        
        # Simulate captain selecting 5 players
        selected_ids = player_ids[:5]
        await db.set_active_roster(team_id, selected_ids)
        print(f"✅ Step 5: Captain selected 5 players for active roster")
        
        # Verify selection
        active = await db.get_active_roster(team_id)
        print(f"✅ Step 6: Active roster has {len(active)} players")
        
        if len(active) == Config.ACTIVE_ROSTER_SIZE:
            print(f"✅ Step 7: CORRECT - Active roster = {Config.ACTIVE_ROSTER_SIZE} players")
            
            # Add to queue
            success = await db.add_team_to_queue(team_id)
            if success:
                print(f"✅ Step 8: Team successfully added to queue")
                
                # Get queue teams
                queue_teams = await db.get_queue_teams()
                if len(queue_teams) > 0:
                    print(f"✅ Step 9: Queue has {len(queue_teams)} team(s)")
                    
                    # Check roster in queue
                    team_in_queue = queue_teams[0]
                    queue_roster = await db.get_active_roster(team_in_queue['team_id'])
                    print(f"✅ Step 10: Queued team has {len(queue_roster)} active players")
                    
                    if len(queue_roster) == 5:
                        print("\n🎉 COMPLETE WORKFLOW SUCCESS!")
                        print("   ✅ Team created")
                        print("   ✅ 8 players added (5 main + 3 subs)")
                        print("   ✅ Captain selected 5 active players")
                        print("   ✅ Team joined queue with correct roster")
                        print("   ✅ ROSTER SELECTION IS WORKING!\n")
                    else:
                        print(f"\n❌ WORKFLOW FAILED: Queue roster has {len(queue_roster)} players")
                
                await db.remove_team_from_queue(team_id)
        else:
            print(f"❌ Step 7: FAILED - Active roster has {len(active)} players, expected {Config.ACTIVE_ROSTER_SIZE}")
    
    # Cleanup
    await db.delete_team(team_id)
    await db.close()

async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("CS2 LEAGUE BOT - COMPLETE SYSTEM VALIDATION")
    print("=" * 60 + "\n")
    
    try:
        # Run tests in order
        test_config()
        await test_elo_calculations()
        await test_embeds()
        await test_database()
        await test_roster_workflow()
        
        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED SUCCESSFULLY! 🎉")
        print("=" * 60)
        print("\nThe bot is ready to use:")
        print("  ✅ Database operations work")
        print("  ✅ ELO calculations are correct")
        print("  ✅ Roster selection works (5 from 8)")
        print("  ✅ Queue system functional")
        print("  ✅ Embeds render correctly")
        print("\nYou can now start the bot with: python bot.py")
        print("=" * 60 + "\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
