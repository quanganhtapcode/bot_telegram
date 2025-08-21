"""
Test script to verify Azure SQL Database connection.
Run this to make sure your Azure SQL setup is working.
"""
import asyncio
from db_azure import AzureDatabase

async def test_azure_connection():
    """Test Azure SQL Database connection."""
    print("Testing Azure SQL Database connection...")

    try:
        db = AzureDatabase()

        # Test basic connection
        print("1. Testing connection...")
        conn = await db.get_connection()
        print("✅ Connection successful")

        # Test table creation
        print("2. Testing table creation...")
        await db.create_tables()
        print("✅ Tables created successfully")

        # Test user creation
        print("3. Testing user creation...")
        user = await db.create_or_update_user(123456789, "Test User")
        print(f"✅ User created: {user.name}")

        # Test user wallets
        print("4. Testing wallet operations...")
        wallets = await db.get_user_wallets(user.id)
        print(f"✅ User has {len(wallets)} wallets")

        print("\n🎉 All tests passed! Azure SQL Database is working correctly.")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        print("\nTroubleshooting:")
        print("1. Check your .env file has correct Azure SQL settings")
        print("2. Make sure Azure SQL Database is created and accessible")
        print("3. Check firewall rules allow your IP")
        print("4. Verify username/password are correct")

if __name__ == "__main__":
    asyncio.run(test_azure_connection())
