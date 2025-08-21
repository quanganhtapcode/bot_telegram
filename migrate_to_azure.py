"""
Migration script to transfer data from SQLite to Azure SQL Database.
Run this script after setting up Azure SQL Database.
"""
import asyncio
import logging
import sqlite3
import pyodbc
from decimal import Decimal
from datetime import datetime
from typing import List, Tuple, Any

from config_azure import azure_config
from db import Database

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SQLiteToAzureMigrator:
    """Migrates data from SQLite to Azure SQL Database."""
    
    def __init__(self):
        self.sqlite_db = Database(azure_config.sqlite_path)
        
        if not azure_config.is_azure_configured:
            raise ValueError("Azure SQL Database not configured. Check environment variables.")
        
        self.azure_connection_string = azure_config.pyodbc_connection_string
        logger.info(f"Migrating from {azure_config.sqlite_path} to Azure SQL Database")
    
    def get_azure_connection(self):
        """Get Azure SQL Database connection."""
        try:
            conn = pyodbc.connect(self.azure_connection_string)
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to Azure SQL: {e}")
            raise
    
    def get_sqlite_connection(self):
        """Get SQLite database connection."""
        return sqlite3.connect(azure_config.sqlite_path)
    
    async def migrate_all_data(self):
        """Migrate all data from SQLite to Azure SQL."""
        logger.info("Starting migration...")
        
        try:
            # Create Azure tables first
            await self._create_azure_tables()
            
            # Migrate data in order (respecting foreign keys)
            await self._migrate_users()
            await self._migrate_user_wallets()
            await self._migrate_personal_expenses()
            await self._migrate_trips()
            await self._migrate_trip_members()
            await self._migrate_expenses()
            await self._migrate_group_expenses()
            await self._migrate_expense_shares()
            await self._migrate_wallet_adjustments()
            await self._migrate_exchange_rates()
            await self._migrate_bank_accounts()
            await self._migrate_group_debts()
            await self._migrate_group_deductions()
            await self._migrate_pending_deductions()
            await self._migrate_payment_preferences()
            
            logger.info("Migration completed successfully!")
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            raise
    
    async def _create_azure_tables(self):
        """Create Azure SQL Database tables."""
        logger.info("Creating Azure SQL Database tables...")
        
        from db_azure import AzureDatabase
        azure_db = AzureDatabase()
        await azure_db.create_tables()
        
        logger.info("Azure tables created successfully")
    
    async def _migrate_table(self, table_name: str, columns: List[str], 
                           transform_row=None, batch_size: int = 1000):
        """Generic method to migrate a table."""
        logger.info(f"Migrating table: {table_name}")
        
        # Get SQLite data
        sqlite_conn = self.get_sqlite_connection()
        cursor = sqlite_conn.cursor()
        
        try:
            cursor.execute(f"SELECT {', '.join(columns)} FROM {table_name}")
            rows = cursor.fetchall()
            
            if not rows:
                logger.info(f"No data to migrate for table: {table_name}")
                return
            
            # Prepare Azure SQL insert
            azure_conn = self.get_azure_connection()
            azure_cursor = azure_conn.cursor()
            
            # Build insert query (excluding id for IDENTITY columns)
            insert_columns = [col for col in columns if col != 'id']
            placeholders = ', '.join(['?' for _ in insert_columns])
            insert_query = f"INSERT INTO {table_name} ({', '.join(insert_columns)}) VALUES ({placeholders})"
            
            # Process data in batches
            migrated_count = 0
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i + batch_size]
                batch_data = []
                
                for row in batch:
                    # Transform row if needed
                    if transform_row:
                        row = transform_row(row)
                    
                    # Exclude id column (first column) for IDENTITY tables
                    row_data = row[1:] if columns[0] == 'id' else row
                    batch_data.append(row_data)
                
                # Insert batch
                azure_cursor.executemany(insert_query, batch_data)
                azure_conn.commit()
                
                migrated_count += len(batch)
                logger.info(f"Migrated {migrated_count}/{len(rows)} rows for {table_name}")
            
            azure_conn.close()
            logger.info(f"Successfully migrated {table_name}: {migrated_count} rows")
            
        except Exception as e:
            logger.error(f"Error migrating {table_name}: {e}")
            raise
        finally:
            sqlite_conn.close()
    
    async def _migrate_users(self):
        """Migrate users table."""
        await self._migrate_table('users', ['id', 'tg_user_id', 'name', 'created_at', 'last_seen'])
    
    async def _migrate_user_wallets(self):
        """Migrate user_wallets table."""
        await self._migrate_table('user_wallets', 
                                ['id', 'user_id', 'currency', 'current_balance', 'created_at'])
    
    async def _migrate_personal_expenses(self):
        """Migrate personal_expenses table."""
        await self._migrate_table('personal_expenses', 
                                ['id', 'user_id', 'wallet_id', 'amount', 'currency', 'note', 'created_at'])
    
    async def _migrate_trips(self):
        """Migrate trips table."""
        await self._migrate_table('trips', 
                                ['id', 'name', 'group_id', 'creator_id', 'created_at'])
    
    async def _migrate_trip_members(self):
        """Migrate trip_members table."""
        await self._migrate_table('trip_members', 
                                ['id', 'trip_id', 'user_id', 'joined_at'])
    
    async def _migrate_expenses(self):
        """Migrate expenses table."""
        await self._migrate_table('expenses', 
                                ['id', 'trip_id', 'payer_id', 'amount', 'currency', 'note', 'created_at'])
    
    async def _migrate_group_expenses(self):
        """Migrate group_expenses table."""
        await self._migrate_table('group_expenses', 
                                ['id', 'group_id', 'payer_id', 'amount', 'currency', 'note', 'created_at'])
    
    async def _migrate_expense_shares(self):
        """Migrate expense_shares table."""
        await self._migrate_table('expense_shares', 
                                ['id', 'expense_id', 'group_expense_id', 'user_id', 'share_amount', 'currency', 'created_at'])
    
    async def _migrate_wallet_adjustments(self):
        """Migrate wallet_adjustments table."""
        await self._migrate_table('wallet_adjustments', 
                                ['id', 'wallet_id', 'amount', 'adjustment_type', 'note', 'created_at'])
    
    async def _migrate_exchange_rates(self):
        """Migrate exchange_rates table."""
        await self._migrate_table('exchange_rates', 
                                ['id', 'from_currency', 'to_currency', 'rate', 'set_by_user_id', 'created_at'])
    
    async def _migrate_bank_accounts(self):
        """Migrate bank_accounts table."""
        await self._migrate_table('bank_accounts', 
                                ['id', 'user_id', 'bank_code', 'bank_name', 'account_number', 'account_name', 'is_default', 'created_at'])
    
    async def _migrate_group_debts(self):
        """Migrate group_debts table."""
        await self._migrate_table('group_debts', 
                                ['id', 'group_id', 'debtor_id', 'creditor_id', 'amount', 'currency', 'created_at', 'updated_at'])
    
    async def _migrate_group_deductions(self):
        """Migrate group_deductions table."""
        await self._migrate_table('group_deductions', 
                                ['id', 'group_expense_id', 'user_id', 'wallet_id', 'deducted_amount', 'currency', 'created_at'])
    
    async def _migrate_pending_deductions(self):
        """Migrate pending_deductions table."""
        await self._migrate_table('pending_deductions', 
                                ['id', 'group_expense_id', 'user_id', 'pending_amount', 'currency', 'created_at'])
    
    async def _migrate_payment_preferences(self):
        """Migrate payment_preferences table."""
        await self._migrate_table('payment_preferences', 
                                ['id', 'user_id', 'accept_vnd_transfers', 'auto_convert_debts', 'created_at', 'updated_at'])
    
    async def verify_migration(self):
        """Verify that migration was successful by comparing row counts."""
        logger.info("Verifying migration...")
        
        tables = [
            'users', 'user_wallets', 'personal_expenses', 'trips', 'trip_members',
            'expenses', 'group_expenses', 'expense_shares', 'wallet_adjustments',
            'exchange_rates', 'bank_accounts', 'group_debts', 'group_deductions',
            'pending_deductions', 'payment_preferences'
        ]
        
        sqlite_conn = self.get_sqlite_connection()
        azure_conn = self.get_azure_connection()
        
        try:
            for table in tables:
                # SQLite count
                sqlite_cursor = sqlite_conn.cursor()
                sqlite_cursor.execute(f"SELECT COUNT(*) FROM {table}")
                sqlite_count = sqlite_cursor.fetchone()[0]
                
                # Azure SQL count
                azure_cursor = azure_conn.cursor()
                azure_cursor.execute(f"SELECT COUNT(*) FROM {table}")
                azure_count = azure_cursor.fetchone()[0]
                
                if sqlite_count == azure_count:
                    logger.info(f"✅ {table}: {sqlite_count} rows (matched)")
                else:
                    logger.warning(f"❌ {table}: SQLite={sqlite_count}, Azure={azure_count} (mismatch)")
        
        finally:
            sqlite_conn.close()
            azure_conn.close()
        
        logger.info("Migration verification completed")

async def main():
    """Main migration function."""
    try:
        migrator = SQLiteToAzureMigrator()
        await migrator.migrate_all_data()
        await migrator.verify_migration()
        
        print("\n" + "="*50)
        print("🎉 MIGRATION COMPLETED SUCCESSFULLY!")
        print("="*50)
        print("\nNext steps:")
        print("1. Update your .env file with Azure SQL settings")
        print("2. Set USE_SQLITE_FALLBACK=false")
        print("3. Restart your bot and web application")
        print("4. Test all functionality")
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        print("\nPlease check:")
        print("1. Azure SQL Database is created and accessible")
        print("2. Connection string is correct")
        print("3. SQLite database file exists")

if __name__ == "__main__":
    asyncio.run(main())
