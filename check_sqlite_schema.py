#!/usr/bin/env python3
"""
Check SQLite database schema to see what columns exist.
"""
import sqlite3
import sys

def check_sqlite_schema(db_path="bot.db"):
    """Check SQLite database schema."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        print(f"📊 SQLite Database Schema ({db_path}):")
        print("=" * 50)
        
        for (table_name,) in tables:
            print(f"\n🗂️ Table: {table_name}")
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            
            for col_info in columns:
                col_id, col_name, col_type, not_null, default_val, pk = col_info
                pk_marker = " (PK)" if pk else ""
                null_marker = " NOT NULL" if not_null else ""
                default_marker = f" DEFAULT {default_val}" if default_val else ""
                print(f"  • {col_name} {col_type}{pk_marker}{null_marker}{default_marker}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error checking schema: {e}")

if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "bot.db"
    check_sqlite_schema(db_path)
