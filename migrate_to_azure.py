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
                           transform_row=None, batch_size: int = 1000, has_identity: bool = True):
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
            
            # Build insert query
            # For tables with IDENTITY, we preserve original IDs to keep FK references valid
            insert_columns = columns[:] if has_identity else [col for col in columns if col != 'id']
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
                    # Include or exclude id depending on has_identity flag
                    row_data = row if has_identity else (row[1:] if columns[0] == 'id' else row)
                    batch_data.append(row_data)
                
                # Enable IDENTITY_INSERT if needed
                if has_identity:
                    azure_cursor.execute(f"SET IDENTITY_INSERT {table_name} ON")
                
                # Insert batch
                azure_cursor.executemany(insert_query, batch_data)
                azure_conn.commit()

                # Disable IDENTITY_INSERT if enabled
                if has_identity:
                    azure_cursor.execute(f"SET IDENTITY_INSERT {table_name} OFF")
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
        """Migrate users table with IDENTITY_INSERT to preserve IDs."""
        await self._migrate_table('users', ['id', 'tg_user_id', 'name', 'created_at', 'last_seen'], has_identity=True)
    
    async def _migrate_user_wallets(self):
        """Migrate user_wallets table with IDENTITY_INSERT to preserve IDs."""
        await self._migrate_table('user_wallets', 
                                ['id', 'user_id', 'currency', 'current_balance', 'created_at'],
                                has_identity=True)
    
    async def _migrate_personal_expenses(self):
        """Migrate personal_expenses table with FK validation."""
        await self._migrate_table('personal_expenses', 
                                ['id', 'user_id', 'wallet_id', 'amount', 'currency', 'note', 'created_at'],
                                has_identity=True)
    
    async def _migrate_trips(self):
        """Migrate trips table with IDENTITY_INSERT."""
        # Map SQLite columns: code, name, base_currency, owner_user_id -> creator_id
        await self._migrate_table('trips', 
                                ['id', 'code', 'name', 'base_currency', 'owner_user_id', 'created_at'],
                                has_identity=True)
    
    async def _migrate_trip_members(self):
        """Migrate trip_members table with IDENTITY_INSERT."""
        # Map SQLite columns: trip_id, user_id, role (no id column, composite PK)
        await self._migrate_table('trip_members', 
                                ['trip_id', 'user_id', 'role'],
                                has_identity=False)  # No IDENTITY column
    
    async def _migrate_expenses(self):
        """Migrate expenses table with IDENTITY_INSERT."""
        # Map SQLite columns: payer_user_id, rate_to_base, amount_base, note
        await self._migrate_table('expenses', 
                                ['id', 'trip_id', 'payer_user_id', 'amount', 'currency', 'rate_to_base', 'amount_base', 'note', 'created_at'],
                                has_identity=True)
    
    async def _migrate_group_expenses(self):
        """Migrate group_expenses table with IDENTITY_INSERT."""
        # Map SQLite columns to Azure SQL columns
        await self._migrate_table('group_expenses', 
                                ['id', 'group_id', 'payer_user_id', 'amount', 'currency', 'description', 'created_at', 'settled', 'undo_until'],
                                has_identity=True)
    
    async def _migrate_expense_shares(self):
        """Migrate expense_shares table with IDENTITY_INSERT."""
        # Map SQLite columns: share_ratio -> share_amount (need conversion)
        await self._migrate_table('expense_shares', 
                                ['id', 'expense_id', 'user_id', 'share_ratio'],
                                has_identity=True)
    
    async def _migrate_wallet_adjustments(self):
        """Migrate wallet_adjustments table with FK validation and IDENTITY_INSERT.
        Only migrate rows whose wallet_id exists in user_wallets to satisfy FK.
        """
        logger.info("Migrating table: wallet_adjustments (with FK validation)")

        # Load data from SQLite
        sqlite_conn = self.get_sqlite_connection()
        s_cur = sqlite_conn.cursor()
        s_cur.execute("SELECT id, wallet_id, delta_amount, reason, created_at FROM wallet_adjustments")
        rows = s_cur.fetchall()

        if not rows:
            logger.info("No data to migrate for table: wallet_adjustments")
            sqlite_conn.close()
            return

        # Open Azure connection and get valid wallet ids
        azure_conn = self.get_azure_connection()
        a_cur = azure_conn.cursor()
        a_cur.execute("SELECT id FROM user_wallets")
        valid_wallet_ids = set(r[0] for r in a_cur.fetchall())

        # Filter rows with valid wallet_id
        filtered = [r for r in rows if r[1] in valid_wallet_ids]
        skipped = len(rows) - len(filtered)
        if skipped:
            logger.warning(f"Skipping {skipped} wallet_adjustments rows with missing wallet_id in user_wallets")

        if not filtered:
            logger.info("No valid rows to migrate for wallet_adjustments")
            azure_conn.close()
            sqlite_conn.close()
            return

        # Insert with IDENTITY_INSERT
        a_cur.execute("SET IDENTITY_INSERT wallet_adjustments ON")
        a_cur.executemany(
            "INSERT INTO wallet_adjustments (id, wallet_id, delta_amount, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            filtered
        )
        azure_conn.commit()
        a_cur.execute("SET IDENTITY_INSERT wallet_adjustments OFF")
        azure_conn.commit()

        logger.info(f"Successfully migrated wallet_adjustments: {len(filtered)} rows (skipped {skipped})")

        azure_conn.close()
        sqlite_conn.close()
    
    async def _migrate_exchange_rates(self):
        """Migrate exchange_rates table with IDENTITY_INSERT."""
        # Map SQLite columns: set_by -> set_by_user_id
        await self._migrate_table('exchange_rates', 
                                ['id', 'from_currency', 'to_currency', 'rate', 'set_by', 'created_at'],
                                has_identity=True)
    
    async def _migrate_bank_accounts(self):
        """Migrate bank_accounts table with IDENTITY_INSERT."""
        await self._migrate_table('bank_accounts', 
                                ['id', 'user_id', 'bank_code', 'bank_name', 'account_number', 'account_name', 'is_default', 'created_at'],
                                has_identity=True)
    
    async def _migrate_group_debts(self):
        """Migrate group_debts table with IDENTITY_INSERT."""
        # Map SQLite columns: debtor_user_id, creditor_user_id, last_updated
        await self._migrate_table('group_debts', 
                                ['id', 'group_id', 'debtor_user_id', 'creditor_user_id', 'amount', 'currency', 'last_updated'],
                                has_identity=True)
    
    async def _migrate_group_deductions(self):
        """Migrate group_deductions table with IDENTITY_INSERT."""
        # Map SQLite columns: trip_id, expense_id, share_amount, share_currency, fx_rate_used, deducted_amount_in_wallet_currency
        await self._migrate_table('group_deductions', 
                                ['id', 'user_id', 'trip_id', 'expense_id', 'share_amount', 'share_currency', 'wallet_id', 'fx_rate_used', 'deducted_amount_in_wallet_currency', 'created_at'],
                                has_identity=True)
    
    async def _migrate_pending_deductions(self):
        """Migrate pending_deductions table with IDENTITY_INSERT."""
        # Map SQLite columns: trip_id, expense_id, share_amount, share_currency, suggested_wallet_id, suggested_fx_rate, suggested_deduction_amount
        await self._migrate_table('pending_deductions', 
                                ['id', 'user_id', 'trip_id', 'expense_id', 'share_amount', 'share_currency', 'suggested_wallet_id', 'suggested_fx_rate', 'suggested_deduction_amount', 'created_at'],
                                has_identity=True)
    
    async def _migrate_payment_preferences(self):
        """Migrate payment_preferences table with IDENTITY_INSERT."""
        # Map SQLite columns: accept_vnd_payments, auto_convert_debts, preferred_bank_id
        await self._migrate_table('payment_preferences', 
                                ['user_id', 'accept_vnd_payments', 'auto_convert_debts', 'preferred_bank_id'],
                                has_identity=False)  # This table uses user_id as PK, not IDENTITY
    
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
