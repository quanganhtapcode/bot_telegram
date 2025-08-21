#!/usr/bin/env python3
"""
Clear all tables in Azure SQL Database before migration.
Run this to clean up existing data that might conflict.
"""
import asyncio
import pyodbc
from config_azure import azure_config

async def clear_all_tables():
    """Clear all tables in Azure SQL Database."""
    print("🧹 Clearing Azure SQL Database tables...")
    
    if not azure_config.is_azure_configured:
        print("❌ Azure SQL not configured")
        return
    
    try:
        # Connect to Azure SQL
        conn = pyodbc.connect(azure_config.pyodbc_connection_string)
        cursor = conn.cursor()
        
        # List of tables in dependency order (reverse for deletion)
        tables = [
            'payment_preferences',
            'pending_deductions', 
            'group_deductions',
            'group_debts',
            'bank_accounts',
            'exchange_rates',
            'wallet_adjustments',
            'expense_shares',
            'group_expenses',
            'expenses',
            'trip_members',
            'trips',
            'personal_expenses',
            'user_wallets',
            'users'
        ]
        
        print("🗑️ Deleting data from tables...")
        for table in tables:
            try:
                cursor.execute(f"DELETE FROM {table}")
                print(f"✅ Cleared {table}")
            except Exception as e:
                print(f"⚠️ Could not clear {table}: {e}")
        
        # Commit all deletions
        conn.commit()
        print("✅ All tables cleared successfully!")
        
    except Exception as e:
        print(f"❌ Error clearing tables: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    asyncio.run(clear_all_tables())
