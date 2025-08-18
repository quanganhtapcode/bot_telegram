"""
VietQR service for generating payment QR codes and handling bank transfers.
"""
import asyncio
import logging
from decimal import Decimal
from typing import Optional, List, Tuple

from models import VietQRData, BankAccount, PaymentPreference
from db import Database

logger = logging.getLogger(__name__)

# Bank data from VietQR API - Complete list
VIETNAM_BANKS = {
    # Major banks first
    "VCB": {"name": "Vietcombank", "bin": "970436"},
    "BIDV": {"name": "BIDV", "bin": "970418"},
    "ICB": {"name": "VietinBank", "bin": "970415"},
    "VBA": {"name": "Agribank", "bin": "970405"},
    "TCB": {"name": "Techcombank", "bin": "970407"},
    "MB": {"name": "MBBank", "bin": "970422"},
    "ACB": {"name": "ACB", "bin": "970416"},
    "VPB": {"name": "VPBank", "bin": "970432"},
    "TPB": {"name": "TPBank", "bin": "970423"},
    "STB": {"name": "Sacombank", "bin": "970403"},
    "HDB": {"name": "HDBank", "bin": "970437"},
    "VIB": {"name": "VIB", "bin": "970441"},
    "SHB": {"name": "SHB", "bin": "970443"},
    "MSB": {"name": "MSB", "bin": "970426"},
    "OCB": {"name": "OCB", "bin": "970448"},
    "EIB": {"name": "Eximbank", "bin": "970431"},
    
    # Other banks
    "VCCB": {"name": "VietCapitalBank", "bin": "970454"},
    "SCB": {"name": "SCB", "bin": "970429"},
    "BAB": {"name": "BacABank", "bin": "970409"},
    "SGICB": {"name": "SaigonBank", "bin": "970400"},
    "PVCB": {"name": "PVcomBank", "bin": "970412"},
    "NCB": {"name": "NCB", "bin": "970419"},
    "SHBVN": {"name": "ShinhanBank", "bin": "970424"},
    "ABB": {"name": "ABBANK", "bin": "970425"},
    "VAB": {"name": "VietABank", "bin": "970427"},
    "NAB": {"name": "NamABank", "bin": "970428"},
    "PGB": {"name": "PGBank", "bin": "970430"},
    "VIETBANK": {"name": "VietBank", "bin": "970433"},
    "BVB": {"name": "BaoVietBank", "bin": "970438"},
    "SEAB": {"name": "SeABank", "bin": "970440"},
    "LPB": {"name": "LPBank", "bin": "970449"},
    "KLB": {"name": "KienLongBank", "bin": "970452"},
    "COOPBANK": {"name": "COOPBANK", "bin": "970446"},
    "CAKE": {"name": "CAKE", "bin": "546034"},
    "UBANK": {"name": "Ubank", "bin": "546035"},
    "TIMO": {"name": "Timo", "bin": "963388"},
    "KBANK": {"name": "KBank", "bin": "668888"},
    "WVN": {"name": "Woori", "bin": "970457"},
    "CIMB": {"name": "CIMB", "bin": "422589"},
    "PVDB": {"name": "PVcomBank Pay", "bin": "971133"}
}


class VietQRService:
    """Service for VietQR payment handling."""

    def __init__(self, db: Database):
        self.db = db

    async def generate_payment_qr(self, user_id: int, amount: Decimal, 
                                description: str, currency: str = "VND") -> Optional[str]:
        """Generate VietQR payment URL for user."""
        try:
            # Get user's default bank account
            bank_account = await self.db.get_default_bank_account(user_id)
            if not bank_account:
                return None

            account_id, bank_code, bank_name, account_number, account_name = bank_account

            # Convert amount to VND if needed
            vnd_amount = amount
            if currency != "VND":
                rate = await self.db.get_exchange_rate(currency, "VND")
                if rate:
                    vnd_amount = amount * rate
                else:
                    logger.warning(f"No exchange rate found for {currency} to VND")
                    return None

            # Create VietQR data
            qr_data = VietQRData(
                bank_code=bank_code,
                account_number=account_number,
                account_name=account_name,
                amount=vnd_amount,
                description=description,
                template="compact2"
            )

            return qr_data.generate_url()

        except Exception as e:
            logger.error(f"Error generating QR for user {user_id}: {e}")
            return None

    async def generate_qr_direct(self, bank_code: str, account_number: str, 
                                account_name: str, amount: Decimal = 0, 
                                description: str = "Chuyển khoản") -> Optional[str]:
        """Generate VietQR payment URL with direct bank info."""
        try:
            # Create VietQR data
            qr_data = VietQRData(
                bank_code=bank_code,
                account_number=account_number,
                account_name=account_name,
                amount=amount,
                description=description,
                template="compact2"
            )

            return qr_data.generate_url()

        except Exception as e:
            logger.error(f"Error generating direct QR: {e}")
            return None

    async def get_user_payment_info(self, user_id: int) -> Optional[Tuple[bool, BankAccount]]:
        """Get user's payment preferences and default bank account."""
        try:
            # Check if user accepts VND payments
            preferences = await self.db.get_payment_preferences(user_id)
            if not preferences or not preferences[0]:  # accept_vnd_payments
                return None

            # Get default bank account
            bank_account = await self.db.get_default_bank_account(user_id)
            if not bank_account:
                return None

            return (True, BankAccount(
                id=bank_account[0],
                user_id=user_id,
                bank_code=bank_account[1],
                bank_name=bank_account[2],
                account_number=bank_account[3],
                account_name=bank_account[4],
                is_default=True,
                created_at=None
            ))

        except Exception as e:
            logger.error(f"Error getting payment info for user {user_id}: {e}")
            return None

    async def convert_currency(self, amount: Decimal, from_currency: str, 
                             to_currency: str) -> Optional[Decimal]:
        """Convert amount between currencies using saved exchange rates."""
        if from_currency == to_currency:
            return amount
            
        rate = await self.db.get_exchange_rate(from_currency, to_currency)
        if rate:
            return amount * rate
        return None

    def get_bank_list(self) -> List[Tuple[str, str]]:
        """Get list of supported banks."""
        return [(code, data["name"]) for code, data in VIETNAM_BANKS.items()]

    def validate_bank_code(self, bank_code: str) -> bool:
        """Validate bank code."""
        return bank_code in VIETNAM_BANKS

    def get_bank_name(self, bank_code: str) -> Optional[str]:
        """Get bank name from code."""
        return VIETNAM_BANKS.get(bank_code, {}).get("name")
