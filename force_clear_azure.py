#!/usr/bin/env python3
"""
Force clear all Azure SQL tables by dropping and recreating them.
This will completely reset the database.
"""
import pyodbc
from config_azure import azure_config

def force_clear_database():
    """Drop all tables and recreate schema."""
    print("🔥 FORCE CLEARING Azure SQL Database...")
    
    if not azure_config.is_azure_configured:
        print("❌ Azure SQL not configured")
        return
    
    try:
        conn = pyodbc.connect(azure_config.pyodbc_connection_string)
        cursor = conn.cursor()
        
        print("🗑️ Dropping all tables...")
        
        # Drop tables in reverse dependency order
        drop_tables = [
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
        
        for table in drop_tables:
            try:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
                print(f"✅ Dropped {table}")
            except Exception as e:
                print(f"⚠️ Could not drop {table}: {e}")
        
        conn.commit()
        print("✅ All tables dropped successfully!")
        print("📝 Database is now completely clean")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    print("⚠️  WARNING: This will DELETE ALL DATA in Azure SQL Database!")
    print("🔥 This action cannot be undone!")
    print("")
    
    confirm = input("Type 'DELETE ALL DATA' to confirm: ")
    if confirm == "DELETE ALL DATA":
        force_clear_database()
        print("")
        print("🎯 Next steps:")
        print("1. python3 migrate_to_azure.py")
        print("2. sed -i 's/from db import Database/from db_azure import AzureDatabase as Database/' main.py")
        print("3. sudo systemctl restart telegram-bot")
    else:
        print("❌ Operation cancelled")
