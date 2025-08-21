"""
Azure SQL Database configuration for the Telegram bot.
"""
import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class AzureSQLConfig:
    """Configuration class for Azure SQL Database."""
    
    def __init__(self):
        # Azure SQL Database connection parameters
        self.server = os.getenv('AZURE_SQL_SERVER')  # e.g., 'your-server.database.windows.net'
        self.database = os.getenv('AZURE_SQL_DATABASE', 'telegram_bot')
        self.username = os.getenv('AZURE_SQL_USERNAME')
        self.password = os.getenv('AZURE_SQL_PASSWORD')
        self.driver = os.getenv('AZURE_SQL_DRIVER', 'ODBC Driver 18 for SQL Server')
        
        # Connection options
        self.encrypt = os.getenv('AZURE_SQL_ENCRYPT', 'yes')
        self.trust_server_certificate = os.getenv('AZURE_SQL_TRUST_CERT', 'no')
        self.connection_timeout = int(os.getenv('AZURE_SQL_TIMEOUT', '30'))
        
        # Fallback to SQLite if Azure SQL not configured
        self.use_sqlite_fallback = os.getenv('USE_SQLITE_FALLBACK', 'true').lower() == 'true'
        self.sqlite_path = os.getenv('DATABASE_PATH', './bot.db')
    
    @property
    def is_azure_configured(self) -> bool:
        """Check if Azure SQL Database is properly configured."""
        return all([
            self.server,
            self.database, 
            self.username,
            self.password
        ])
    
    @property
    def connection_string(self) -> str:
        """Generate Azure SQL Database connection string."""
        if not self.is_azure_configured:
            raise ValueError("Azure SQL Database not properly configured")
        
        return (
            f"mssql+pyodbc://{self.username}:{self.password}@{self.server}/"
            f"{self.database}?driver={self.driver.replace(' ', '+')}"
            f"&encrypt={self.encrypt}&trustServerCertificate={self.trust_server_certificate}"
        )
    
    @property 
    def pyodbc_connection_string(self) -> str:
        """Generate pyodbc connection string."""
        if not self.is_azure_configured:
            raise ValueError("Azure SQL Database not properly configured")
            
        return (
            f"DRIVER={{{self.driver}}};SERVER={self.server};DATABASE={self.database};"
            f"UID={self.username};PWD={self.password};Encrypt={self.encrypt};"
            f"TrustServerCertificate={self.trust_server_certificate};"
            f"Connection Timeout={self.connection_timeout};"
        )

# Global configuration instance
azure_config = AzureSQLConfig()
