#!/usr/bin/env python3
"""
Simple test script for Azure SQL Database connection.
Compatible with Ubuntu 22.04 and Python 3.10.
"""
import sys
import os

# Add current directory to path
sys.path.append('.')

try:
    print("🔍 Testing Azure SQL Database connection...")
    print(f"Python version: {sys.version}")
    print(f"Current directory: {os.getcwd()}")

    # Test imports
    print("📦 Testing imports...")
    import pyodbc
    print("✅ pyodbc imported successfully")

    import aioodbc
    print("✅ aioodbc imported successfully")

    import sqlalchemy
    print("✅ sqlalchemy imported successfully")

    # Test config import
    from config_azure import azure_config
    print("✅ config_azure imported successfully")

    # Show configuration
    print(f"\n⚙️ Configuration:")
    print(f"  Server: {azure_config.server}")
    print(f"  Database: {azure_config.database}")
    print(f"  Username: {azure_config.username}")
    print(f"  Use Azure: {azure_config.is_azure_configured}")
    print(f"  Use SQLite fallback: {azure_config.use_sqlite_fallback}")

    if azure_config.is_azure_configured:
        print("✅ Azure SQL configuration found")
    else:
        print("⚠️ Azure SQL not configured, will use SQLite fallback")

    # Test database class import
    from db_azure import AzureDatabase
    print("✅ AzureDatabase imported successfully")

    # Test basic connection
    print("\n🔌 Testing database connection...")
    db = AzureDatabase()
    print(f"✅ Database class initialized (use_azure: {db.use_azure})")

    print("\n🎉 Basic tests passed! Azure SQL setup is working.")
    print("\n💡 Next steps:")
    print("  1. Run: python3 test_azure_connection.py")
    print("  2. If successful: python3 migrate_to_azure.py")
    print("  3. Restart bot: sudo systemctl restart telegram-bot")

except ImportError as e:
    print(f"❌ Import error: {e}")
    print("\n🔧 Fix:")
    print("  sudo apt update")
    print("  sudo apt install -y python3-pyodbc python3-aioodbc python3-sqlalchemy")
    print("  pip3 install pyodbc aioodbc sqlalchemy")

except Exception as e:
    print(f"❌ Error: {e}")
    print("\n🔧 Check your .env file configuration")
