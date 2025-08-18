"""
Configuration settings for the bot.
Centralized configuration management.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', '5245151002'))

# Database configuration
DATABASE_PATH = os.getenv('DATABASE_PATH', 'bot.db')

# Timezone configuration  
DEFAULT_TIMEZONE = os.getenv('TIMEZONE', 'Asia/Ho_Chi_Minh')

# Currency configuration
DEFAULT_CURRENCY = 'VND'
SUPPORTED_CURRENCIES = ['VND', 'USD', 'TWD']

# Notification configuration
DAILY_SUMMARY_HOUR = 10  # 10h sáng

# VietQR configuration
VIETQR_TIMEOUT = 30  # seconds

# Validation limits
MIN_ACCOUNT_NUMBER_LENGTH = 6
MAX_ACCOUNT_NUMBER_LENGTH = 19
MIN_ACCOUNT_NAME_LENGTH = 2
MIN_AMOUNT = 0.01
MAX_AMOUNT = 999999999

# Response timeouts (seconds)
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 5.0
