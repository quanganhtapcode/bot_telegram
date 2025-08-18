"""
Database models and schemas for the Telegram bot.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from decimal import Decimal


@dataclass
class User:
    id: Optional[int]
    tg_user_id: int
    name: str
    created_at: Optional[datetime]
    last_seen: Optional[datetime]


@dataclass
class UserSettings:
    user_id: int
    preferred_currency: str
    allow_negative: bool
    auto_rule: bool


@dataclass
class UserWallet:
    id: Optional[int]
    user_id: int
    currency: str
    initial_amount: Decimal
    current_balance: Decimal
    note: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


@dataclass
class WalletAdjustment:
    id: Optional[int]
    wallet_id: int
    delta_amount: Decimal
    reason: str
    created_at: Optional[datetime]


@dataclass
class PersonalExpense:
    id: Optional[int]
    user_id: int
    amount: Decimal
    currency: str
    note: Optional[str]
    wallet_id: int
    fx_rate: Optional[Decimal]
    converted_amount: Optional[Decimal]
    created_at: Optional[datetime]
    undo_until: Optional[datetime]


@dataclass
class Trip:
    id: Optional[int]
    code: str
    name: str
    base_currency: str
    owner_user_id: int
    created_at: Optional[datetime]


@dataclass
class TripMember:
    trip_id: int
    user_id: int
    role: str  # 'admin' or 'member'


@dataclass
class Expense:
    id: Optional[int]
    trip_id: int
    payer_user_id: int
    amount: Decimal
    currency: str
    rate_to_base: Decimal
    amount_base: Decimal
    note: Optional[str]
    created_at: Optional[datetime]


@dataclass
class ExpenseShare:
    id: Optional[int]
    expense_id: int
    user_id: int
    share_ratio: Decimal


@dataclass
class GroupDeduction:
    id: Optional[int]
    user_id: int
    trip_id: int
    expense_id: int
    share_amount: Decimal
    share_currency: str
    wallet_id: int
    fx_rate_used: Decimal
    deducted_amount_in_wallet_currency: Decimal
    created_at: Optional[datetime]


@dataclass
class ExchangeRate:
    date: str
    base: str
    quote: str
    rate: Decimal


@dataclass
class GroupExpense:
    """Group expense for splitting among members"""
    id: Optional[int]
    group_id: int  # Telegram group chat ID
    payer_user_id: int  # User who paid
    amount: Decimal
    currency: str
    description: Optional[str]
    created_at: Optional[datetime]
    settled: bool = False


@dataclass  
class GroupExpenseParticipant:
    """Participants in a group expense"""
    id: Optional[int]
    expense_id: int
    user_id: int
    share_amount: Decimal  # Amount this user owes
    paid: bool = False  # Whether they paid back
    reminded: bool = False  # Whether they were reminded today


@dataclass
class GroupDebt:
    """Debt between two users"""
    id: Optional[int]
    group_id: int
    debtor_user_id: int  # Person who owes money
    creditor_user_id: int  # Person who is owed money
    amount: Decimal
    currency: str
    last_updated: Optional[datetime]


@dataclass
class DebtSettlement:
    """Record of debt settlements"""
    id: Optional[int]
    group_id: int
    payer_user_id: int
    receiver_user_id: int
    amount: Decimal
    currency: str
    created_at: Optional[datetime]


@dataclass
class ExchangeRate:
    """Exchange rate between currencies"""
    id: Optional[int]
    from_currency: str
    to_currency: str
    rate: Decimal
    set_by: int
    created_at: Optional[datetime]


@dataclass
class BankAccount:
    """User bank account for VietQR"""
    id: Optional[int]
    user_id: int
    bank_code: str
    bank_name: str
    account_number: str
    account_name: str
    is_default: bool
    created_at: Optional[datetime]


@dataclass
class PaymentPreference:
    """User payment preferences"""
    user_id: int
    accept_vnd_payments: bool
    auto_convert_debts: bool
    preferred_bank_id: Optional[int]


@dataclass
class VietQRData:
    """VietQR payment data"""
    bank_code: str
    account_number: str
    account_name: str
    amount: Decimal
    description: str
    template: str = "compact2"

    def generate_url(self) -> str:
        """Generate VietQR URL"""
        amount_str = str(int(self.amount))  # VietQR expects integer VND
        description_encoded = self.description.replace(" ", "%20")
        account_name_encoded = self.account_name.replace(" ", "%20")
        
        return (f"https://img.vietqr.io/image/{self.bank_code}-{self.account_number}-"
                f"{self.template}.png?amount={amount_str}&addInfo={description_encoded}"
                f"&accountName={account_name_encoded}")
