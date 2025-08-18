"""
Database operations for the Telegram bot.
"""
import aiosqlite
import logging
from typing import List, Optional, Tuple, Dict
from decimal import Decimal
from datetime import datetime, timedelta
from models import *
import os

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init_db(self):
        """Initialize the database with all required tables."""
        async with aiosqlite.connect(self.db_path) as db:
            # SQLite optimizations for better performance
            await db.execute("PRAGMA journal_mode=WAL")      # Better concurrency
            await db.execute("PRAGMA synchronous=NORMAL")     # Faster writes
            await db.execute("PRAGMA cache_size=10000")       # More memory cache
            await db.execute("PRAGMA temp_store=MEMORY")      # Use memory for temp
            
            # Users table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tg_user_id INTEGER UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # User settings table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    preferred_currency TEXT DEFAULT 'TWD',
                    allow_negative BOOLEAN DEFAULT TRUE,
                    auto_rule BOOLEAN DEFAULT TRUE,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)

            # Bank accounts table for VietQR
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bank_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    bank_code TEXT NOT NULL,
                    bank_name TEXT NOT NULL,
                    account_number TEXT NOT NULL,
                    account_name TEXT NOT NULL,
                    is_default BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)

            # User payment preferences
            await db.execute("""
                CREATE TABLE IF NOT EXISTS payment_preferences (
                    user_id INTEGER PRIMARY KEY,
                    accept_vnd_payments BOOLEAN DEFAULT FALSE,
                    auto_convert_debts BOOLEAN DEFAULT FALSE,
                    preferred_bank_id INTEGER,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (preferred_bank_id) REFERENCES bank_accounts (id)
                )
            """)

            # User wallets table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_wallets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    initial_amount DECIMAL(15,2) NOT NULL,
                    current_balance DECIMAL(15,2) NOT NULL,
                    note TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    UNIQUE(user_id, currency)
                )
            """)

            # Wallet adjustments table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS wallet_adjustments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_id INTEGER NOT NULL,
                    delta_amount DECIMAL(15,2) NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (wallet_id) REFERENCES user_wallets (id)
                )
            """)

            # Personal expenses table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS personal_expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount DECIMAL(15,2) NOT NULL,
                    currency TEXT NOT NULL,
                    note TEXT,
                    wallet_id INTEGER NOT NULL,
                    fx_rate DECIMAL(10,6),
                    converted_amount DECIMAL(15,2),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    undo_until TIMESTAMP NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (wallet_id) REFERENCES user_wallets (id)
                )
            """)

            # Trips table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    base_currency TEXT NOT NULL,
                    owner_user_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (owner_user_id) REFERENCES users (id)
                )
            """)

            # Trip members table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trip_members (
                    trip_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
                    PRIMARY KEY (trip_id, user_id),
                    FOREIGN KEY (trip_id) REFERENCES trips (id),
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)

            # Expenses table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trip_id INTEGER NOT NULL,
                    payer_user_id INTEGER NOT NULL,
                    amount DECIMAL(15,2) NOT NULL,
                    currency TEXT NOT NULL,
                    rate_to_base DECIMAL(10,6) NOT NULL,
                    amount_base DECIMAL(15,2) NOT NULL,
                    note TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (trip_id) REFERENCES trips (id),
                    FOREIGN KEY (payer_user_id) REFERENCES users (id)
                )
            """)

            # Expense shares table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS expense_shares (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expense_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    share_ratio DECIMAL(5,4) NOT NULL,
                    FOREIGN KEY (expense_id) REFERENCES expenses (id),
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)

            # Group deductions table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS group_deductions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    trip_id INTEGER NOT NULL,
                    expense_id INTEGER NOT NULL,
                    share_amount DECIMAL(15,2) NOT NULL,
                    share_currency TEXT NOT NULL,
                    wallet_id INTEGER NOT NULL,
                    fx_rate_used DECIMAL(10,6) NOT NULL,
                    deducted_amount_in_wallet_currency DECIMAL(15,2) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (trip_id) REFERENCES trips (id),
                    FOREIGN KEY (expense_id) REFERENCES expenses (id),
                    FOREIGN KEY (wallet_id) REFERENCES user_wallets (id)
                )
            """)

            # Pending deductions table (before user confirms payment)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pending_deductions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    trip_id INTEGER NOT NULL,
                    expense_id INTEGER NOT NULL,
                    share_amount DECIMAL(15,2) NOT NULL,
                    share_currency TEXT NOT NULL,
                    suggested_wallet_id INTEGER,
                    suggested_fx_rate DECIMAL(10,6),
                    suggested_deduction_amount DECIMAL(15,2),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (trip_id) REFERENCES trips (id),
                    FOREIGN KEY (expense_id) REFERENCES expenses (id),
                    FOREIGN KEY (suggested_wallet_id) REFERENCES user_wallets (id)
                )
            """)

            # Exchange rates table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS exchange_rates (
                    from_currency TEXT NOT NULL,
                    to_currency TEXT NOT NULL,
                    rate DECIMAL(10,6) NOT NULL,
                    set_by TEXT,
                    PRIMARY KEY (from_currency, to_currency)
                )
            """)

            # Group expenses table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS group_expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    payer_user_id INTEGER NOT NULL,
                    amount DECIMAL(15,2) NOT NULL,
                    currency TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    settled BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (payer_user_id) REFERENCES users (id)
                )
            """)

            # Group expense participants table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS group_expense_participants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expense_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    share_amount DECIMAL(15,2) NOT NULL,
                    paid BOOLEAN DEFAULT FALSE,
                    reminded BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (expense_id) REFERENCES group_expenses (id),
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)

            # Group debts table (optimized debts between users)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS group_debts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    debtor_user_id INTEGER NOT NULL,
                    creditor_user_id INTEGER NOT NULL,
                    amount DECIMAL(15,2) NOT NULL,
                    currency TEXT NOT NULL,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (debtor_user_id) REFERENCES users (id),
                    FOREIGN KEY (creditor_user_id) REFERENCES users (id),
                    UNIQUE (group_id, debtor_user_id, creditor_user_id, currency)
                )
            """)

            # Debt settlements table (history of payments)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS debt_settlements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    payer_user_id INTEGER NOT NULL,
                    receiver_user_id INTEGER NOT NULL,
                    amount DECIMAL(15,2) NOT NULL,
                    currency TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (payer_user_id) REFERENCES users (id),
                    FOREIGN KEY (receiver_user_id) REFERENCES users (id)
                )
            """)

            await db.commit()
            
            # Add undo_until column to group_expenses if not exists (migration)
            try:
                cursor = await db.execute("PRAGMA table_info(group_expenses)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                if 'undo_until' not in column_names:
                    await db.execute("ALTER TABLE group_expenses ADD COLUMN undo_until TIMESTAMP")
                    await db.commit()
                    logger.info("Added undo_until column to group_expenses table")
            except Exception as e:
                logger.error(f"Error adding undo_until column: {e}")
                
            # Add undo_until column to personal_expenses if not exists (migration)
            try:
                cursor = await db.execute("PRAGMA table_info(personal_expenses)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                if 'undo_until' not in column_names:
                    await db.execute("ALTER TABLE personal_expenses ADD COLUMN undo_until TIMESTAMP")
                    await db.commit()
                    logger.info("Added undo_until column to personal_expenses table")
                    
                    # Update existing expenses to have undo_until = created_at + 24 hours
                    await db.execute("""
                        UPDATE personal_expenses 
                        SET undo_until = datetime(created_at, '+24 hours') 
                        WHERE undo_until IS NULL
                    """)
                    await db.commit()
                    logger.info("Updated existing personal expenses with undo_until")
            except Exception as e:
                logger.error(f"Error adding undo_until column to personal_expenses: {e}")
                
            # Add payment_method column to group_expense_participants if not exists
            try:
                cursor = await db.execute("PRAGMA table_info(group_expense_participants)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                if 'payment_method' not in column_names:
                    await db.execute("ALTER TABLE group_expense_participants ADD COLUMN payment_method TEXT DEFAULT 'end_of_day'")
                    await db.commit()
                    logger.info("Added payment_method column to group_expense_participants table")
            except Exception as e:
                logger.error(f"Error adding payment_method column: {e}")
                
            logger.info("Database initialized successfully")

    # User operations
    async def create_or_update_user(self, tg_user_id: int, name: str) -> User:
        """Create or update a user and return the user object."""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if user exists
            cursor = await db.execute(
                "SELECT id, tg_user_id, name, created_at, last_seen FROM users WHERE tg_user_id = ?",
                (tg_user_id,)
            )
            row = await cursor.fetchone()
            
            if row:
                # Update existing user
                await db.execute(
                    "UPDATE users SET name = ?, last_seen = CURRENT_TIMESTAMP WHERE tg_user_id = ?",
                    (name, tg_user_id)
                )
                await db.commit()
                return User(row[0], row[1], name, row[3], datetime.now())
            else:
                # Create new user
                cursor = await db.execute(
                    "INSERT INTO users (tg_user_id, name) VALUES (?, ?)",
                    (tg_user_id, name)
                )
                user_id = cursor.lastrowid
                
                # Create default settings
                await db.execute(
                    "INSERT INTO user_settings (user_id) VALUES (?)",
                    (user_id,)
                )
                await db.commit()
                
                return User(user_id, tg_user_id, name, datetime.now(), datetime.now())

    async def get_user_by_tg_id(self, tg_user_id: int) -> Optional[User]:
        """Get user by Telegram user ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id, tg_user_id, name, created_at, last_seen FROM users WHERE tg_user_id = ?",
                (tg_user_id,)
            )
            row = await cursor.fetchone()
            if row:
                return User(*row)
            return None

    # User settings operations
    async def get_user_settings(self, user_id: int) -> UserSettings:
        """Get user settings."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT user_id, preferred_currency, allow_negative, auto_rule FROM user_settings WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                return UserSettings(*row)
            return UserSettings(user_id, "TWD", False, False)

    async def update_user_settings(self, user_id: int, **kwargs) -> None:
        """Update user settings."""
        async with aiosqlite.connect(self.db_path) as db:
            # First ensure the record exists
            await db.execute(
                "INSERT OR IGNORE INTO user_settings (user_id, preferred_currency, allow_negative, auto_rule) VALUES (?, 'TWD', TRUE, TRUE)",
                (user_id,)
            )
            
            # Then update the specific fields
            if 'preferred_currency' in kwargs:
                await db.execute(
                    "UPDATE user_settings SET preferred_currency = ? WHERE user_id = ?",
                    (kwargs['preferred_currency'], user_id)
                )
            await db.commit()

    # Wallet operations
    async def create_wallet(self, user_id: int, currency: str, initial_amount: Decimal, note: Optional[str] = None) -> UserWallet:
        """Create a new wallet."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO user_wallets (user_id, currency, initial_amount, current_balance, note) VALUES (?, ?, ?, ?, ?)",
                (user_id, currency, str(initial_amount), str(initial_amount), note)
            )
            wallet_id = cursor.lastrowid
            
            # Log the initial adjustment
            await db.execute(
                "INSERT INTO wallet_adjustments (wallet_id, delta_amount, reason) VALUES (?, ?, ?)",
                (wallet_id, str(initial_amount), "Tạo ví mới")
            )
            await db.commit()
            
            return UserWallet(wallet_id, user_id, currency, initial_amount, initial_amount, note, datetime.now(), datetime.now())

    async def get_user_wallets(self, user_id: int) -> List[UserWallet]:
        """Get all wallets for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id, user_id, currency, initial_amount, current_balance, note, created_at, updated_at FROM user_wallets WHERE user_id = ? ORDER BY currency",
                (user_id,)
            )
            rows = await cursor.fetchall()
            return [UserWallet(row[0], row[1], row[2], Decimal(str(row[3])), Decimal(str(row[4])), row[5], row[6], row[7]) for row in rows]

    async def get_wallet(self, wallet_id: int) -> Optional[UserWallet]:
        """Get a wallet by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id, user_id, currency, initial_amount, current_balance, note, created_at, updated_at FROM user_wallets WHERE id = ?",
                (wallet_id,)
            )
            row = await cursor.fetchone()
            if row:
                return UserWallet(row[0], row[1], row[2], Decimal(str(row[3])), Decimal(str(row[4])), row[5], row[6], row[7])
            return None

    async def get_wallet_by_currency(self, user_id: int, currency: str) -> Optional[UserWallet]:
        """Get a wallet by user ID and currency."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id, user_id, currency, initial_amount, current_balance, note, created_at, updated_at FROM user_wallets WHERE user_id = ? AND currency = ?",
                (user_id, currency)
            )
            row = await cursor.fetchone()
            if row:
                return UserWallet(row[0], row[1], row[2], Decimal(str(row[3])), Decimal(str(row[4])), row[5], row[6], row[7])
            return None

    async def update_wallet_balance(self, wallet_id: int, delta_amount: Decimal, reason: str) -> bool:
        """Update wallet balance and log the adjustment."""
        async with aiosqlite.connect(self.db_path) as db:
            # Get current balance
            cursor = await db.execute(
                "SELECT current_balance FROM user_wallets WHERE id = ?",
                (wallet_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return False
            
            new_balance = Decimal(str(row[0])) + delta_amount
            
            # Update balance
            await db.execute(
                "UPDATE user_wallets SET current_balance = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (str(new_balance), wallet_id)
            )
            
            # Log adjustment
            await db.execute(
                "INSERT INTO wallet_adjustments (wallet_id, delta_amount, reason) VALUES (?, ?, ?)",
                (wallet_id, str(delta_amount), reason)
            )
            await db.commit()
            return True

    async def delete_wallet(self, wallet_id: int) -> bool:
        """Delete a wallet regardless of balance."""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if wallet exists
            cursor = await db.execute(
                "SELECT current_balance FROM user_wallets WHERE id = ?",
                (wallet_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return False
            
            # Delete wallet (regardless of balance)
            await db.execute("DELETE FROM user_wallets WHERE id = ?", (wallet_id,))
            await db.commit()
            return True

    # Personal expense operations
    async def add_personal_expense(self, user_id: int, amount: Decimal, currency: str, 
                                 wallet_id: int, note: Optional[str] = None, 
                                 fx_rate: Optional[Decimal] = None, 
                                 converted_amount: Optional[Decimal] = None) -> PersonalExpense:
        """Add a personal expense."""
        undo_until = datetime.now() + timedelta(hours=24)
        
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO personal_expenses 
                   (user_id, amount, currency, note, wallet_id, fx_rate, converted_amount, undo_until) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, str(amount), currency, note, wallet_id, 
                 str(fx_rate) if fx_rate else None, 
                 str(converted_amount) if converted_amount else None, undo_until)
            )
            expense_id = cursor.lastrowid
            await db.commit()
            
            return PersonalExpense(expense_id, user_id, amount, currency, note, 
                                 wallet_id, fx_rate, converted_amount, datetime.now(), undo_until)

    async def get_personal_expenses(self, user_id: int, days: int = 7) -> List[PersonalExpense]:
        """Get personal expenses for the last N days."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT id, user_id, amount, currency, note, wallet_id, fx_rate, converted_amount, created_at, undo_until 
                   FROM personal_expenses 
                   WHERE user_id = ? AND created_at > datetime('now', '-{} days')
                   ORDER BY created_at DESC""".format(days),
                (user_id,)
            )
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                # Convert datetime fields properly
                created_at = None
                undo_until = None
                
                if row[8]:  # created_at
                    try:
                        created_at = datetime.fromisoformat(row[8]) if isinstance(row[8], str) else row[8]
                    except (ValueError, TypeError):
                        created_at = None
                
                if row[9]:  # undo_until
                    try:
                        undo_until = datetime.fromisoformat(row[9]) if isinstance(row[9], str) else row[9]
                    except (ValueError, TypeError):
                        undo_until = None
                
                result.append(PersonalExpense(
                    row[0], row[1], Decimal(str(row[2])), row[3], row[4], row[5],
                    Decimal(str(row[6])) if row[6] else None,
                    Decimal(str(row[7])) if row[7] else None,
                    created_at, undo_until
                ))
            return result

    async def get_personal_expenses_today(self, user_id: int, currency: str = None) -> List[PersonalExpense]:
        """Get personal expenses for today."""
        async with aiosqlite.connect(self.db_path) as db:
            if currency:
                cursor = await db.execute(
                    """SELECT id, user_id, amount, currency, note, wallet_id, fx_rate, converted_amount, created_at, undo_until 
                       FROM personal_expenses 
                       WHERE user_id = ? AND currency = ? AND date(created_at) = date('now')
                       ORDER BY created_at DESC""",
                    (user_id, currency)
                )
            else:
                cursor = await db.execute(
                    """SELECT id, user_id, amount, currency, note, wallet_id, fx_rate, converted_amount, created_at, undo_until 
                       FROM personal_expenses 
                       WHERE user_id = ? AND date(created_at) = date('now')
                       ORDER BY created_at DESC""",
                    (user_id,)
                )
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                # Convert datetime fields properly
                created_at = None
                undo_until = None
                
                if row[8]:  # created_at
                    try:
                        created_at = datetime.fromisoformat(row[8]) if isinstance(row[8], str) else row[8]
                    except (ValueError, TypeError):
                        created_at = None
                
                if row[9]:  # undo_until
                    try:
                        undo_until = datetime.fromisoformat(row[9]) if isinstance(row[9], str) else row[9]
                    except (ValueError, TypeError):
                        undo_until = None
                
                result.append(PersonalExpense(
                    row[0], row[1], Decimal(str(row[2])), row[3], row[4], row[5],
                    Decimal(str(row[6])) if row[6] else None,
                    Decimal(str(row[7])) if row[7] else None,
                    created_at, undo_until
                ))
            return result

    async def undo_personal_expense(self, expense_id: int, user_id: int) -> bool:
        """Undo a personal expense if within time limit."""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if expense exists and can be undone
            cursor = await db.execute(
                """SELECT amount, currency, wallet_id, converted_amount, undo_until 
                   FROM personal_expenses 
                   WHERE id = ? AND user_id = ?""",
                (expense_id, user_id)
            )
            row = await cursor.fetchone()
            if not row:
                return False
            
            amount, currency, wallet_id, converted_amount, undo_until = row
            
            # Check if expense can still be undone (within time limit)
            current_time = datetime.now()
            undo_until_dt = None
            
            if undo_until:
                try:
                    undo_until_dt = datetime.fromisoformat(undo_until) if isinstance(undo_until, str) else undo_until
                except (ValueError, TypeError):
                    undo_until_dt = None
            
            if not undo_until_dt or undo_until_dt <= current_time:
                return False  # Expense has expired
            
            restore_amount = Decimal(str(converted_amount)) if converted_amount else Decimal(str(amount))
            
            # Restore wallet balance
            await self.update_wallet_balance(wallet_id, Decimal(str(restore_amount)), "Hoàn tác chi tiêu")
            
            # Delete expense record
            await db.execute("DELETE FROM personal_expenses WHERE id = ?", (expense_id,))
            await db.commit()
            return True

    async def delete_personal_expense(self, expense_id: int, user_id: int) -> bool:
        """Hard delete a personal expense regardless of time, without balance restoration."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM personal_expenses WHERE id = ? AND user_id = ?",
                (expense_id, user_id)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_group_expenses_by_user(self, user_id: int, group_id: int, days: int) -> List:
        """Get group expenses by user for specified days."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT id, amount, currency, description, payer_user_id, 
                          datetime(created_at, '+7 hours') as local_time, 
                          undo_until
                   FROM group_expenses 
                   WHERE payer_user_id = ? AND group_id = ? 
                   AND date(created_at) >= date('now', '-{} days')
                   ORDER BY created_at DESC""".format(days),
                (user_id, group_id)
            )
            rows = await cursor.fetchall()
            
            # Create simple expense objects with required attributes
            result = []
            for row in rows:
                expense = type('Expense', (), {})()
                expense.id = row[0]
                expense.amount = row[1] 
                expense.currency = row[2]
                expense.description = row[3]
                expense.payer_id = row[4]
                expense.created_at = row[5]
                
                # Convert undo_until datetime properly
                undo_until = None
                if row[6]:  # undo_until
                    try:
                        undo_until = datetime.fromisoformat(row[6]) if isinstance(row[6], str) else row[6]
                    except (ValueError, TypeError):
                        undo_until = None
                
                expense.undo_until = undo_until
                result.append(expense)
            return result

    async def undo_group_expense(self, expense_id: int, user_id: int) -> bool:
        """Undo a group expense if within time limit and user is the payer."""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if expense exists and can be undone
            cursor = await db.execute(
                """SELECT payer_id, group_id, undo_until 
                   FROM group_expenses 
                   WHERE id = ? AND payer_id = ?""",
                (expense_id, user_id)
            )
            row = await cursor.fetchone()
            if not row:
                return False
            
            payer_id, group_id, undo_until = row
            
            # Check if expense can still be undone (within time limit)
            current_time = datetime.now()
            undo_until_dt = None
            
            if undo_until:
                try:
                    undo_until_dt = datetime.fromisoformat(undo_until) if isinstance(undo_until, str) else undo_until
                except (ValueError, TypeError):
                    undo_until_dt = None
            
            if not undo_until_dt or undo_until_dt <= current_time:
                return False  # Expense has expired
            
            # Delete related debts
            await db.execute("DELETE FROM debts WHERE expense_id = ?", (expense_id,))
            
            # Delete expense record
            await db.execute("DELETE FROM group_expenses WHERE id = ?", (expense_id,))
            await db.commit()
            return True

    async def delete_group_expense(self, expense_id: int, user_id: int) -> bool:
        """Hard delete a group expense regardless of time, ensuring related debts are removed."""
        async with aiosqlite.connect(self.db_path) as db:
            # Remove related debts first
            await db.execute("DELETE FROM debts WHERE expense_id = ?", (expense_id,))
            # Remove the expense (only if issued by this user)
            cursor = await db.execute(
                "DELETE FROM group_expenses WHERE id = ? AND payer_id = ?",
                (expense_id, user_id)
            )
            await db.commit()
            return cursor.rowcount > 0

    # Trip operations
    async def create_trip(self, code: str, name: str, base_currency: str, owner_user_id: int) -> Trip:
        """Create a new trip."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO trips (code, name, base_currency, owner_user_id) VALUES (?, ?, ?, ?)",
                (code, name, base_currency, owner_user_id)
            )
            trip_id = cursor.lastrowid
            
            # Add owner as admin
            await db.execute(
                "INSERT INTO trip_members (trip_id, user_id, role) VALUES (?, ?, ?)",
                (trip_id, owner_user_id, 'admin')
            )
            await db.commit()
            
            return Trip(trip_id, code, name, base_currency, owner_user_id, datetime.now())

    async def get_trip_by_code(self, code: str) -> Optional[Trip]:
        """Get trip by code."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id, code, name, base_currency, owner_user_id, created_at FROM trips WHERE code = ?",
                (code,)
            )
            row = await cursor.fetchone()
            if row:
                return Trip(*row)
            return None

    async def join_trip(self, trip_id: int, user_id: int) -> bool:
        """Join a user to a trip."""
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    "INSERT INTO trip_members (trip_id, user_id, role) VALUES (?, ?, ?)",
                    (trip_id, user_id, 'member')
                )
                await db.commit()
                return True
            except:
                return False  # User already in trip

    async def get_trip_members(self, trip_id: int) -> List[Tuple[User, str]]:
        """Get all members of a trip with their roles."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT u.id, u.tg_user_id, u.name, u.created_at, u.last_seen, tm.role
                   FROM users u 
                   JOIN trip_members tm ON u.id = tm.user_id 
                   WHERE tm.trip_id = ?""",
                (trip_id,)
            )
            rows = await cursor.fetchall()
            return [(User(row[0], row[1], row[2], row[3], row[4]), row[5]) for row in rows]

    # Exchange rate operations
    async def save_exchange_rate(self, from_currency: str, to_currency: str, rate: Decimal, set_by: str = None) -> None:
        """Save exchange rate to cache."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO exchange_rates (from_currency, to_currency, rate, set_by) VALUES (?, ?, ?, ?)",
                (from_currency, to_currency, str(rate), set_by)
            )
            await db.commit()

    # Group expense operations
    async def add_group_expense(self, trip_id: int, payer_user_id: int, amount: Decimal, 
                              currency: str, rate_to_base: Decimal, amount_base: Decimal, 
                              note: Optional[str] = None) -> int:
        """Add a group expense and return expense ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO expenses (trip_id, payer_user_id, amount, currency, rate_to_base, amount_base, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (trip_id, payer_user_id, amount, currency, rate_to_base, amount_base, note)
            )
            expense_id = cursor.lastrowid
            await db.commit()
            return expense_id

    async def add_expense_shares(self, expense_id: int, shares: List[Tuple[int, Decimal]]) -> None:
        """Add expense shares for participants."""
        async with aiosqlite.connect(self.db_path) as db:
            for user_id, share_ratio in shares:
                await db.execute(
                    "INSERT INTO expense_shares (expense_id, user_id, share_ratio) VALUES (?, ?, ?)",
                    (expense_id, user_id, share_ratio)
                )
            await db.commit()

    async def get_trip_balances(self, trip_id: int) -> List[Tuple[User, Decimal]]:
        """Calculate net balances for all trip members."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT u.id, u.tg_user_id, u.name, u.created_at, u.last_seen,
                          COALESCE(paid.total, 0) - COALESCE(owed.total, 0) as net_balance
                   FROM users u
                   JOIN trip_members tm ON u.id = tm.user_id
                   LEFT JOIN (
                       SELECT payer_user_id, SUM(amount_base) as total
                       FROM expenses 
                       WHERE trip_id = ?
                       GROUP BY payer_user_id
                   ) paid ON u.id = paid.payer_user_id
                   LEFT JOIN (
                       SELECT es.user_id, SUM(e.amount_base * es.share_ratio) as total
                       FROM expenses e
                       JOIN expense_shares es ON e.id = es.expense_id
                       WHERE e.trip_id = ?
                       GROUP BY es.user_id
                   ) owed ON u.id = owed.user_id
                   WHERE tm.trip_id = ?""",
                (trip_id, trip_id, trip_id)
            )
            rows = await cursor.fetchall()
            return [(User(row[0], row[1], row[2], row[3], row[4]), Decimal(str(row[5]))) for row in rows]

    async def get_recent_trip_expenses(self, trip_id: int, limit: int = 5) -> List[Tuple[Expense, User]]:
        """Get recent expenses for a trip."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT e.id, e.trip_id, e.payer_user_id, e.amount, e.currency, 
                          e.rate_to_base, e.amount_base, e.note, e.created_at,
                          u.id, u.tg_user_id, u.name, u.created_at, u.last_seen
                   FROM expenses e
                   JOIN users u ON e.payer_user_id = u.id
                   WHERE e.trip_id = ?
                   ORDER BY e.created_at DESC
                   LIMIT ?""",
                (trip_id, limit)
            )
            rows = await cursor.fetchall()
            return [(Expense(*row[:9]), User(row[9], row[10], row[11], row[12], row[13])) for row in rows]

    async def add_group_deduction(self, user_id: int, trip_id: int, expense_id: int,
                                share_amount: Decimal, share_currency: str, wallet_id: int,
                                fx_rate_used: Decimal, deducted_amount: Decimal) -> None:
        """Record a group deduction."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO group_deductions 
                   (user_id, trip_id, expense_id, share_amount, share_currency, wallet_id, fx_rate_used, deducted_amount_in_wallet_currency)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, trip_id, expense_id, share_amount, share_currency, wallet_id, fx_rate_used, deducted_amount)
            )
            await db.commit()

    async def add_pending_deduction(self, user_id: int, trip_id: int, expense_id: int,
                                  share_amount: Decimal, share_currency: str, 
                                  suggested_wallet_id: int = None, suggested_fx_rate: Decimal = None,
                                  suggested_deduction_amount: Decimal = None) -> None:
        """Record a pending deduction (before user confirms payment)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO pending_deductions 
                   (user_id, trip_id, expense_id, share_amount, share_currency, 
                    suggested_wallet_id, suggested_fx_rate, suggested_deduction_amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, trip_id, expense_id, share_amount, share_currency, 
                 suggested_wallet_id, suggested_fx_rate, suggested_deduction_amount)
            )
            await db.commit()

    async def get_user_pending_deductions(self, user_id: int) -> List[Dict]:
        """Get all pending deductions for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT pd.*, e.note as description, e.amount as expense_amount, e.currency as expense_currency,
                          uw.currency as wallet_currency, uw.current_balance as wallet_balance
                   FROM pending_deductions pd
                   LEFT JOIN expenses e ON pd.expense_id = e.id
                   LEFT JOIN user_wallets uw ON pd.suggested_wallet_id = uw.id
                   WHERE pd.user_id = ?
                   ORDER BY pd.created_at DESC""",
                (user_id,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def confirm_pending_deduction(self, pending_id: int, wallet_id: int) -> bool:
        """Confirm a pending deduction and move it to group_deductions."""
        async with aiosqlite.connect(self.db_path) as db:
            # Get pending deduction details
            cursor = await db.execute(
                "SELECT * FROM pending_deductions WHERE id = ?", (pending_id,)
            )
            pending = await cursor.fetchone()
            if not pending:
                return False
            
            # Move to group_deductions (using suggested values for now)
            await db.execute(
                """INSERT INTO group_deductions 
                   (user_id, trip_id, expense_id, share_amount, share_currency, wallet_id, fx_rate_used, deducted_amount_in_wallet_currency)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (pending[1], pending[2], pending[3], pending[4], pending[5], 
                 wallet_id, pending[7] or 1.0, pending[8] or pending[4])
            )
            
            # Remove from pending
            await db.execute("DELETE FROM pending_deductions WHERE id = ?", (pending_id,))
            
            await db.commit()
            return True

    async def cancel_pending_deduction(self, pending_id: int) -> bool:
        """Cancel a pending deduction."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM pending_deductions WHERE id = ?", (pending_id,))
            await db.commit()
            return True

    # Group expense operations
    async def create_group_expense(self, group_id: int, payer_user_id: int, amount: Decimal, 
                                 currency: str, description: str = None) -> int:
        """Create a new group expense and return its ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """INSERT INTO group_expenses (group_id, payer_user_id, amount, currency, description)
                   VALUES (?, ?, ?, ?, ?)""",
                (group_id, payer_user_id, amount, currency, description)
            )
            await db.commit()
            return cursor.lastrowid

    async def add_expense_participants(self, expense_id: int, participants: List[Tuple[int, Decimal]]) -> None:
        """Add participants to a group expense."""
        async with aiosqlite.connect(self.db_path) as db:
            for user_id, share_amount in participants:
                await db.execute(
                    """INSERT INTO group_expense_participants (expense_id, user_id, share_amount)
                       VALUES (?, ?, ?)""",
                    (expense_id, user_id, share_amount)
                )
            await db.commit()

    async def get_group_expense(self, expense_id: int) -> Optional[GroupExpense]:
        """Get a group expense by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT id, group_id, payer_user_id, amount, currency, description, created_at, settled
                   FROM group_expenses WHERE id = ?""",
                (expense_id,)
            )
            row = await cursor.fetchone()
            if row:
                return GroupExpense(*row)
            return None

    async def get_expense_participants(self, expense_id: int) -> List[GroupExpenseParticipant]:
        """Get all participants of a group expense."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT id, expense_id, user_id, share_amount, paid, reminded
                   FROM group_expense_participants WHERE expense_id = ?""",
                (expense_id,)
            )
            rows = await cursor.fetchall()
            return [GroupExpenseParticipant(*row) for row in rows]

    async def mark_participant_paid(self, expense_id: int, user_id: int) -> None:
        """Mark a participant as having paid their share."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """UPDATE group_expense_participants SET paid = TRUE 
                   WHERE expense_id = ? AND user_id = ?""",
                (expense_id, user_id)
            )
            await db.commit()

    async def get_unpaid_participants(self, group_id: int) -> List[Tuple[GroupExpense, GroupExpenseParticipant, User]]:
        """Get all unpaid participants in a group."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT ge.id, ge.group_id, ge.payer_user_id, ge.amount, ge.currency, 
                          ge.description, ge.created_at, ge.settled,
                          gep.id, gep.expense_id, gep.user_id, gep.share_amount, gep.paid, gep.reminded,
                          u.id, u.tg_user_id, u.name, u.created_at, u.last_seen
                   FROM group_expenses ge
                   JOIN group_expense_participants gep ON ge.id = gep.expense_id
                   JOIN users u ON gep.user_id = u.id
                   WHERE ge.group_id = ? AND gep.paid = FALSE AND ge.settled = FALSE
                   ORDER BY ge.created_at DESC""",
                (group_id,)
            )
            rows = await cursor.fetchall()
            return [(GroupExpense(*row[:8]), GroupExpenseParticipant(*row[8:14]), User(row[14], row[15], row[16], row[17], row[18])) for row in rows]

    async def update_group_debts(self, group_id: int, debtor_id: int, creditor_id: int, 
                               amount: Decimal, currency: str) -> None:
        """Update debt between two users in a group."""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if debt already exists
            cursor = await db.execute(
                """SELECT amount FROM group_debts 
                   WHERE group_id = ? AND debtor_user_id = ? AND creditor_user_id = ? AND currency = ?""",
                (group_id, debtor_id, creditor_id, amount, currency)
            )
            existing = await cursor.fetchone()
            
            if existing:
                new_amount = Decimal(str(existing[0])) + amount
                if new_amount == 0:
                    # Delete if debt is settled
                    await db.execute(
                        """DELETE FROM group_debts 
                           WHERE group_id = ? AND debtor_user_id = ? AND creditor_user_id = ? AND currency = ?""",
                        (group_id, debtor_id, creditor_id, currency)
                    )
                else:
                    # Update existing debt
                    await db.execute(
                        """UPDATE group_debts SET amount = ?, last_updated = CURRENT_TIMESTAMP
                           WHERE group_id = ? AND debtor_user_id = ? AND creditor_user_id = ? AND currency = ?""",
                        (new_amount, group_id, debtor_id, creditor_id, currency)
                    )
            else:
                # Create new debt
                await db.execute(
                    """INSERT INTO group_debts (group_id, debtor_user_id, creditor_user_id, amount, currency)
                       VALUES (?, ?, ?, ?, ?)""",
                    (group_id, debtor_id, creditor_id, amount, currency)
                )
            await db.commit()

    async def get_group_debts(self, group_id: int) -> List[Tuple[GroupDebt, User, User]]:
        """Get all debts in a group with debtor and creditor info."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT gd.id, gd.group_id, gd.debtor_user_id, gd.creditor_user_id, 
                          gd.amount, gd.currency, gd.last_updated,
                          u1.id, u1.tg_user_id, u1.name, u1.created_at, u1.last_seen,
                          u2.id, u2.tg_user_id, u2.name, u2.created_at, u2.last_seen
                   FROM group_debts gd
                   JOIN users u1 ON gd.debtor_user_id = u1.id
                   JOIN users u2 ON gd.creditor_user_id = u2.id
                   WHERE gd.group_id = ? AND gd.amount > 0
                   ORDER BY gd.amount DESC""",
                (group_id,)
            )
            rows = await cursor.fetchall()
            return [(GroupDebt(*row[:7]), User(row[7], row[8], row[9], row[10], row[11]), User(row[12], row[13], row[14], row[15], row[16])) for row in rows]

    async def optimize_group_debts(self, group_id: int, currency: str) -> List[Tuple[User, User, Decimal]]:
        """Optimize debts in a group to minimize transactions."""
        debts = await self.get_group_debts(group_id)
        
        # Filter by currency and build balance map
        balances = {}  # user_id -> net balance (positive = owed money, negative = owes money)
        
        for debt, debtor, creditor in debts:
            if debt.currency != currency:
                continue
                
            if debtor.id not in balances:
                balances[debtor.id] = Decimal('0')
            if creditor.id not in balances:
                balances[creditor.id] = Decimal('0')
                
            balances[debtor.id] -= debt.amount  # They owe money
            balances[creditor.id] += debt.amount  # They are owed money
        
        # Separate creditors (positive) and debtors (negative)
        creditors = [(user_id, amount) for user_id, amount in balances.items() if amount > 0]
        debtors = [(user_id, -amount) for user_id, amount in balances.items() if amount < 0]
        
        # Optimize transactions
        transactions = []
        creditors.sort(key=lambda x: x[1], reverse=True)  # Largest creditors first
        debtors.sort(key=lambda x: x[1], reverse=True)    # Largest debtors first
        
        async with aiosqlite.connect(self.db_path) as db:
            i = j = 0
            while i < len(creditors) and j < len(debtors):
                creditor_id, credit_amount = creditors[i]
                debtor_id, debt_amount = debtors[j]
                
                transfer_amount = min(credit_amount, debt_amount)
                
                # Get user objects for the transaction
                cursor = await db.execute(
                    "SELECT id, tg_user_id, name, created_at, last_seen FROM users WHERE id IN (?, ?)",
                    (debtor_id, creditor_id)
                )
                user_rows = await cursor.fetchall()
                user_map = {row[0]: User(*row) for row in user_rows}
                
                transactions.append((user_map[debtor_id], user_map[creditor_id], transfer_amount))
                
                # Update balances
                creditors[i] = (creditor_id, credit_amount - transfer_amount)
                debtors[j] = (debtor_id, debt_amount - transfer_amount)
            
                # Move to next creditor/debtor if current one is settled
                if creditors[i][1] == 0:
                    i += 1
                if debtors[j][1] == 0:
                    j += 1
        
        return transactions

    # Exchange Rate Functions
    async def set_exchange_rate(self, from_currency: str, to_currency: str, rate: Decimal, set_by: int):
        """Set exchange rate (admin only)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO exchange_rates (from_currency, to_currency, rate, set_by)
                VALUES (?, ?, ?, ?)
            """, (from_currency, to_currency, str(rate), set_by))
            await db.commit()

    async def get_exchange_rate(self, from_currency: str, to_currency: str) -> Optional[Decimal]:
        """Get exchange rate between currencies."""
        if from_currency == to_currency:
            return Decimal('1')
            
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT rate FROM exchange_rates 
                WHERE from_currency = ? AND to_currency = ?
            """, (from_currency, to_currency))
            result = await cursor.fetchone()
            
            if result:
                return Decimal(str(result[0]))
            
            # Try reverse rate
            cursor = await db.execute("""
                SELECT rate FROM exchange_rates 
                WHERE from_currency = ? AND to_currency = ?
            """, (to_currency, from_currency))
            result = await cursor.fetchone()
            
            if result:
                return Decimal('1') / Decimal(str(result[0]))
            
            return None

    async def get_latest_exchange_rate(self, from_currency: str, to_currency: str) -> Optional[dict]:
        """Get the latest exchange rate with timestamp."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT rate, created_at FROM exchange_rates 
                WHERE from_currency = ? AND to_currency = ?
                ORDER BY created_at DESC LIMIT 1
            """, (from_currency, to_currency))
            result = await cursor.fetchone()
            
            if result:
                return {
                    'rate': Decimal(str(result[0])),
                    'created_at': result[1]
                }
            return None

    async def get_all_exchange_rates(self) -> List[Tuple]:
        """Get all exchange rates."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT from_currency, to_currency, rate, created_at 
                FROM exchange_rates 
                ORDER BY created_at DESC
            """)
            return await cursor.fetchall()

    # Bank Account Functions
    async def add_bank_account(self, user_id: int, bank_code: str, bank_name: str, 
                              account_number: str, account_name: str) -> int:
        """Add bank account for user."""
        async with aiosqlite.connect(self.db_path) as db:
            # If this is first account, make it default
            cursor = await db.execute("""
                SELECT COUNT(*) FROM bank_accounts WHERE user_id = ?
            """, (user_id,))
            count = (await cursor.fetchone())[0]
            is_default = count == 0
            
            cursor = await db.execute("""
                INSERT INTO bank_accounts (user_id, bank_code, bank_name, account_number, account_name, is_default)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, bank_code, bank_name, account_number, account_name, is_default))
            await db.commit()
            return cursor.lastrowid

    async def get_user_bank_accounts(self, user_id: int) -> List[Tuple]:
        """Get all bank accounts for user."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT id, bank_code, bank_name, account_number, account_name, is_default
                FROM bank_accounts 
                WHERE user_id = ?
                ORDER BY is_default DESC, created_at ASC
            """, (user_id,))
            return await cursor.fetchall()

    async def get_default_bank_account(self, user_id: int) -> Optional[Tuple]:
        """Get default bank account for user."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT id, bank_code, bank_name, account_number, account_name
                FROM bank_accounts 
                WHERE user_id = ? AND is_default = TRUE
            """, (user_id,))
            return await cursor.fetchone()

    async def set_default_bank_account(self, user_id: int, account_id: int):
        """Set default bank account."""
        async with aiosqlite.connect(self.db_path) as db:
            # Remove default from all accounts
            await db.execute("""
                UPDATE bank_accounts SET is_default = FALSE WHERE user_id = ?
            """, (user_id,))
            # Set new default
            await db.execute("""
                UPDATE bank_accounts SET is_default = TRUE WHERE id = ? AND user_id = ?
            """, (account_id, user_id))
            await db.commit()

    # Payment Preferences Functions
    async def update_payment_preferences(self, user_id: int, accept_vnd: bool = None, 
                                        auto_convert: bool = None, preferred_bank_id: int = None):
        """Update user payment preferences."""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if preferences exist
            cursor = await db.execute("""
                SELECT user_id FROM payment_preferences WHERE user_id = ?
            """, (user_id,))
            exists = await cursor.fetchone()
            
            if exists:
                # Update existing
                updates = []
                params = []
                if accept_vnd is not None:
                    updates.append("accept_vnd_payments = ?")
                    params.append(accept_vnd)
                if auto_convert is not None:
                    updates.append("auto_convert_debts = ?")
                    params.append(auto_convert)
                if preferred_bank_id is not None:
                    updates.append("preferred_bank_id = ?")
                    params.append(preferred_bank_id)
                
                if updates:
                    params.append(user_id)
                    await db.execute(f"""
                        UPDATE payment_preferences SET {', '.join(updates)} WHERE user_id = ?
                    """, params)
            else:
                # Insert new
                await db.execute("""
                    INSERT INTO payment_preferences (user_id, accept_vnd_payments, auto_convert_debts, preferred_bank_id)
                    VALUES (?, ?, ?, ?)
                """, (user_id, accept_vnd or False, auto_convert or False, preferred_bank_id))
            
            await db.commit()

    async def get_payment_preferences(self, user_id: int) -> Optional[Tuple]:
        """Get user payment preferences."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT accept_vnd_payments, auto_convert_debts, preferred_bank_id
                FROM payment_preferences WHERE user_id = ?
            """, (user_id,))
            return await cursor.fetchone()
            creditor_id, credit_amount = creditors[i]
            debtor_id, debt_amount = debtors[j]
            
            # Transfer minimum of what creditor is owed and debtor owes
            transfer_amount = min(credit_amount, debt_amount)
            
            if transfer_amount > 0:
                # Get user objects
                async with aiosqlite.connect(self.db_path) as db:
                    cursor = await db.execute(
                        "SELECT id, tg_user_id, name, created_at, last_seen FROM users WHERE id IN (?, ?)",
                        (debtor_id, creditor_id)
                    )
                    user_rows = await cursor.fetchall()
                    user_map = {row[0]: User(*row) for row in user_rows}
                
                transactions.append((user_map[debtor_id], user_map[creditor_id], transfer_amount))
                
                # Update balances
                creditors[i] = (creditor_id, credit_amount - transfer_amount)
                debtors[j] = (debtor_id, debt_amount - transfer_amount)
            
            # Move to next creditor/debtor if current one is settled
            if creditors[i][1] == 0:
                i += 1
            if debtors[j][1] == 0:
                j += 1
        
        return transactions

    async def mark_participant_paid(self, expense_id: int, participant_id: int, payment_method: str) -> bool:
        """Mark a participant as paid for a group expense."""
        async with aiosqlite.connect(self.db_path) as db:
            paid_status = True if payment_method == 'paid_now' else False
            await db.execute(
                """UPDATE group_expense_participants 
                   SET paid = ?, payment_method = ?
                   WHERE expense_id = ? AND user_id = ?""",
                (paid_status, payment_method, expense_id, participant_id)
            )
            await db.commit()
            return True

    async def get_expense_by_id(self, expense_id: int) -> dict:
        """Get expense details by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT id, group_id, payer_user_id, amount, currency, description, created_at
                   FROM group_expenses WHERE id = ?""",
                (expense_id,)
            )
            row = await cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'group_id': row[1], 
                    'payer_user_id': row[2],
                    'amount': row[3],
                    'currency': row[4],
                    'description': row[5],
                    'created_at': row[6]
                }
            return None

    async def get_groups_with_pending_debts(self) -> List[int]:
        """Get all group IDs that have pending debts."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT DISTINCT group_id 
                   FROM group_debts 
                   WHERE amount > 0""")
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_wallet_transactions(self, wallet_id: int, limit: int = 10):
        """Get recent transactions for a specific wallet."""
        async with aiosqlite.connect(self.db_path) as db:
            transactions = []
            
            # Get wallet adjustments (top-ups, decreases)
            cursor = await db.execute("""
                SELECT delta_amount, reason, created_at, 'adjustment' as type
                FROM wallet_adjustments 
                WHERE wallet_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (wallet_id, limit))
            
            adjustment_rows = await cursor.fetchall()
            for row in adjustment_rows:
                amount, reason, created_at, tx_type = row
                transactions.append({
                    'amount': amount,
                    'description': reason,
                    'created_at': created_at,
                    'type': tx_type
                })
            
            # Get personal expenses from this wallet
            cursor = await db.execute("""
                SELECT -amount, note, created_at, 'expense' as type
                FROM personal_expenses 
                WHERE wallet_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (wallet_id, limit))
            
            expense_rows = await cursor.fetchall()
            for row in expense_rows:
                amount, note, created_at, tx_type = row
                description = note if note else "Chi tiêu cá nhân"
                transactions.append({
                    'amount': amount,
                    'description': description,
                    'created_at': created_at,
                    'type': tx_type
                })
            
            # Sort all transactions by date and limit
            transactions.sort(key=lambda x: x['created_at'], reverse=True)
            return transactions[:limit]
