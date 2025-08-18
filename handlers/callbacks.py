"""
Callback query handlers for inline keyboards.
Split from main.py to improve code organization.
"""
import logging
from decimal import Decimal
from telegram import Update
from telegram.ext import ContextTypes

import db
from keyboards import Keyboards

logger = logging.getLogger(__name__)

class CallbackHandlers:
    """Handles all callback queries from inline keyboards"""
    
    def __init__(self, user_states, group_expense_states):
        self.user_states = user_states
        self.group_expense_states = group_expense_states

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Main callback query router"""
        query = update.callback_query
        data = query.data
        user_id = update.effective_user.id
        
        logger.info(f"Processing callback query: {data} from user {user_id}")
        
        await query.answer()
        
        # Route to appropriate handler
        if data == 'main_menu':
            await self._handle_main_menu(query, user_id)
        elif data == 'budget_menu':
            await self._handle_budget_menu(query, user_id)
        elif data == 'settings_menu':
            await self._handle_settings_menu(query, user_id)
        elif data == 'payment_settings':
            await self._handle_payment_settings(query, user_id)
        elif data.startswith('select_bank_'):
            await self._handle_bank_selection(query, user_id, data)
        elif data.startswith('group_currency_'):
            await self._handle_group_currency(query, user_id, data)
        elif data == 'personal_expense_menu':
            await self._handle_personal_expense_menu(query, user_id)
        # Add more routing as needed...
        else:
            await query.edit_message_text("❌ Lệnh không được hỗ trợ")

    async def _handle_main_menu(self, query, user_id):
        """Handle main menu callback"""
        logger.info("Processing main_menu callback")
        
        if query.message.chat.type == 'private':
            await query.edit_message_text(
                "🏠 **Menu chính**\n\nChọn tính năng:",
                parse_mode='Markdown',
                reply_markup=Keyboards.main_dm_menu()
            )
        else:
            await query.edit_message_text(
                "🏠 **Menu nhóm**\n\nChọn tính năng:",
                parse_mode='Markdown',
                reply_markup=Keyboards.group_main_menu()
            )

    async def _handle_budget_menu(self, query, user_id):
        """Handle budget menu callback"""
        logger.info("Processing budget_menu callback")
        
        # Get user wallets
        await db.create_or_update_user(user_id, query.from_user.full_name)
        db_user = await db.get_user_by_tg_id(user_id)
        wallets = await db.get_user_wallets(db_user.id)
        
        text = "💰 **Quản lý Budget**\n\n"
        if wallets:
            # Initialize currency service
            from services.currency import CurrencyService
            currency_service = CurrencyService(db)
            
            text += "Ví hiện tại:\n"
            for wallet in wallets:
                balance_decimal = Decimal(wallet.current_balance)
                balance_text = currency_service.format_amount(balance_decimal, wallet.currency)
                text += f"• {balance_text}\n"
        else:
            text += "Chưa có ví nào. Tạo ví mới để bắt đầu!"
        
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=Keyboards.budget_menu()
        )
        
        logger.info("Completed budget_menu callback")

    async def _handle_settings_menu(self, query, user_id):
        """Handle settings menu callback"""
        await query.edit_message_text(
            "⚙️ **Cài đặt**\n\nChọn mục cần cấu hình:",
            parse_mode='Markdown',
            reply_markup=Keyboards.settings_menu()
        )

    async def _handle_payment_settings(self, query, user_id):
        """Handle payment settings callback"""
        # Get user preferences
        db_user = await db.get_user_by_tg_id(user_id)
        preferences = await db.get_payment_preferences(db_user.id)
        
        accept_vnd = preferences[0] if preferences else False
        
        text = "💳 **Cài đặt thanh toán**\n\n"
        text += f"💰 Nhận VND: {'✅ Bật' if accept_vnd else '❌ Tắt'}\n\n"
        
        if accept_vnd:
            # Show bank accounts
            accounts = await db.get_user_bank_accounts(db_user.id)
            if accounts:
                text += "🏛️ Tài khoản ngân hàng:\n"
                for account in accounts:
                    default_text = " (mặc định)" if account[4] else ""  # is_default
                    text += f"• {account[2]} - {account[3]}{default_text}\n"  # bank_name, account_number
            else:
                text += "⚠️ Chưa có tài khoản ngân hàng nào"
        
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=Keyboards.payment_settings_menu(accept_vnd)
        )

    async def _handle_bank_selection(self, query, user_id, data):
        """Handle bank selection callback"""
        bank_code = data.replace('select_bank_', '')
        
        # Get bank info from VietQR service
        from services.vietqr import VIETNAM_BANKS
        if bank_code not in VIETNAM_BANKS:
            await query.edit_message_text("❌ Ngân hàng không được hỗ trợ")
            return
        
        bank_name = VIETNAM_BANKS[bank_code]
        
        # Set user state for account input
        self.user_states[user_id] = {
            'action': 'add_bank_account',
            'bank_code': bank_code,
            'bank_name': bank_name
        }
        
        await query.edit_message_text(
            f"🏛️ **{bank_name}**\n\n"
            "💳 Vui lòng nhập số tài khoản:",
            parse_mode='Markdown'
        )

    async def _handle_group_currency(self, query, user_id, data):
        """Handle group currency selection"""
        currency = data.replace('group_currency_', '')
        chat_id = query.message.chat.id
        
        # Store group expense state
        self.group_expense_states[chat_id] = {
            'currency': currency,
            'step': 'amount'
        }
        
        await query.edit_message_text(
            f"💰 **Chi tiêu nhóm ({currency})**\n\n"
            "💸 Nhập số tiền chi tiêu:",
            parse_mode='Markdown'
        )

    async def _handle_personal_expense_menu(self, query, user_id):
        """Handle personal expense menu"""
        logger.info("Processing personal_expense_menu callback")
        
        await query.edit_message_text(
            "💸 **Chi tiêu cá nhân**\n\n"
            "Chọn tính năng:",
            parse_mode='Markdown',
            reply_markup=Keyboards.personal_expense_menu()
        )
