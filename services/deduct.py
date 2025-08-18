"""
Service for handling automatic deductions from personal wallets for group expenses.
"""
from decimal import Decimal
from typing import List, Optional, Tuple
from models import User, UserWallet, UserSettings
from db import Database
from services.currency import CurrencyService
import logging

logger = logging.getLogger(__name__)


class DeductionService:
    def __init__(self, db: Database, currency_service: CurrencyService):
        self.db = db
        self.currency_service = currency_service

    async def suggest_wallet_for_deduction(self, user_id: int, share_amount: Decimal, 
                                         share_currency: str) -> List[Tuple[UserWallet, Decimal, Decimal]]:
        """
        Suggest wallets for deduction with priority:
        1. Same currency wallet
        2. Preferred currency wallet  
        3. Any other wallet
        
        Returns list of (wallet, fx_rate, deduction_amount) tuples.
        """
        user_wallets = await self.db.get_user_wallets(user_id)
        user_settings = await self.db.get_user_settings(user_id)
        suggestions = []

        # Priority 1: Same currency wallet
        for wallet in user_wallets:
            if wallet.currency == share_currency:
                # Negative balance is always allowed now
                suggestions.append((wallet, Decimal('1.0'), share_amount))
                return suggestions  # Best match, return immediately

        # Priority 2: Preferred currency wallet
        preferred_wallet = None
        for wallet in user_wallets:
            if wallet.currency == user_settings.preferred_currency:
                preferred_wallet = wallet
                break

        if preferred_wallet:
            try:
                fx_rate, converted_amount = await self.currency_service.convert(
                    share_amount, share_currency, preferred_wallet.currency
                )
                # Negative balance is always allowed now
                suggestions.append((preferred_wallet, fx_rate, converted_amount))
            except Exception as e:
                logger.error(f"Error converting to preferred currency: {e}")

        # Priority 3: Any wallet with any balance
        for wallet in user_wallets:
            if wallet.currency not in [share_currency, user_settings.preferred_currency]:
                try:
                    fx_rate, converted_amount = await self.currency_service.convert(
                        share_amount, share_currency, wallet.currency
                    )
                    # Negative balance is always allowed now
                    suggestions.append((wallet, fx_rate, converted_amount))
                except Exception as e:
                    logger.error(f"Error converting to {wallet.currency}: {e}")

        return suggestions

    async def process_auto_deduction(self, user_id: int, trip_id: int, expense_id: int,
                                   share_amount: Decimal, share_currency: str) -> Optional[str]:
        """
        Create pending deduction (no immediate wallet deduction).
        Returns success message or None if no suitable wallet found.
        """
        suggestions = await self.suggest_wallet_for_deduction(user_id, share_amount, share_currency)
        
        if not suggestions:
            # Create pending without suggested wallet
            await self.db.add_pending_deduction(
                user_id, trip_id, expense_id, share_amount, share_currency
            )
            formatted_share = self.currency_service.format_amount(share_amount, share_currency)
            return f"📋 Đã tạo ghi nợ {formatted_share} - chưa trừ từ ví. Xem /wallets để thanh toán."

        # Use the first (best) suggestion
        wallet, fx_rate, deduction_amount = suggestions[0]
        
        # Create pending deduction with suggestion
        await self.db.add_pending_deduction(
            user_id, trip_id, expense_id, share_amount, share_currency,
            wallet.id, fx_rate, deduction_amount
        )
        
        formatted_share = self.currency_service.format_amount(share_amount, share_currency)
        formatted_deduction = self.currency_service.format_amount(deduction_amount, wallet.currency)
        
        if share_currency == wallet.currency:
            return f"📋 Đã tạo ghi nợ {formatted_share} - đề xuất từ ví {wallet.currency}. Xem /wallets để thanh toán."
        else:
            return f"📋 Đã tạo ghi nợ {formatted_share} - đề xuất trừ {formatted_deduction} từ ví {wallet.currency}. Xem /wallets để thanh toán."

    async def manual_deduction(self, user_id: int, trip_id: int, expense_id: int,
                             share_amount: Decimal, share_currency: str, 
                             wallet_id: int) -> Tuple[bool, str]:
        """
        Create pending deduction for manual wallet selection.
        """
        wallet = await self.db.get_wallet(wallet_id)
        if not wallet or wallet.user_id != user_id:
            return False, "Ví không tồn tại hoặc không thuộc về bạn"

        try:
            if wallet.currency == share_currency:
                fx_rate = Decimal('1.0')
                deduction_amount = share_amount
            else:
                fx_rate, deduction_amount = await self.currency_service.convert(
                    share_amount, share_currency, wallet.currency
                )

            # Create pending deduction
            await self.db.add_pending_deduction(
                user_id, trip_id, expense_id, share_amount, share_currency,
                wallet.id, fx_rate, deduction_amount
            )

            formatted_share = self.currency_service.format_amount(share_amount, share_currency)
            formatted_deduction = self.currency_service.format_amount(deduction_amount, wallet.currency)

            if share_currency == wallet.currency:
                return True, f"📋 Đã tạo ghi nợ {formatted_share} từ ví {wallet.currency}. Xem /wallets để thanh toán."
            else:
                return True, f"📋 Đã tạo ghi nợ {formatted_share} - sẽ trừ {formatted_deduction} từ ví {wallet.currency}. Xem /wallets để thanh toán."

        except Exception as e:
            logger.error(f"Error in manual deduction: {e}")
            return False, "Lỗi khi xử lý giao dịch"

    async def create_wallet_for_deduction(self, user_id: int, trip_id: int, expense_id: int,
                                        share_amount: Decimal, share_currency: str) -> Tuple[bool, str]:
        """
        Create a new wallet with pending deduction.
        """
        try:
            # Create wallet with zero balance
            initial_amount = Decimal('0')
            wallet = await self.db.create_wallet(
                user_id, share_currency, initial_amount, f"Tạo cho chi tiêu nhóm"
            )

            # Create pending deduction
            await self.db.add_pending_deduction(
                user_id, trip_id, expense_id, share_amount, share_currency,
                wallet.id, Decimal('1.0'), share_amount
            )

            formatted_amount = self.currency_service.format_amount(share_amount, share_currency)
            return True, f"📋 Đã tạo ví {share_currency} với ghi nợ {formatted_amount}. Xem /wallets để thanh toán."

        except Exception as e:
            logger.error(f"Error creating wallet for deduction: {e}")
            return False, "Lỗi khi tạo ví mới"
