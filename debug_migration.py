#!/usr/bin/env python3
"""
Debug migration issues by checking data relationships.
"""
import sqlite3
import pyodbc
from config_azure import azure_config

def debug_migration():
    """Debug migration data relationships."""
    print("🔍 Debugging migration data relationships...")
    
    # Check SQLite data
    sqlite_conn = sqlite3.connect('bot.db')
    cursor = sqlite_conn.cursor()
    
    print("\n📊 SQLite Data Analysis:")
    print("=" * 40)
    
    # Check user_wallets
    cursor.execute("SELECT id, user_id, currency FROM user_wallets")
    wallets = cursor.fetchall()
    print(f"👛 user_wallets: {len(wallets)} rows")
    for wallet in wallets:
        print(f"  Wallet ID={wallet[0]}, User ID={wallet[1]}, Currency={wallet[2]}")
    
    # Check wallet_adjustments
    cursor.execute("SELECT id, wallet_id, delta_amount, reason FROM wallet_adjustments")
    adjustments = cursor.fetchall()
    print(f"🔧 wallet_adjustments: {len(adjustments)} rows")
    for adj in adjustments:
        print(f"  Adjustment ID={adj[0]}, Wallet ID={adj[1]}, Amount={adj[2]}, Reason={adj[3]}")
    
    # Check FK relationships
    cursor.execute("""
        SELECT wa.id, wa.wallet_id, uw.id as wallet_exists
        FROM wallet_adjustments wa
        LEFT JOIN user_wallets uw ON wa.wallet_id = uw.id
    """)
    fk_check = cursor.fetchall()
    print(f"\n🔗 FK Relationship Check:")
    for row in fk_check:
        status = "✅ OK" if row[2] else "❌ BROKEN FK"
        print(f"  Adjustment {row[0]} → Wallet {row[1]} {status}")
    
    sqlite_conn.close()
    
    # Check Azure SQL data
    if azure_config.is_azure_configured:
        print(f"\n📊 Azure SQL Data Analysis:")
        print("=" * 40)
        
        try:
            azure_conn = pyodbc.connect(azure_config.pyodbc_connection_string)
            cursor = azure_conn.cursor()
            
            # Check user_wallets in Azure
            cursor.execute("SELECT id, user_id, currency FROM user_wallets")
            azure_wallets = cursor.fetchall()
            print(f"👛 Azure user_wallets: {len(azure_wallets)} rows")
            for wallet in azure_wallets:
                print(f"  Wallet ID={wallet[0]}, User ID={wallet[1]}, Currency={wallet[2]}")
            
            azure_conn.close()
            
        except Exception as e:
            print(f"❌ Azure connection error: {e}")
    
    print(f"\n💡 Migration Strategy:")
    print("1. Migrate users first ✅")
    print("2. Migrate user_wallets second ✅") 
    print("3. Migrate wallet_adjustments third (FK depends on user_wallets)")
    print("4. Check wallet_id references exist in target table")

if __name__ == "__main__":
    debug_migration()
