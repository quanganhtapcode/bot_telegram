"""
Message handlers for text input processing.
Split from main.py to improve code organization.
"""
import logging
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

import db
from keyboards import Keyboards

logger = logging.getLogger(__name__)

class MessageHandlers:
    """Handles all text message processing"""
    
    def __init__(self, user_states, group_expense_states):
        self.user_states = user_states
        self.group_expense_states = group_expense_states

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Main message handler router"""
        user_id = update.effective_user.id
        text = update.message.text.strip()
        
        logger.info(f"Received message from user {user_id}: '{text}'")
        logger.info(f"Current user_states: {self.user_states}")
        logger.info(f"Current group_expense_states: {self.group_expense_states}")
        
        # Check if user has active state
        if user_id in self.user_states:
            await self._handle_user_state(update, user_id, text)
        # Check if group has active expense state
        elif update.effective_chat.type != 'private':
            chat_id = update.effective_chat.id
            if chat_id in self.group_expense_states:
                await self._handle_group_expense_state(update, chat_id, text)
            else:
                await self._handle_expense_format(update, text)
        else:
            # Private chat - check for expense format
            await self._handle_expense_format(update, text)

    async def _handle_user_state(self, update, user_id, text):
        """Handle user in specific state (waiting for input)"""
        state = self.user_states[user_id]
        action = state.get('action')
        
        if action == 'add_bank_account' and state.get('step') == 'account_name':
            await self._handle_bank_account_name(update, user_id, text, state)
        elif action == 'add_bank_account':
            await self._handle_bank_account_number(update, user_id, text, state)
        elif action == 'set_exchange_rate':
            await self._handle_exchange_rate_input(update, user_id, text, state)
        # Add more state handlers as needed...

    async def _handle_bank_account_name(self, update, user_id, text, state):
        """Handle bank account name input"""
        account_name = text.strip()
        
        if len(account_name) < 2:
            await update.message.reply_text("❌ Tên tài khoản quá ngắn! Vui lòng nhập lại:")
            return
        
        try:
            # Save bank account
            db_user = await db.get_user_by_tg_id(user_id)
            account_id = await db.add_bank_account(
                db_user.id,
                state['bank_code'],
                state['bank_name'],
                state['account_number'],
                account_name
            )
            
            await update.message.reply_text(
                f"✅ **Thêm tài khoản thành công!**\n\n"
                f"🏛️ Ngân hàng: {state['bank_name']}\n"
                f"💳 STK: {state['account_number']}\n"
                f"👤 Tên: {account_name}\n\n"
                "Bạn có thể nhận chuyển khoản VND từ bây giờ!",
                parse_mode='Markdown',
                reply_markup=Keyboards.main_dm_menu()
            )
            
            # Auto-enable VND payments if this is first account
            preferences = await db.get_payment_preferences(db_user.id)
            if not preferences or not preferences[0]:  # accept_vnd_payments
                await db.update_payment_preferences(db_user.id, accept_vnd=True)
            
            # Clear state
            del self.user_states[user_id]
            
        except Exception as e:
            logger.error(f"Error adding bank account: {e}")
            await update.message.reply_text("❌ Có lỗi khi thêm tài khoản. Vui lòng thử lại!")

    async def _handle_bank_account_number(self, update, user_id, text, state):
        """Handle bank account number input"""
        account_number = text.replace(' ', '').replace('-', '')  # Remove spaces and dashes
        
        if len(account_number) < 6 or len(account_number) > 19:
            await update.message.reply_text("❌ Số tài khoản không hợp lệ! Vui lòng nhập lại (6-19 chữ số):")
            return
        
        state['account_number'] = account_number
        state['step'] = 'account_name'
        
        await update.message.reply_text(
            f"🏛️ **Tài khoản {state['bank_name']}**\n"
            f"💳 STK: {account_number}\n\n"
            "👤 Vui lòng nhập tên chủ tài khoản (như trên thẻ):",
            parse_mode='Markdown'
        )

    async def _handle_exchange_rate_input(self, update, user_id, text, state):
        """Handle exchange rate input (admin only)"""
        ADMIN_USER_ID = 5245151002  # Will be moved to config
        
        if user_id != ADMIN_USER_ID:
            await update.message.reply_text("❌ Không có quyền truy cập!")
            return
        
        try:
            rate = Decimal(text.replace(',', '.'))
            if rate <= 0:
                await update.message.reply_text("❌ Tỷ giá phải lớn hơn 0! Vui lòng nhập lại:")
                return
            
            from_currency = state['from_currency']
            to_currency = state['to_currency']
            
            # Save exchange rate
            await db.set_exchange_rate(from_currency, to_currency, rate, user_id)
            
            await update.message.reply_text(
                f"✅ **Cập nhật tỷ giá thành công!**\n\n"
                f"💱 {from_currency}/{to_currency}: {rate}\n\n"
                f"Tỷ giá mới đã được áp dụng cho toàn hệ thống.",
                parse_mode='Markdown',
                reply_markup=Keyboards.main_dm_menu()
            )
            
            # Clear state
            del self.user_states[user_id]
            
        except (InvalidOperation, ValueError):
            await update.message.reply_text("❌ Tỷ giá không hợp lệ! Vui lòng nhập số (VD: 875 hoặc 875.5):")
        except Exception as e:
            logger.error(f"Error setting exchange rate: {e}")
            await update.message.reply_text("❌ Có lỗi khi cập nhật tỷ giá. Vui lòng thử lại!")

    async def _handle_expense_format(self, update, text):
        """Handle expense format like '120 ăn sáng'"""
        # Pattern: number + optional description
        expense_pattern = r'^(\d+(?:\.\d+)?)\s*(.*)$'
        match = re.match(expense_pattern, text)
        
        if not match:
            return  # Not an expense format
        
        try:
            amount = Decimal(match.group(1))
            note = match.group(2).strip() or None
            
            if amount <= 0:
                await update.message.reply_text("❌ Số tiền phải lớn hơn 0!")
                return
            
            user_id = update.effective_user.id
            await self._process_expense(update, user_id, amount, note)
            
        except (InvalidOperation, ValueError):
            pass  # Invalid number format, ignore

    async def _process_expense(self, update, user_id, amount, note):
        """Process expense transaction"""
        # Get user settings
        await db.create_or_update_user(user_id, update.effective_user.full_name)
        db_user = await db.get_user_by_tg_id(user_id)
        user_settings = await db.get_user_settings(user_id)
        
        currency = user_settings.preferred_currency
        
        # Check for existing wallet
        wallet = await db.get_wallet_by_currency(db_user.id, currency)
        
        if wallet:
            # Process expense
            expense = await db.add_personal_expense(
                db_user.id,
                amount,
                currency,
                wallet.id,
                note
            )
            expense_id = expense.id if expense else None
            
            if expense_id:
                # Update wallet balance
                new_balance = Decimal(wallet.current_balance) - amount
                await db.update_wallet_balance(wallet.id, new_balance)
                
                # Initialize currency service
                from services.currency import CurrencyService
                currency_service = CurrencyService(db)
                
                # Format response
                formatted_amount = currency_service.format_amount(amount, currency)
                formatted_balance = currency_service.format_amount(new_balance, currency)
                
                message = f"✅ Đã ghi nhận chi tiêu {formatted_amount}"
                if note:
                    message += f"\n📝 Ghi chú: {note}"
                message += f"\n💰 Số dư còn lại: {formatted_balance}"
                message += f"\n⏰ Có thể hoàn tác trong 10 phút"
                
                await update.message.reply_text(message)
            else:
                await update.message.reply_text("❌ Lỗi khi cập nhật ví!")
        else:
            # No wallet - offer to create
            from services.currency import CurrencyService
            currency_service = CurrencyService(db)
            formatted_amount = currency_service.format_amount(amount, currency)
            await update.message.reply_text(
                f"❌ Không có ví {currency}!\n\n"
                f"Tạo ví {currency} mới với chi tiêu {formatted_amount}?",
                reply_markup=Keyboards.confirm_action('create_expense_wallet')
            )
