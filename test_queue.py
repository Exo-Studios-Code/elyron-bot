#!/usr/bin/env python3
"""
Quick test to verify queue_system.py loads correctly
"""

import sys
import asyncio

async def test_queue_cog():
    """Test if queue cog loads."""
    print("Testing queue_system cog...")
    
    try:
        # Import the module
        sys.path.insert(0, '.')
        from cogs import queue_system
        print("✅ queue_system module imported")
        
        # Check for classes
        assert hasattr(queue_system, 'MapVetoView'), "MapVetoView not found"
        print("✅ MapVetoView class exists")
        
        assert hasattr(queue_system, 'RosterSelectView'), "RosterSelectView not found"
        print("✅ RosterSelectView class exists")
        
        assert hasattr(queue_system, 'QueueView'), "QueueView not found"
        print("✅ QueueView class exists")
        
        assert hasattr(queue_system, 'QueueSystem'), "QueueSystem not found"
        print("✅ QueueSystem class exists")
        
        # Check QueueSystem has required methods
        qs = queue_system.QueueSystem
        assert hasattr(qs, 'queue'), "queue command group not found"
        print("✅ queue command group exists")
        
        print("\n🎉 All checks passed!")
        print("\nQueue commands should be:")
        print("  - !queue create")
        print("  - !queue join") 
        print("  - !queue leave")
        print("  - !queue status")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_queue_cog())
    sys.exit(0 if success else 1)
