"""
Settlement calculation service for optimal debt resolution.
"""
from decimal import Decimal
from typing import List, Tuple, Dict
from models import User
import logging

logger = logging.getLogger(__name__)


class SettlementService:
    def __init__(self):
        pass

    def calculate_settlements(self, balances: List[Tuple[User, Decimal]]) -> List[Tuple[User, User, Decimal]]:
        """
        Calculate minimal transfers using greedy algorithm.
        Returns list of (debtor, creditor, amount) tuples.
        """
        # Filter out zero balances and round to 2 decimal places
        significant_balances = []
        for user, balance in balances:
            rounded_balance = balance.quantize(Decimal('0.01'))
            if abs(rounded_balance) >= Decimal('0.01'):
                significant_balances.append((user, rounded_balance))
        
        if not significant_balances:
            return []

        # Separate debtors and creditors
        debtors = [(user, abs(balance)) for user, balance in significant_balances if balance < 0]
        creditors = [(user, balance) for user, balance in significant_balances if balance > 0]
        
        # Sort debtors and creditors by amount (largest first)
        debtors.sort(key=lambda x: x[1], reverse=True)
        creditors.sort(key=lambda x: x[1], reverse=True)
        
        settlements = []
        
        # Greedy matching: largest debtor pays largest creditor
        while debtors and creditors:
            debtor, debt_amount = debtors[0]
            creditor, credit_amount = creditors[0]
            
            # Calculate transfer amount (minimum of debt and credit)
            transfer_amount = min(debt_amount, credit_amount)
            
            # Record the settlement
            settlements.append((debtor, creditor, transfer_amount))
            
            # Update amounts
            debt_amount -= transfer_amount
            credit_amount -= transfer_amount
            
            # Remove or update the lists
            if debt_amount <= Decimal('0.01'):
                debtors.pop(0)
            else:
                debtors[0] = (debtor, debt_amount)
                
            if credit_amount <= Decimal('0.01'):
                creditors.pop(0)
            else:
                creditors[0] = (creditor, credit_amount)
        
        return settlements

    def format_settlement_summary(self, settlements: List[Tuple[User, User, Decimal]], currency: str) -> str:
        """Format settlement summary in Vietnamese."""
        if not settlements:
            return "✅ Tất cả đã thanh toán xong!"
        
        currency_symbols = {
            'TWD': 'NT$',
            'USD': '$',
            'EUR': '€',
            'GBP': '£',
            'JPY': '¥',
            'VND': '₫',
        }
        
        symbol = currency_symbols.get(currency, currency)
        
        lines = ["💰 Thanh toán tối ưu:"]
        for debtor, creditor, amount in settlements:
            if currency == 'VND':
                amount_str = f"{amount:,.0f} {symbol}"
            else:
                amount_str = f"{symbol} {amount:,.2f}"
            lines.append(f"• {debtor.name} → {creditor.name}: {amount_str}")
        
        return "\n".join(lines)

    def validate_settlement_balance(self, balances: List[Tuple[User, Decimal]]) -> bool:
        """Validate that total balance sums to approximately zero."""
        total = sum(balance for _, balance in balances)
        return abs(total) < Decimal('0.01')

    def get_balance_summary(self, balances: List[Tuple[User, Decimal]], currency: str) -> str:
        """Format balance summary in Vietnamese."""
        currency_symbols = {
            'TWD': 'NT$',
            'USD': '$',
            'EUR': '€',
            'GBP': '£',
            'JPY': '¥',
            'VND': '₫',
        }
        
        symbol = currency_symbols.get(currency, currency)
        
        lines = ["📊 Tình hình chi tiêu:"]
        
        # Sort by balance (creditors first, then debtors)
        sorted_balances = sorted(balances, key=lambda x: x[1], reverse=True)
        
        for user, balance in sorted_balances:
            if balance > Decimal('0.01'):
                if currency == 'VND':
                    amount_str = f"{balance:,.0f} {symbol}"
                else:
                    amount_str = f"{symbol} {balance:,.2f}"
                lines.append(f"✅ {user.name}: +{amount_str} (được trả)")
            elif balance < -Decimal('0.01'):
                abs_balance = abs(balance)
                if currency == 'VND':
                    amount_str = f"{abs_balance:,.0f} {symbol}"
                else:
                    amount_str = f"{symbol} {abs_balance:,.2f}"
                lines.append(f"❌ {user.name}: -{amount_str} (phải trả)")
            else:
                lines.append(f"⚖️ {user.name}: Đã cân bằng")
        
        return "\n".join(lines)
