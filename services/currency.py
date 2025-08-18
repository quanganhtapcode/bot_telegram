"""
Currency conversion service using exchangerate.host API.
"""
import httpx
import logging
from decimal import Decimal
from datetime import datetime
from typing import Tuple, Optional
from db import Database

logger = logging.getLogger(__name__)


class CurrencyService:
    def __init__(self, db: Database, base_url: str = "https://api.exchangerate.host"):
        self.db = db
        self.base_url = base_url
        self.client = httpx.AsyncClient()

    async def convert(self, amount: Decimal, from_currency: str, to_currency: str) -> Tuple[Decimal, Decimal]:
        """
        Convert amount from one currency to another.
        Returns (exchange_rate, converted_amount).
        """
        if from_currency == to_currency:
            return Decimal('1.0'), amount

        # Check admin-set exchange rate first (highest priority)
        admin_rate = await self.db.get_exchange_rate(from_currency, to_currency)
        if admin_rate:
            converted_amount = amount * admin_rate
            logger.info(f"Using admin-set rate {from_currency}/{to_currency}: {admin_rate}")
            return admin_rate, converted_amount.quantize(Decimal('0.01'))

        # Check cache for API rates
        today = datetime.now().strftime('%Y-%m-%d')
        cached_rate = await self.db.get_exchange_rate(today, from_currency, to_currency)
        
        if cached_rate:
            converted_amount = amount * cached_rate
            return cached_rate, converted_amount.quantize(Decimal('0.01'))

        # Fetch from API as fallback
        try:
            url = f"{self.base_url}/convert"
            params = {
                'from': from_currency,
                'to': to_currency,
                'amount': str(amount)
            }
            
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get('success', False):
                rate = Decimal(str(data['info']['rate']))
                converted_amount = Decimal(str(data['result']))
                
                # Cache the rate
                await self.db.save_exchange_rate(from_currency, to_currency, rate)
                
                return rate, converted_amount.quantize(Decimal('0.01'))
            else:
                logger.error(f"Exchange rate API error: {data}")
                raise ValueError("Không thể lấy tỷ giá hối đoái")
                
        except httpx.RequestError as e:
            logger.error(f"HTTP error fetching exchange rate: {e}")
            raise ValueError("Lỗi kết nối khi lấy tỷ giá hối đoái")
        except Exception as e:
            logger.error(f"Error converting currency: {e}")
            raise ValueError("Lỗi chuyển đổi tiền tệ")

    async def get_rate(self, from_currency: str, to_currency: str) -> Decimal:
        """Get exchange rate without converting amount."""
        rate, _ = await self.convert(Decimal('1.0'), from_currency, to_currency)
        return rate

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    def format_amount(self, amount: Decimal, currency: str) -> str:
        """Format amount with currency symbol."""
        currency_symbols = {
            'TWD': 'NT$',
            'USD': '$',
            'EUR': '€',
            'GBP': '£',
            'JPY': '¥',
            'VND': '₫',
        }
        
        symbol = currency_symbols.get(currency, currency)
        if currency == 'VND':
            return f"{amount:,.0f} {symbol}"
        else:
            return f"{symbol} {amount:,.2f}"
