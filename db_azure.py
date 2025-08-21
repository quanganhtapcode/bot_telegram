"""
Azure SQL Database implementation for the Telegram bot.
This is a hybrid implementation that can use both SQLite (fallback) and Azure SQL.
"""
import asyncio
import logging
import pyodbc
import aioodbc
import aiosqlite
from typing import Optional, List, Tuple, Any
from datetime import datetime, timedelta
from decimal import Decimal

from config_azure import azure_config
from models import *

logger = logging.getLogger(__name__)

class AzureDatabase:
    """
    Hybrid database class that supports both Azure SQL and SQLite fallback.
    """
    
    def __init__(self):
        self.use_azure = azure_config.is_azure_configured and not azure_config.use_sqlite_fallback
        
        if self.use_azure:
            logger.info("Using Azure SQL Database")
            self.connection_string = azure_config.pyodbc_connection_string
        else:
            logger.info("Using SQLite fallback")
            # Import original SQLite database
            from db import Database
            self.sqlite_db = Database(azure_config.sqlite_path)
    
    async def get_connection(self):
        """Get database connection (Azure SQL or SQLite)."""
        if self.use_azure:
            try:
                return await aioodbc.connect(dsn=self.connection_string)
            except Exception as e:
                logger.error(f"Failed to connect to Azure SQL: {e}")
                # Fallback to SQLite
                logger.info("Falling back to SQLite")
                self.use_azure = False
                from db import Database
                self.sqlite_db = Database(azure_config.sqlite_path)
                return await self.sqlite_db.get_connection()
        else:
            # Use direct aiosqlite connection to avoid relying on missing get_connection()
            return await aiosqlite.connect(azure_config.sqlite_path)
    
    async def execute_query(self, query: str, params: tuple = None) -> Any:
        """Execute a query and return results."""
        if self.use_azure:
            async with await self.get_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(query, params or ())
                    if query.strip().upper().startswith('SELECT'):
                        return await cursor.fetchall()
                    else:
                        await conn.commit()
                        return cursor.rowcount
        else:
            # Delegate to SQLite database
            return await self.sqlite_db.execute_query(query, params)
    
    async def execute_many(self, query: str, params_list: List[tuple]) -> int:
        """Execute a query multiple times with different parameters."""
        if self.use_azure:
            async with await self.get_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.executemany(query, params_list)
                    await conn.commit()
                    return cursor.rowcount
        else:
            return await self.sqlite_db.execute_many(query, params_list)
    
    async def create_tables(self):
        """Create database tables (Azure SQL or SQLite)."""
        if self.use_azure:
            await self._create_azure_tables()
        else:
            await self.sqlite_db.create_tables()
    
    async def _create_azure_tables(self):
        """Create tables for Azure SQL Database."""
        # Convert SQLite schema to SQL Server schema
        azure_schema = """
        -- Users table
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='users' AND xtype='U')
        CREATE TABLE users (
            id INT IDENTITY(1,1) PRIMARY KEY,
            tg_user_id BIGINT NOT NULL UNIQUE,
            name NVARCHAR(255) NOT NULL,
            created_at DATETIME2 DEFAULT GETDATE(),
            last_seen DATETIME2 DEFAULT GETDATE()
        );
        
        -- User wallets table  
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='user_wallets' AND xtype='U')
        CREATE TABLE user_wallets (
            id INT IDENTITY(1,1) PRIMARY KEY,
            user_id INT NOT NULL,
            currency NVARCHAR(10) NOT NULL,
            current_balance DECIMAL(15,2) NOT NULL DEFAULT 0.00,
            created_at DATETIME2 DEFAULT GETDATE(),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, currency)
        );
        
        -- Personal expenses table
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='personal_expenses' AND xtype='U') 
        CREATE TABLE personal_expenses (
            id INT IDENTITY(1,1) PRIMARY KEY,
            user_id INT NOT NULL,
            wallet_id INT NOT NULL,
            amount DECIMAL(15,2) NOT NULL,
            currency NVARCHAR(10) NOT NULL,
            note NVARCHAR(500),
            created_at DATETIME2 DEFAULT GETDATE(),
            -- Avoid multiple cascade paths: cascade via wallet, no action via user
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE NO ACTION,
            FOREIGN KEY (wallet_id) REFERENCES user_wallets(id) ON DELETE CASCADE
        );
        
        -- Expenses table (for group expenses)
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='expenses' AND xtype='U')
        CREATE TABLE expenses (
            id INT IDENTITY(1,1) PRIMARY KEY,
            trip_id INT,
            payer_id INT NOT NULL,
            amount DECIMAL(15,2) NOT NULL,
            currency NVARCHAR(10) NOT NULL,
            note NVARCHAR(500),
            created_at DATETIME2 DEFAULT GETDATE(),
            -- Avoid cascade from users to prevent multiple cascade paths
            FOREIGN KEY (payer_id) REFERENCES users(id) ON DELETE NO ACTION
        );
        
        -- Group expenses table
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='group_expenses' AND xtype='U')
        CREATE TABLE group_expenses (
            id INT IDENTITY(1,1) PRIMARY KEY,
            group_id BIGINT NOT NULL,
            payer_id INT NOT NULL,
            amount DECIMAL(15,2) NOT NULL,
            currency NVARCHAR(10) NOT NULL,
            note NVARCHAR(500),
            created_at DATETIME2 DEFAULT GETDATE(),
            -- Avoid cascade from users to prevent multiple cascade paths
            FOREIGN KEY (payer_id) REFERENCES users(id) ON DELETE NO ACTION
        );
        
        -- Expense shares table
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='expense_shares' AND xtype='U')
        CREATE TABLE expense_shares (
            id INT IDENTITY(1,1) PRIMARY KEY,
            expense_id INT,
            group_expense_id INT,
            user_id INT NOT NULL,
            share_amount DECIMAL(15,2) NOT NULL,
            currency NVARCHAR(10) NOT NULL,
            created_at DATETIME2 DEFAULT GETDATE(),
            -- Avoid multiple cascade paths: no action to parent expenses
            FOREIGN KEY (expense_id) REFERENCES expenses(id) ON DELETE NO ACTION,
            FOREIGN KEY (group_expense_id) REFERENCES group_expenses(id) ON DELETE NO ACTION,
            -- Avoid multiple cascade paths from users
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE NO ACTION
        );
        
        -- Trips table
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='trips' AND xtype='U')
        CREATE TABLE trips (
            id INT IDENTITY(1,1) PRIMARY KEY,
            name NVARCHAR(255) NOT NULL,
            group_id BIGINT NOT NULL UNIQUE,
            creator_id INT NOT NULL,
            created_at DATETIME2 DEFAULT GETDATE(),
            FOREIGN KEY (creator_id) REFERENCES users(id) ON DELETE CASCADE
        );
        
        -- Trip members table
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='trip_members' AND xtype='U')
        CREATE TABLE trip_members (
            id INT IDENTITY(1,1) PRIMARY KEY,
            trip_id INT NOT NULL,
            user_id INT NOT NULL,
            joined_at DATETIME2 DEFAULT GETDATE(),
            FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE,
            -- Avoid multiple cascade paths from users via trips
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE NO ACTION,
            UNIQUE(trip_id, user_id)
        );
        
        -- Wallet adjustments table
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='wallet_adjustments' AND xtype='U')
        CREATE TABLE wallet_adjustments (
            id INT IDENTITY(1,1) PRIMARY KEY,
            wallet_id INT NOT NULL,
            delta_amount DECIMAL(15,2) NOT NULL,
            reason NVARCHAR(500) NOT NULL,
            created_at DATETIME2 DEFAULT GETDATE(),
            FOREIGN KEY (wallet_id) REFERENCES user_wallets(id) ON DELETE CASCADE
        );
        
        -- Exchange rates table
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='exchange_rates' AND xtype='U')
        CREATE TABLE exchange_rates (
            id INT IDENTITY(1,1) PRIMARY KEY,
            from_currency NVARCHAR(10) NOT NULL,
            to_currency NVARCHAR(10) NOT NULL,
            rate DECIMAL(20,8) NOT NULL,
            set_by INT NOT NULL,
            created_at DATETIME2 DEFAULT GETDATE(),
            FOREIGN KEY (set_by) REFERENCES users(id),
            UNIQUE(from_currency, to_currency)
        );
        
        -- Bank accounts table
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='bank_accounts' AND xtype='U')
        CREATE TABLE bank_accounts (
            id INT IDENTITY(1,1) PRIMARY KEY,
            user_id INT NOT NULL,
            bank_code NVARCHAR(20) NOT NULL,
            bank_name NVARCHAR(100) NOT NULL,
            account_number NVARCHAR(50) NOT NULL,
            account_name NVARCHAR(100) NOT NULL,
            is_default BIT DEFAULT 0,
            created_at DATETIME2 DEFAULT GETDATE(),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        
        -- Group debts table
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='group_debts' AND xtype='U')
        CREATE TABLE group_debts (
            id INT IDENTITY(1,1) PRIMARY KEY,
            group_id BIGINT NOT NULL,
            debtor_id INT NOT NULL,
            creditor_id INT NOT NULL,
            amount DECIMAL(15,2) NOT NULL,
            currency NVARCHAR(10) NOT NULL,
            created_at DATETIME2 DEFAULT GETDATE(),
            updated_at DATETIME2 DEFAULT GETDATE(),
            FOREIGN KEY (debtor_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (creditor_id) REFERENCES users(id) ON DELETE NO ACTION
        );
        
        -- Group deductions table
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='group_deductions' AND xtype='U')
        CREATE TABLE group_deductions (
            id INT IDENTITY(1,1) PRIMARY KEY,
            group_expense_id INT NOT NULL,
            user_id INT NOT NULL,
            wallet_id INT,
            deducted_amount DECIMAL(15,2) NOT NULL,
            currency NVARCHAR(10) NOT NULL,
            created_at DATETIME2 DEFAULT GETDATE(),
            FOREIGN KEY (group_expense_id) REFERENCES group_expenses(id) ON DELETE CASCADE,
            -- Avoid multiple cascade paths from users
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE NO ACTION,
            FOREIGN KEY (wallet_id) REFERENCES user_wallets(id) ON DELETE SET NULL
        );
        
        -- Pending deductions table
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='pending_deductions' AND xtype='U')
        CREATE TABLE pending_deductions (
            id INT IDENTITY(1,1) PRIMARY KEY,
            group_expense_id INT NOT NULL,
            user_id INT NOT NULL,
            pending_amount DECIMAL(15,2) NOT NULL,
            currency NVARCHAR(10) NOT NULL,
            created_at DATETIME2 DEFAULT GETDATE(),
            FOREIGN KEY (group_expense_id) REFERENCES group_expenses(id) ON DELETE CASCADE,
            -- Avoid multiple cascade paths from users
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE NO ACTION
        );
        
        -- Payment preferences table
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='payment_preferences' AND xtype='U')
        CREATE TABLE payment_preferences (
            id INT IDENTITY(1,1) PRIMARY KEY,
            user_id INT NOT NULL,
            accept_vnd_transfers BIT DEFAULT 1,
            auto_convert_debts BIT DEFAULT 1,
            created_at DATETIME2 DEFAULT GETDATE(),
            updated_at DATETIME2 DEFAULT GETDATE(),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id)
        );
        """
        
        # Execute schema creation
        statements = azure_schema.split(';\n\n')
        for statement in statements:
            if statement.strip():
                try:
                    await self.execute_query(statement.strip())
                    logger.info(f"Created table successfully")
                except Exception as e:
                    logger.error(f"Error creating table: {e}")
                    logger.error(f"Statement: {statement[:100]}...")
    
    # Delegate all other methods to SQLite implementation or implement Azure versions
    async def create_or_update_user(self, tg_user_id: int, name: str) -> User:
        """Create or update user."""
        if self.use_azure:
            # Azure SQL implementation
            query = """
            MERGE users AS target
            USING (SELECT ? AS tg_user_id, ? AS name) AS source
            ON target.tg_user_id = source.tg_user_id
            WHEN MATCHED THEN
                UPDATE SET name = source.name, last_seen = GETDATE()
            WHEN NOT MATCHED THEN
                INSERT (tg_user_id, name, created_at, last_seen)
                VALUES (source.tg_user_id, source.name, GETDATE(), GETDATE());
            """
            await self.execute_query(query, (tg_user_id, name))
            
            # Get the user
            query = "SELECT id, tg_user_id, name, created_at, last_seen FROM users WHERE tg_user_id = ?"
            result = await self.execute_query(query, (tg_user_id,))
            if result:
                return User(*result[0])
        else:
            return await self.sqlite_db.create_or_update_user(tg_user_id, name)
    
    # Add more method implementations as needed...
    # For now, delegate to SQLite for methods not yet implemented
    def __getattr__(self, name):
        """Delegate unknown methods to SQLite database."""
        if hasattr(self, 'sqlite_db'):
            return getattr(self.sqlite_db, name)
        else:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
