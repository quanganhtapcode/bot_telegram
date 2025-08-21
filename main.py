"""
Main Telegram bot for trip expense splitting.
"""
import os
import asyncio
import logging
import string
import random
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError, TimedOut, NetworkError
from telegram.request import HTTPXRequest
import pytz
import asyncio
from datetime import datetime, time

from db import Database
from models import *
from keyboards import Keyboards
from services import CurrencyService, SettlementService, DeductionService
from services.vietqr import VietQRService

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO'))
)
logger = logging.getLogger(__name__)

# Global configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
DATABASE_PATH = os.getenv('DATABASE_PATH', './bot.db')
DEFAULT_BASE_CURRENCY = os.getenv('DEFAULT_BASE_CURRENCY', 'TWD')
TIMEZONE = pytz.timezone(os.getenv('TIMEZONE', 'Asia/Ho_Chi_Minh'))
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', '5245151002'))

# Webhook configuration (optional)
USE_WEBHOOK = os.getenv('USE_WEBHOOK', 'false').lower() == 'true'
WEBHOOK_DOMAIN = os.getenv('WEBHOOK_DOMAIN')  # e.g. bot.quanganh.org
WEBHOOK_PATH = os.getenv('WEBHOOK_PATH', '/telegram/webhook')
WEBHOOK_PORT = int(os.getenv('WEBHOOK_PORT', '8080'))
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')

# Global instances
db = Database(DATABASE_PATH)
currency_service = CurrencyService(db)
settlement_service = SettlementService()
deduction_service = DeductionService(db, currency_service)
vietqr_service = VietQRService(db)

# User state tracking for multi-step operations
user_states: Dict[int, Dict] = {}
group_expense_states: Dict[int, Dict] = {}  # For group expense creation states


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a message to the user."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    # Try to send a friendly error message to user
    if isinstance(context.error, (TimedOut, NetworkError)):
        error_message = "⚠️ Kết nối chậm, vui lòng thử lại sau ít phút."
    else:
        error_message = "❌ Đã xảy ra lỗi. Vui lòng thử lại."
    
    try:
        if update and hasattr(update, 'effective_chat') and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=error_message
            )
    except Exception:
        # Don't let error handler fail
        pass


async def send_daily_debt_summary(application: Application):
    """Send daily debt summary at 11 PM - Private messages only."""
    try:
        # Get all groups with pending debts
        groups_with_debts = await db.get_groups_with_pending_debts()
        
        for group_id in groups_with_debts:
            try:
                # Get all debts in this group
                all_debts = await db.get_group_debts(group_id)
                
                if not all_debts:
                    continue
                
                # Group by currency and optimize each currency separately
                currencies = set(debt.currency for debt, _, _ in all_debts)
                total_transactions = 0
                
                for currency in currencies:
                    # Get optimized debts for this currency
                    optimized_transactions = await db.optimize_group_debts(group_id, currency)
                    
                    if not optimized_transactions:
                        continue
                    
                    total_transactions += len(optimized_transactions)
                    
                    # Send PRIVATE debt notifications to each person
                    for debtor, creditor, amount in optimized_transactions:
                        await send_private_debt_notification(
                            application, debtor.tg_user_id, creditor.tg_user_id, 
                            amount, currency, group_id
                        )
                
                # Send simple group summary (no sensitive details)
                if total_transactions > 0:
                    group_summary = (
                        "🌅 **Nhắc nhở 10h sáng**\n\n"
                        f"💰 Có {total_transactions} giao dịch nợ chưa thanh toán\n"
                        "📱 Kiểm tra tin nhắn riêng để xem chi tiết\n"
                        "💡 Dùng `/settle` để quản lý công nợ"
                    )
                    
                    await application.bot.send_message(
                        chat_id=group_id,
                        text=group_summary,
                        parse_mode='Markdown'
                    )
                
            except Exception as e:
                logger.error(f"Error sending daily summary to group {group_id}: {e}")
                
    except Exception as e:
        logger.error(f"Error in daily debt summary: {e}")


async def send_private_debt_notification(application: Application, debtor_id: int, 
                                      creditor_id: int, amount: Decimal, currency: str, group_id: int):
    """Send private debt notification with VietQR option."""
    try:
        debtor_name = await get_user_name(application, debtor_id)
        creditor_name = await get_user_name(application, creditor_id)
        
        # Get creditor's payment info
        creditor_user = await db.get_user_by_tg_id(creditor_id)
        if not creditor_user:
            return
            
        payment_info = await vietqr_service.get_user_payment_info(creditor_user.id)
        amount_text = currency_service.format_amount(amount, currency)
        
        # Message to debtor
        debtor_text = f"💰 **Nhắc nhở thanh toán nợ**\n\n"
        debtor_text += f"Bạn nợ **{creditor_name}**: {amount_text}\n\n"
        # Option trả tiền mặt
        debtor_text += "Chọn phương thức thanh toán:\n"
        keyboard = [
            [InlineKeyboardButton("💵 Trả tiền mặt", callback_data=f"pay_cash_{group_id}_{creditor_id}_{amount}_{currency}")],
        ]
        # Option chuyển khoản nếu có payment_info
        if payment_info:
            vnd_amount = await vietqr_service.convert_currency(amount, currency, "VND")
            if vnd_amount:
                vnd_text = currency_service.format_amount(vnd_amount, "VND")
                debtor_text += f"💳 Chuyển khoản VND: {vnd_text}\n"
                _, bank_account = payment_info
                debtor_text += f"🏛️ **Thông tin chuyển khoản:**\n"
                debtor_text += f"• Ngân hàng: {bank_account.bank_name}\n"
                debtor_text += f"• STK: `{bank_account.account_number}`\n"
                debtor_text += f"• Tên: {bank_account.account_name}\n"
                debtor_text += f"• Nội dung: `No {creditor_name}`\n"
                qr_url = await vietqr_service.generate_payment_qr(
                    creditor_user.id, vnd_amount, f"No {creditor_name}", "VND"
                )
                if qr_url:
                    keyboard.append([InlineKeyboardButton("📱 Chuyển khoản VND (QR)", callback_data=f"pay_qr_{group_id}_{creditor_id}_{vnd_amount}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send private message to debtor
        await application.bot.send_message(
            chat_id=debtor_id,
            text=debtor_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        # Message to creditor
        creditor_text = f"💰 **Thông báo có người nợ**\n\n"
        creditor_text += f"**{debtor_name}** nợ bạn: {amount_text}\n"
        if payment_info:
            vnd_amount = await vietqr_service.convert_currency(amount, currency, "VND")
            if vnd_amount:
                vnd_text = currency_service.format_amount(vnd_amount, "VND")
                creditor_text += f"💳 Tương đương: {vnd_text}\n"
        creditor_text += f"\n📱 Đã gửi thông báo chuyển khoản cho {debtor_name}"
        
        # Send private message to creditor
        await application.bot.send_message(
            chat_id=creditor_id,
            text=creditor_text,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error sending private debt notification: {e}")


async def get_chat_members_for_expense(context, group_id):
    """Get chat members for expense splitting. Try to get all members for small groups."""
    try:
        # Try to get member count to determine strategy
        chat_member_count = await context.bot.get_chat_member_count(group_id)
        
        # For now, we can only reliably get administrators due to Telegram API limitations
        # In the future, if bot gets promoted to admin with "see members" permission,
        # we could get all members for small groups
        chat_members = await context.bot.get_chat_administrators(group_id)
        
        return chat_members
    except Exception as e:
        logger.error(f"Error getting chat members: {e}")
        # Fallback to administrators only
        chat_members = await context.bot.get_chat_administrators(group_id)
        return chat_members


async def get_user_name(application: Application, user_id: int) -> str:
    """Get user's display name."""
    try:
        user = await application.bot.get_chat(user_id)
        return user.first_name or "Unknown"
    except:
        return "Unknown"


async def schedule_daily_tasks(application: Application):
    """Schedule daily tasks like debt summary."""
    while True:
        try:
            now = datetime.now(TIMEZONE)
            target_time = now.replace(hour=23, minute=0, second=0, microsecond=0)
            
            # If it's already past 11 PM today, schedule for tomorrow
            if now > target_time:
                target_time = target_time.replace(day=target_time.day + 1)
            
            # Calculate seconds until target time
            wait_seconds = (target_time - now).total_seconds()
            
            logger.info(f"Scheduled daily summary in {wait_seconds/3600:.1f} hours")
            await asyncio.sleep(wait_seconds)
            
            # Send daily summary
            await send_daily_debt_summary(application)
            
            # Wait 24 hours for next run
            await asyncio.sleep(24 * 60 * 60)
            
        except Exception as e:
            logger.error(f"Error in daily task scheduler: {e}")
            await asyncio.sleep(60 * 60)  # Wait 1 hour before retry


class BotHandlers:
    @staticmethod
    async def format_wallets_and_history(db_user):
        wallets = await db.get_user_wallets(db_user.id)
        currency_flags = {
            "TWD": "🇹🇼",
            "VND": "🇻🇳", 
            "USD": "🇺🇸",
            "EUR": "🇪🇺",
            "JPY": "🇯🇵",
            "KRW": "🇰🇷",
            "CNY": "🇨🇳",
            "THB": "🇹🇭",
            "SGD": "🇸🇬",
            "MYR": "🇲🇾",
            "PHP": "🇵🇭",
            "IDR": "🇮🇩",
            "GBP": "🇬🇧",
            "AUD": "🇦🇺",
            "CAD": "🇨🇦"
        }
        text = "💰 **Chi tiết tất cả ví**\n\n"
        for wallet in wallets:
            balance_decimal = Decimal(wallet.current_balance)
            balance_text = currency_service.format_amount(balance_decimal, wallet.currency)
            flag = currency_flags.get(wallet.currency, "💳")
            text += f"{flag} **{wallet.currency}**\n"
            text += f"💵 Số dư: {balance_text}\n"
            if wallet.note:
                text += f"📝 Ghi chú: {wallet.note}\n"
            # Giao dịch gần đây
            try:
                transactions = await db.get_wallet_transactions(wallet.id, limit=3)
                if transactions:
                    text += f"📊 **Giao dịch gần đây:**\n"
                    for tx in transactions:
                        # Luôn dùng dict key nếu có
                        amount_decimal = Decimal(tx.get("amount", 0))
                        created_at = tx.get("created_at", "")
                        desc = tx.get("description", "Giao dịch")
                        amount_text = currency_service.format_amount(amount_decimal, wallet.currency)
                        icon = "💰" if amount_decimal > 0 else "💸"
                        sign = "+" if amount_decimal > 0 else ""
                        # Format date
                        try:
                            from datetime import datetime
                            if isinstance(created_at, str):
                                tx_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                                date_str = tx_date.strftime('%d/%m')
                            else:
                                date_str = created_at.strftime('%d/%m')
                        except:
                            date_str = "N/A"
                        if len(desc) > 20:
                            desc = desc[:20] + "..."
                        text += f"  {icon} {sign}{amount_text} - {desc} ({date_str})\n"
                else:
                    text += f"📊 **Chưa có giao dịch nào**\n"
            except Exception as e:
                logger.warning(f"Could not get transactions for wallet {wallet.id}: {e}")
                text += f"📊 **Chưa có giao dịch nào**\n"
            text += "\n"
        return text
    """Main bot handlers class."""

    @staticmethod
    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        user = update.effective_user
        chat = update.effective_chat
        
        try:
            # Create or update user
            db_user = await db.create_or_update_user(user.id, user.full_name)
            logger.info(f"User created/updated: {db_user}")
        except Exception as e:
            logger.error(f"Error creating/updating user: {e}")
            await update.message.reply_text("❌ Lỗi cơ sở dữ liệu. Vui lòng thử lại sau.")
            return
        
        if chat.type == 'private':
            try:
                await update.message.reply_text(
                    f"👋 **Chào mừng {user.first_name}!**\n\n"
                    "🤖 **Bot Quản Lý Chi Tiêu Thông Minh**\n\n"
                    "✨ **Tính năng chính:**\n"
                    "💰 Quản lý ví đa tiền tệ\n"
                    "📊 Theo dõi chi tiêu cá nhân\n"
                    "👥 Chia sẻ chi phí nhóm tự động\n"
                    "🏦 Tích hợp VietQR & chuyển khoản\n\n"
                    "🚀 **Bắt đầu ngay:**",
                    parse_mode='Markdown',
                    reply_markup=Keyboards.main_dm_menu()
                )
                logger.info("Successfully sent start message with keyboard")
            except (TimedOut, NetworkError) as e:
                logger.error(f"Timeout/Network error: {e}")
                # Try simpler message without keyboard
                try:
                    await update.message.reply_text(
                        f"Xin chào {user.first_name}! Bot đã sẵn sàng. "
                        "Gửi /start lại để xem menu."
                    )
                    logger.info("Successfully sent simple start message")
                except Exception as e2:
                    logger.error(f"Failed to send even simple start message: {e2}")
            except Exception as e:
                logger.error(f"Unexpected error sending start message: {e}")
                try:
                    await update.message.reply_text("❌ Lỗi gửi tin nhắn. Vui lòng thử lại.")
                except Exception:
                    pass  # If we can't even send error message, give up
        else:
            try:
                await update.message.reply_text(
                    f"Xin chào! Tôi đã sẵn sàng giúp quản lý chi tiêu chuyến đi.\n\n"
                    "Sử dụng /newtrip <tên chuyến đi> để tạo chuyến đi mới\n"
                    "Hoặc /join <mã> để tham gia chuyến đi",
                    reply_markup=Keyboards.group_main_menu()
                )
                logger.info("Successfully sent group start message")
            except Exception as e:
                logger.error(f"Error sending group start message: {e}")
                try:
                    await update.message.reply_text("❌ Lỗi gửi tin nhắn. Vui lòng thử lại.")
                except Exception:
                    pass

    @staticmethod
    async def newtrip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /newtrip command."""
        if update.effective_chat.type == 'private':
            await update.message.reply_text("Lệnh này chỉ dùng được trong nhóm!")
            return

        if not context.args:
            await update.message.reply_text("Sử dụng: /newtrip <tên chuyến đi>")
            return

        trip_name = " ".join(context.args)
        user = update.effective_user
        
        # Create or update user
        db_user = await db.create_or_update_user(user.id, user.full_name)
        
        # Generate unique trip code
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            existing_trip = await db.get_trip_by_code(code)
            if not existing_trip:
                break

        # Create trip
        trip = await db.create_trip(code, trip_name, DEFAULT_BASE_CURRENCY, db_user.id)
        
        await update.message.reply_text(
            f"🎉 Đã tạo chuyến đi: {trip_name}\n"
            f"📝 Mã tham gia: `{code}`\n"
            f"💰 Tiền tệ gốc: {DEFAULT_BASE_CURRENCY}\n"
            f"👑 Quản trị viên: {user.full_name}\n\n"
            f"Chia sẻ mã `{code}` để mọi người tham gia!",
            parse_mode='Markdown',
            reply_markup=Keyboards.group_main_menu()
        )

    @staticmethod
    async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /join command."""
        if not context.args:
            await update.message.reply_text("Sử dụng: /join <mã chuyến đi>")
            return

        code = context.args[0].upper()
        user = update.effective_user
        
        # Create or update user
        db_user = await db.create_or_update_user(user.id, user.full_name)
        
        # Find trip
        trip = await db.get_trip_by_code(code)
        if not trip:
            await update.message.reply_text("❌ Không tìm thấy chuyến đi với mã này!")
            return

        # Join trip
        success = await db.join_trip(trip.id, db_user.id)
        if success:
            await update.message.reply_text(
                f"✅ Đã tham gia chuyến đi: {trip.name}\n"
                f"💰 Tiền tệ gốc: {trip.base_currency}"
            )
        else:
            await update.message.reply_text("Bạn đã tham gia chuyến đi này rồi!")

    @staticmethod
    async def add_expense_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add command for group expenses."""
        if update.effective_chat.type == 'private':
            await BotHandlers.handle_personal_expense_command(update, context)
            return

        # For group chats, start group expense flow
        user_id = update.effective_user.id
        group_id = update.effective_chat.id
        
        # Ensure user exists in database
        await db.create_or_update_user(user_id, update.effective_user.full_name)
        
        # Initialize group expense state
        group_expense_states[user_id] = {
            'step': 'currency',
            'group_id': group_id,
            'payer_id': user_id
        }
        
        await update.message.reply_text(
            "💰 Tạo chi tiêu nhóm\n\n"
            "Chọn loại tiền tệ:",
            reply_markup=Keyboards.group_expense_currency_selection()
        )

    @staticmethod
    async def handle_personal_expense_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle personal expense command in DM."""
        if len(context.args) < 2:
            await update.message.reply_text("Sử dụng: /add <số tiền> <tiền tệ> [ghi chú]")
            return

        try:
            amount = Decimal(context.args[0])
            currency = context.args[1].upper()
            note = " ".join(context.args[2:]) if len(context.args) > 2 else None
        except (InvalidOperation, ValueError):
            await update.message.reply_text("❌ Số tiền không hợp lệ!")
            return

        user = update.effective_user
        db_user = await db.get_user_by_tg_id(user.id)
        if not db_user:
            await update.message.reply_text("❌ Vui lòng sử dụng /start trước!")
            return

        await BotHandlers.process_personal_expense(update.message.reply_text, db_user.id, amount, currency, note)

    @staticmethod
    async def process_personal_expense(reply_func, user_id: int, amount: Decimal, currency: str, note: Optional[str]):
        """Process personal expense addition."""
        # Find matching wallet
        wallet = await db.get_wallet_by_currency(user_id, currency)
        
        if wallet:
            # Deduct from wallet (negative balance is now always allowed)
            success = await db.update_wallet_balance(wallet.id, -amount, "Chi tiêu cá nhân")
            if success:
                # Add expense record
                expense = await db.add_personal_expense(user_id, amount, currency, wallet.id, note)
                formatted_amount = currency_service.format_amount(amount, currency)
                remaining_balance = Decimal(wallet.current_balance) - amount
                formatted_balance = currency_service.format_amount(remaining_balance, currency)
                
                message = f"✅ Đã ghi nhận chi tiêu {formatted_amount}"
                if note:
                    message += f"\n📝 Ghi chú: {note}"
                message += f"\n💰 Số dư còn lại: {formatted_balance}"
                message += f"\n⏰ Có thể hoàn tác trong 10 phút"
                
                await reply_func(message)
            else:
                await reply_func("❌ Lỗi khi cập nhật ví!")
        else:
            # No wallet for this currency - offer options
            user_settings = await db.get_user_settings(user_id)
            
            try:
                # Try to convert to preferred currency
                if currency != user_settings.preferred_currency:
                    fx_rate, converted_amount = await currency_service.convert(amount, currency, user_settings.preferred_currency)
                    
                    preferred_wallet = await db.get_wallet_by_currency(user_id, user_settings.preferred_currency)
                    if preferred_wallet:
                        formatted_original = currency_service.format_amount(amount, currency)
                        formatted_converted = currency_service.format_amount(converted_amount, user_settings.preferred_currency)
                        
                        # Store conversion info for callback
                        user_states[user_id] = {
                            'action': 'convert_expense',
                            'amount': amount,
                            'currency': currency,
                            'note': note,
                            'fx_rate': fx_rate,
                            'converted_amount': converted_amount,
                            'target_wallet': preferred_wallet.id
                        }
                        
                        await reply_func(
                            f"❌ Không có ví {currency}!\n\n"
                            f"Chuyển đổi {formatted_original} → {formatted_converted}?\n"
                            f"Tỷ giá: 1 {currency} = {fx_rate} {user_settings.preferred_currency}",
                            reply_markup=Keyboards.confirm_action('convert_expense')
                        )
                        return
            except Exception as e:
                logger.error(f"Error converting currency: {e}")

            # Offer to create new wallet
            user_states[user_id] = {
                'action': 'create_expense_wallet',
                'amount': amount,
                'currency': currency,
                'note': note
            }
            
            formatted_amount = currency_service.format_amount(amount, currency)
            await reply_func(
                f"❌ Không có ví {currency}!\n\n"
                f"Tạo ví {currency} mới với chi tiêu {formatted_amount}?",
                reply_markup=Keyboards.confirm_action('create_expense_wallet')
            )

    @staticmethod
    async def overview_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /overview command."""
        if update.effective_chat.type == 'private':
            await update.message.reply_text("Lệnh này chỉ dùng được trong nhóm!")
            return

        # For now, use button interface
        await update.message.reply_text(
            "📊 Sử dụng nút 'Tổng quan' để xem chi tiết:",
            reply_markup=Keyboards.group_main_menu()
        )

    @staticmethod
    async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /budget command."""
        if update.effective_chat.type != 'private':
            await update.message.reply_text("Lệnh này chỉ dùng được trong DM!")
            return
            
        user_id = update.effective_user.id
        
        # Get database user first
        await db.create_or_update_user(user_id, update.effective_user.full_name)
        db_user = await db.get_user_by_tg_id(user_id)
        
        wallets = await db.get_user_wallets(db_user.id)
        text = "💰 Quản lý Budget\n\n"
        if wallets:
            text += "Ví hiện tại:\n"
            for wallet in wallets:
                balance_decimal = Decimal(wallet.current_balance)
                balance_text = currency_service.format_amount(balance_decimal, wallet.currency)
                text += f"• {balance_text}\n"
        
        await update.message.reply_text(text, reply_markup=Keyboards.budget_menu())

    @staticmethod
    async def expense_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /expense command."""
        if update.effective_chat.type != 'private':
            await update.message.reply_text("Lệnh này chỉ dùng được trong DM!")
            return

        user_id = update.effective_user.id
        db_user = await db.get_user_by_tg_id(user_id)
        wallets = await db.get_user_wallets(db_user.id)
        
        if not wallets:
            await update.message.reply_text(
                "❌ Bạn cần tạo ví trước khi thêm chi tiêu.\n\n"
                "Vui lòng tạo ví đầu tiên:",
                reply_markup=Keyboards.budget_menu()
            )
        else:
            await update.message.reply_text(
                "🧾 Thêm chi tiêu cá nhân\n\n"
                "Chọn ví để ghi nhận chi tiêu:",
                reply_markup=Keyboards.wallet_selection_menu(wallets)
            )

    @staticmethod
    async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /history command."""
        if update.effective_chat.type != 'private':
            await update.message.reply_text("Lệnh này chỉ dùng được trong DM!")
            return

        user_id = update.effective_user.id
        # Get expenses from the last 7 days
        expenses = await db.get_personal_expenses_today(user_id, days=7)
        
        if not expenses:
            await update.message.reply_text("📚 Không có chi tiêu nào trong 7 ngày qua.")
            return
        
        text = "📚 Lịch sử chi tiêu (7 ngày gần nhất)\n\n"
        current_date = None
        daily_total = Decimal('0')
        
        for expense in expenses:
            # Convert datetime to correct timezone for display
            if isinstance(expense.created_at, str):
                from datetime import datetime
                created_at = datetime.fromisoformat(expense.created_at.replace('Z', '+00:00'))
            else:
                created_at = expense.created_at
            
            # Convert to local timezone
            if created_at.tzinfo is None:
                created_at = TIMEZONE.localize(created_at)
            else:
                created_at = created_at.astimezone(TIMEZONE)
            
            expense_date = created_at.strftime('%d/%m/%Y')
            if current_date != expense_date:
                if current_date is not None:
                    text += f"📊 Tổng ngày {current_date}: {currency_service.format_amount(daily_total, 'TWD')}\n\n"
                current_date = expense_date
                daily_total = Decimal('0')
                text += f"📅 {expense_date}\n"
            
            amount_decimal = Decimal(expense.amount)
            daily_total += amount_decimal
            amount_text = currency_service.format_amount(amount_decimal, expense.currency)
            time_str = created_at.strftime('%H:%M')
            
            description = f" - {expense.description}" if expense.description else ""
            text += f"• {time_str} | {amount_text}{description}\n"
        
        # Add last day total
        if current_date:
            text += f"📊 Tổng ngày {current_date}: {currency_service.format_amount(daily_total, 'TWD')}\n"
        
        await update.message.reply_text(text, reply_markup=Keyboards.personal_expense_menu())

    @staticmethod
    async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /settings command."""
        if update.effective_chat.type != 'private':
            await update.message.reply_text("Lệnh này chỉ dùng được trong DM!")
            return

        user_id = update.effective_user.id
        db_user = await db.get_user_by_tg_id(user_id)
        if not db_user:
            await update.message.reply_text("❌ Bạn chưa đăng ký. Sử dụng /start để bắt đầu.")
            return
            
        user_settings = await db.get_user_settings(user_id)
        
        # Build comprehensive settings display
        text = "⚙️ **Cài đặt**\n\n"
        
        # Basic settings (removed allow_negative and auto_rule as they're now defaults)
        
        # Bank accounts section
        try:
            bank_accounts = await db.get_user_bank_accounts(db_user.id)
            if bank_accounts:
                text += "🏦 **Tài khoản ngân hàng:**\n"
                for account in bank_accounts:
                    # account is tuple: (id, bank_code, bank_name, account_number, account_name, is_default)
                    bank_name = account[2]
                    account_number = account[3]
                    account_name = account[4] if account[4] else ""
                    # Note: QR code info is not in this query, so we'll show basic info
                    text += f"• {bank_name}: {account_number}\n"
                    if account_name:
                        text += f"  Tên: {account_name}\n"
                text += "\n"
            else:
                text += "🏦 **Tài khoản ngân hàng:** Chưa có\n\n"
        except Exception as e:
            logger.error(f"Error getting bank accounts: {e}")
            text += "🏦 **Tài khoản ngân hàng:** Lỗi tải dữ liệu\n\n"
        
                # Đã xóa hoàn toàn phần hiển thị cài đặt thanh toán
        
        await update.message.reply_text(text, reply_markup=Keyboards.settings_menu(), parse_mode='Markdown')

    @staticmethod
    async def active_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /active command to enable advanced settings."""
        if update.effective_chat.type != 'private':
            await update.message.reply_text("Lệnh này chỉ dùng được trong DM!")
            return

        user_id = update.effective_user.id
        db_user = await db.get_user_by_tg_id(user_id)
        if not db_user:
            await update.message.reply_text("❌ Bạn chưa đăng ký. Sử dụng /start để bắt đầu.")
            return

        # Get command argument
        args = context.args
        if not args:
            await update.message.reply_text(
                "⚠️ **Lệnh /active đã ngừng sử dụng**\n\n"
                "Tất cả các chức năng nâng cao đã được bật mặc định:\n\n"
                "✅ Cho phép âm quỹ - Luôn bật\n"
                "✅ Tự trừ share nhóm - Luôn bật\n\n"
                "💡 Bot giờ đây hoạt động tự động và đơn giản hơn!",
                parse_mode='Markdown'
            )
            return

    @staticmethod
    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        await update.message.reply_text(
            "📚 **Trung Tâm Trợ Giúp**\n\n"
            "🎯 Chọn chủ đề bạn muốn tìm hiểu:\n"
            "👇 Nhấn vào các nút bên dưới",
            parse_mode='Markdown',
            reply_markup=Keyboards.help_menu()
        )

    @staticmethod
    async def setrates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /setrates command - admin only exchange rate management."""
        user_id = update.effective_user.id
        
        # Check if user is admin
        if user_id != ADMIN_USER_ID:
            await update.message.reply_text("❌ Chỉ admin mới có thể sử dụng lệnh này!")
            return
        
        if update.effective_chat.type != 'private':
            await update.message.reply_text("💡 Lệnh này chỉ dùng được trong DM!")
            return
        
        # Build message with current rates
        text = "💱 **Quản lý tỷ giá hối đoái (Admin)**\n\n"
        
        # Show current admin-set rates
        currencies = ["USD", "EUR", "GBP", "JPY", "VND", "TWD"]
        found_rates = False
        displayed_pairs = set()  # To avoid reverse pairs
        
        # Define preferred direction for major currency pairs
        preferred_directions = [
            ("USD", "VND"), ("USD", "TWD"), ("USD", "EUR"), ("USD", "GBP"), ("USD", "JPY"),
            ("EUR", "VND"), ("EUR", "TWD"), ("EUR", "USD"), ("EUR", "GBP"), ("EUR", "JPY"),
            ("GBP", "VND"), ("GBP", "TWD"), ("GBP", "USD"), ("GBP", "EUR"), ("GBP", "JPY"),
            ("TWD", "VND"), ("JPY", "VND"), ("JPY", "TWD")
        ]
        
        text += "📊 **Tỷ giá đã thiết lập:**\n"
        
        # First, try preferred directions
        for from_curr, to_curr in preferred_directions:
            pair = tuple(sorted([from_curr, to_curr]))
            if pair in displayed_pairs:
                continue
                
            try:
                rate = await db.get_exchange_rate(from_curr, to_curr)
                if rate and rate > 0:
                    # Format rate nicely - remove trailing zeros
                    if rate >= 1:
                        rate_str = f"{rate:,.0f}" if rate == int(rate) else f"{rate:,.4f}".rstrip('0').rstrip('.')
                    else:
                        rate_str = f"{rate:.6f}".rstrip('0').rstrip('.')
                    
                    text += f"• 1 {from_curr} = {rate_str} {to_curr}\n"
                    found_rates = True
                    displayed_pairs.add(pair)
            except Exception as e:
                logger.error(f"Error getting rate {from_curr}/{to_curr}: {e}")
        
        # Then check remaining pairs
        for from_curr in currencies:
            for to_curr in currencies:
                if from_curr != to_curr:
                    # Skip if already displayed
                    pair = tuple(sorted([from_curr, to_curr]))
                    if pair in displayed_pairs:
                        continue
                        
                    try:
                        rate = await db.get_exchange_rate(from_curr, to_curr)
                        if rate and rate > 0:
                            # Format rate nicely - remove trailing zeros
                            if rate >= 1:
                                rate_str = f"{rate:,.0f}" if rate == int(rate) else f"{rate:,.4f}".rstrip('0').rstrip('.')
                            else:
                                rate_str = f"{rate:.6f}".rstrip('0').rstrip('.')
                            
                            text += f"• 1 {from_curr} = {rate_str} {to_curr}\n"
                            found_rates = True
                            displayed_pairs.add(pair)
                    except Exception as e:
                        logger.error(f"Error getting rate {from_curr}/{to_curr}: {e}")
        
        if not found_rates:
            text += "❌ Chưa có tỷ giá nào được thiết lập.\n"
        
        text += "\n💡 **Chọn thao tác:**"
            
        await update.message.reply_text(
            text,
            parse_mode='Markdown',
            reply_markup=Keyboards.admin_exchange_rate_menu()
        )

    @staticmethod
    async def spend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /spend command - personal expense tracking."""
        if update.effective_chat.type != 'private':
            await update.message.reply_text("💡 Lệnh này chỉ dùng được trong DM!\nDùng `/gspend` cho chi tiêu nhóm.")
            return

        user_id = update.effective_user.id
        db_user = await db.get_user_by_tg_id(user_id)
        wallets = await db.get_user_wallets(db_user.id)
        
        if not wallets:
            await update.message.reply_text(
                "💰 Chưa có ví nào!\n\n"
                "Dùng `/budget` để tạo ví đầu tiên của bạn.",
                reply_markup=Keyboards.budget_menu()
            )
        else:
            await update.message.reply_text(
                "🧾 Ghi chi tiêu cá nhân\n\n"
                "Chọn ví để ghi nhận chi tiêu:",
                reply_markup=Keyboards.wallet_selection_menu(wallets)
            )

    @staticmethod
    async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /summary command - personal expense summary."""
        if update.effective_chat.type != 'private':
            await update.message.reply_text("💡 Lệnh này chỉ dùng được trong DM!")
            return

        user_id = update.effective_user.id
        
        # Get database user first
        await db.create_or_update_user(user_id, update.effective_user.full_name)
        db_user = await db.get_user_by_tg_id(user_id)
        
        # Get wallets
        wallets = await db.get_user_wallets(db_user.id)
        if not wallets:
            await update.message.reply_text("💰 Chưa có ví nào! Dùng `/budget` để tạo ví.")
            return
        
        # Get today's expenses
        expenses_today = await db.get_personal_expenses_today(db_user.id)
        
        # Build summary
        text = "📊 **Tóm tắt cá nhân**\n\n"
        
        # Currency flag mapping
        currency_flags = {
            "TWD": "🇹🇼",
            "VND": "🇻🇳", 
            "USD": "🇺🇸",
            "EUR": "🇪🇺",
            "JPY": "🇯🇵",
            "KRW": "🇰🇷",
            "CNY": "🇨🇳",
            "THB": "🇹🇭",
            "SGD": "🇸🇬",
            "MYR": "🇲🇾",
            "PHP": "🇵🇭",
            "IDR": "🇮🇩",
            "GBP": "🇬🇧",
            "AUD": "🇦🇺",
            "CAD": "🇨🇦"
        }
        
        # Wallet balances with flags
        text += "💰 **Ví hiện tại:**\n"
        for wallet in wallets:
            balance_decimal = Decimal(wallet.current_balance)
            balance_text = currency_service.format_amount(balance_decimal, wallet.currency)
            flag = currency_flags.get(wallet.currency, "💳")
            text += f"{flag} {balance_text}\n"
        
        # Today's expenses
        if expenses_today:
            text += "🧾 **Chi tiêu hôm nay:**\n"
            daily_totals = {}  # Track totals by currency
            for expense in expenses_today:
                amount_decimal = Decimal(expense.amount)
                
                # Track total by currency
                if expense.currency not in daily_totals:
                    daily_totals[expense.currency] = Decimal('0')
                daily_totals[expense.currency] += amount_decimal
                
                amount_text = currency_service.format_amount(amount_decimal, expense.currency)
                
                # Parse datetime from string if needed and convert to timezone
                if isinstance(expense.created_at, str):
                    from datetime import datetime
                    created_at = datetime.fromisoformat(expense.created_at.replace('Z', '+00:00'))
                else:
                    created_at = expense.created_at
                
                # Convert to local timezone
                if created_at.tzinfo is None:
                    created_at = pytz.UTC.localize(created_at).astimezone(TIMEZONE)
                else:
                    created_at = created_at.astimezone(TIMEZONE)
                
                time_str = created_at.strftime('%H:%M')
                desc = f" - {expense.note}" if expense.note else ""
                text += f"• {time_str} | {amount_text}{desc}\n"
            
            # Show totals by currency with flags
            text += "\n📊 **Tổng chi hôm nay:**\n"
            for currency, total in daily_totals.items():
                total_text = currency_service.format_amount(total, currency)
                flag = currency_flags.get(currency, "💳")
                text += f"{flag} {total_text}\n"
        else:
            text += "✨ **Chưa có chi tiêu nào hôm nay!**"
        
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=Keyboards.personal_expense_menu())

    @staticmethod
    async def register_bank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /register_bank command."""
        await update.message.reply_text(
            "🏦 **Đăng ký ngân hàng**\n\n"
            "⚠️ Tính năng này đang được phát triển!\n\n"
            "Sẽ cho phép:\n"
            "• Liên kết tài khoản ngân hàng\n"
            "• Tự động import giao dịch\n"
            "• Đồng bộ số dư\n\n"
            "Vui lòng quay lại sau! 🔜",
            parse_mode='Markdown'
        )

    @staticmethod
    async def rates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /rates command - show exchange rates."""
        text = "💱 **Tỷ giá hiện tại**\n\n"
        
        # Get admin-set exchange rates from database
        currencies = ["USD", "EUR", "GBP", "JPY", "VND", "TWD"]
        found_rates = False
        displayed_pairs = set()  # To avoid reverse pairs
        
        # Define preferred direction for major currency pairs
        preferred_directions = [
            ("USD", "VND"), ("USD", "TWD"), ("USD", "EUR"), ("USD", "GBP"), ("USD", "JPY"),
            ("EUR", "VND"), ("EUR", "TWD"), ("EUR", "USD"), ("EUR", "GBP"), ("EUR", "JPY"),
            ("GBP", "VND"), ("GBP", "TWD"), ("GBP", "USD"), ("GBP", "EUR"), ("GBP", "JPY"),
            ("TWD", "VND"), ("JPY", "VND"), ("JPY", "TWD")
        ]
        
        # First, try preferred directions
        for from_curr, to_curr in preferred_directions:
            pair = tuple(sorted([from_curr, to_curr]))
            if pair in displayed_pairs:
                continue
                
            try:
                rate = await db.get_exchange_rate(from_curr, to_curr)
                if rate and rate > 0:
                    # Format rate nicely - remove trailing zeros
                    if rate >= 1:
                        rate_str = f"{rate:,.0f}" if rate == int(rate) else f"{rate:,.4f}".rstrip('0').rstrip('.')
                    else:
                        rate_str = f"{rate:.6f}".rstrip('0').rstrip('.')
                    
                    text += f"• 1 {from_curr} = {rate_str} {to_curr}\n"
                    found_rates = True
                    displayed_pairs.add(pair)
            except Exception as e:
                logger.error(f"Error getting rate {from_curr}/{to_curr}: {e}")
        
        # Then check remaining pairs
        for from_curr in currencies:
            for to_curr in currencies:
                if from_curr != to_curr:
                    # Skip if already displayed
                    pair = tuple(sorted([from_curr, to_curr]))
                    if pair in displayed_pairs:
                        continue
                        
                    try:
                        rate = await db.get_exchange_rate(from_curr, to_curr)
                        if rate and rate > 0:
                            # Format rate nicely - remove trailing zeros
                            if rate >= 1:
                                rate_str = f"{rate:,.0f}" if rate == int(rate) else f"{rate:,.4f}".rstrip('0').rstrip('.')
                            else:
                                rate_str = f"{rate:.6f}".rstrip('0').rstrip('.')
                            
                            text += f"• 1 {from_curr} = {rate_str} {to_curr}\n"
                            found_rates = True
                            displayed_pairs.add(pair)
                    except Exception as e:
                        logger.error(f"Error getting rate {from_curr}/{to_curr}: {e}")
        
        if not found_rates:
            text += "❌ Chưa có tỷ giá nào được thiết lập.\n\n"
            text += "💡 Sử dụng /setrates để thiết lập tỷ giá."
        else:
            text += f"\n🕐 **Cập nhật:** {datetime.now().strftime('%H:%M %d/%m/%Y')}"
        
        await update.message.reply_text(text, parse_mode='Markdown')

    @staticmethod
    async def clear_budgets_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /clear_budgets command."""
        if update.effective_chat.type != 'private':
            await update.message.reply_text("💡 Lệnh này chỉ dùng được trong DM!")
            return

        await update.message.reply_text(
            "🗑 **Xóa tất cả ngân sách**\n\n"
            "⚠️ **CẢNH BÁO:** Hành động này sẽ xóa:\n"
            "• Tất cả ví của bạn\n"
            "• Lịch sử chi tiêu\n"
            "• Cài đặt cá nhân\n\n"
            "❌ **KHÔNG THỂ HOÀN TÁC!**\n\n"
            "Tính năng này đang được phát triển để đảm bảo an toàn.",
            parse_mode='Markdown'
        )

    @staticmethod
    async def gspend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /gspend command - group expense splitting."""
        if update.effective_chat.type == 'private':
            await update.message.reply_text(
                "👥 **Chi nhóm & chia tiền**\n\n"
                "💡 Lệnh này chỉ dùng được trong **group chat**!\n\n"
                "📝 **Cách dùng:**\n"
                "1️⃣ Thêm bot vào group\n"
                "2️⃣ Gõ `/gspend` trong group\n"
                "3️⃣ Làm theo hướng dẫn\n\n"
                "🔄 Dùng `/spend` cho chi tiêu cá nhân.",
                parse_mode='Markdown'
            )
            return

        # Group expense logic (same as add_expense_command)
        user_id = update.effective_user.id
        group_id = update.effective_chat.id
        
        await db.create_or_update_user(user_id, update.effective_user.full_name)
        
        group_expense_states[user_id] = {
            'step': 'currency',
            'group_id': group_id,
            'payer_id': user_id
        }
        
        await update.message.reply_text(
            "👥 **Chi nhóm & chia tiền**\n\n"
            "💱 Chọn loại tiền tệ:",
            reply_markup=Keyboards.group_expense_currency_selection(),
            parse_mode='Markdown'
        )

    @staticmethod
    async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /undo command - undo recent expenses in groups."""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        if update.message.chat.type == 'private':
            # In DM, show personal undo menu
            db_user = await db.get_user_by_tg_id(user_id)
            if not db_user:
                await update.message.reply_text("❌ Bạn chưa đăng ký. Sử dụng /start để bắt đầu.")
                return
            
            # Get user's recent personal expenses (last 30 days)
            expenses = await db.get_personal_expenses(db_user.id, 30)
            
            # No time limit: allow deleting any expense in the last 30 days
            undoable_expenses = expenses
            
            if not undoable_expenses:
                await update.message.reply_text(
                    "↩️ **Hoàn tác chi tiêu cá nhân**\n\n"
                    "❌ Không có chi tiêu nào có thể hoàn tác.\n\n"
                    "💡 Chi tiêu chỉ có thể hoàn tác trong vòng 24 giờ sau khi ghi nhận.",
                    parse_mode='Markdown'
                )
            else:
                # Show list of deletable personal expenses
                undo_text = "🗑️ **Xóa chi tiêu cá nhân**\n\n"
                undo_text += "Chọn chi tiêu muốn xóa:\n\n"
                
                keyboard = []
                for expense in undoable_expenses[:5]:  # Show max 5 recent expenses
                    formatted_amount = currency_service.format_amount(expense.amount, expense.currency)
                    description = expense.note if expense.note else "Chi tiêu cá nhân"
                    if len(description) > 20:
                        description = description[:17] + "..."
                    
                    button_text = f"{formatted_amount} - {description}"
                    keyboard.append([InlineKeyboardButton(button_text, callback_data=f"undo_personal_expense_{expense.id}")])
                
                await update.message.reply_text(
                    undo_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
            return
        
        # In group chat, show undoable expenses
        db_user = await db.get_user_by_tg_id(user_id)
        if not db_user:
            await update.message.reply_text("❌ Bạn chưa đăng ký. Sử dụng /start để bắt đầu.")
            return
        
        # Get user's recent expenses in this group (last 30 days)
        expenses = await db.get_group_expenses_by_user(db_user.id, chat_id, 30)
        
        # No time limit: allow deleting any expense in the last 30 days
        undoable_expenses = expenses
        
        if not undoable_expenses:
            await update.message.reply_text(
                "↩️ **Hoàn tác chi tiêu**\n\n"
                "❌ Không có chi tiêu nào có thể hoàn tác.\n\n"
                "💡 Chi tiêu chỉ có thể hoàn tác trong vòng 24 giờ sau khi ghi nhận.",
                parse_mode='Markdown'
            )
        else:
            # Show list of deletable expenses with inline buttons
            undo_text = "🗑️ **Xóa chi tiêu**\n\n"
            undo_text += "Chọn chi tiêu muốn xóa:\n\n"
            
            keyboard = []
            for expense in undoable_expenses[:5]:  # Show max 5 recent expenses
                formatted_amount = currency_service.format_amount(expense.amount, expense.currency)
                description = expense.description if expense.description else "Chi tiêu nhóm"
                if len(description) > 20:
                    description = description[:17] + "..."
                
                button_text = f"{formatted_amount} - {description}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"undo_group_expense_{expense.id}")])
            
            await update.message.reply_text(
                undo_text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    @staticmethod
    async def settle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /settle command - debt settlement overview."""
        if update.effective_chat.type == 'private':
            await update.message.reply_text(
                "✅ **Quản lý công nợ**\n\n"
                "💡 Lệnh này chỉ dùng được trong **group chat**!\n\n"
                "📝 **Chức năng:**\n"
                "• Xem tổng quan công nợ\n"
                "• Quản lý thanh toán\n"
                "• Theo dõi tình trạng\n\n"
                "🔄 Dùng `/summary` cho tóm tắt cá nhân.",
                parse_mode='Markdown'
            )
            return

        group_id = update.effective_chat.id
        
        # Get optimized debts for this group
        try:
            optimized_transactions = await db.optimize_group_debts(group_id, "TWD")  # Default to TWD
            
            if not optimized_transactions:
                await update.message.reply_text(
                    "✅ **Tuyệt vời!**\n\n"
                    "🎉 Không có công nợ nào trong nhóm!\n"
                    "💯 Mọi người đều đã thanh toán xong.",
                    parse_mode='Markdown'
                )
                return
            
            # Calculate statistics without showing details
            total_debts = len(optimized_transactions)
            total_amount = sum(amount for _, _, amount in optimized_transactions)
            
            text = "✅ **Tổng quan công nợ**\n\n"
            text += f"📊 **Thống kê:**\n"
            text += f"• Số giao dịch cần thanh toán: {total_debts}\n"
            text += f"• Tổng tiền đang lưu thông: {currency_service.format_amount(total_amount, 'TWD')}\n\n"
            text += "🔒 **Riêng tư:** Chi tiết gửi qua tin nhắn riêng\n"
            text += "⏰ **Nhắc nhở:** Hàng ngày lúc 10h sáng\n\n"
            text += "💡 **Mẹo:** Kiểm tra DM để xem chi tiết và QR thanh toán!"
            
            await update.message.reply_text(
                text,
                parse_mode='Markdown',
                reply_markup=Keyboards.debt_settlement_options(group_id)
            )
            
        except Exception as e:
            logger.error(f"Error in settle command: {e}")
            await update.message.reply_text(
                "❌ **Lỗi tính toán công nợ**\n\n"
                "Vui lòng thử lại sau!",
                parse_mode='Markdown'
            )

    @staticmethod
    async def format_expense_history_7(expenses):
        """Format 7-day expense history - shared by command and callback"""
        if not expenses:
            return (
                "📚 **Lịch sử chi tiêu (7 ngày)**\n\n"
                "❌ Không có chi tiêu nào trong 7 ngày qua.\n\n"
                "Bắt đầu ghi nhận chi tiêu để theo dõi!"
            )
        
        # Group expenses by date
        from collections import defaultdict
        expenses_by_date = defaultdict(list)
        
        for expense in expenses:
            # Convert datetime to correct timezone for display
            if isinstance(expense.created_at, str):
                created_at = datetime.fromisoformat(expense.created_at.replace('Z', '+00:00'))
            else:
                created_at = expense.created_at
            
            # Convert to local timezone
            if created_at.tzinfo is None:
                created_at = TIMEZONE.localize(created_at)
            else:
                created_at = created_at.astimezone(TIMEZONE)
            
            date_key = created_at.strftime('%d/%m/%Y')
            expenses_by_date[date_key].append(expense)
        
        text = "📚 **Lịch sử chi tiêu (7 ngày)**\n\n"
        
        # Group totals by currency
        grand_total_by_currency = defaultdict(lambda: Decimal('0'))
        
        for date, day_expenses in sorted(expenses_by_date.items(), reverse=True):
            text += f"📅 **{date}**\n"
            day_total_by_currency = defaultdict(lambda: Decimal('0'))
            
            for expense in day_expenses:
                amount = Decimal(expense.amount)
                day_total_by_currency[expense.currency] += amount
                grand_total_by_currency[expense.currency] += amount
                
                amount_text = currency_service.format_amount(amount, expense.currency)
                description = expense.note if expense.note else "Chi tiêu"
                text += f"  • {amount_text} - {description}\n"
            
            # Show daily totals by currency
            for currency, total in day_total_by_currency.items():
                total_text = currency_service.format_amount(total, currency)
                text += f"  💰 **Tổng ngày: {total_text}**\n"
            text += "\n"
        
        # Show grand totals by currency
        text += f"📊 **Tổng 7 ngày:**\n"
        for currency, total in grand_total_by_currency.items():
            total_text = currency_service.format_amount(total, currency)
            text += f"💰 {total_text}\n"
        
        return text.rstrip()  # Remove trailing newline

    @staticmethod
    async def expense_history_7_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /expense_history_7 command - show 7 days expense history."""
        if update.effective_chat.type != 'private':
            await update.message.reply_text("💡 Lệnh này chỉ dùng được trong DM!")
            return
            
        user_id = update.effective_user.id
        
        try:
            # Get database user
            db_user = await db.get_user_by_tg_id(user_id)
            
            # Get expenses from last 7 days
            expenses = await db.get_personal_expenses(db_user.id, 7)
            
            # Format using shared function
            text = await BotHandlers.format_expense_history_7(expenses)
            await update.message.reply_text(text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in expense_history_7 command: {e}")
            await update.message.reply_text(
                "❌ **Lỗi lấy lịch sử chi tiêu**\n\n"
                "Vui lòng thử lại sau!",
                parse_mode='Markdown'
            )

    @staticmethod
    async def wallets_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /wallets command - show user wallets with pending deductions."""
        if update.effective_chat.type != 'private':
            await update.message.reply_text("💡 Lệnh này chỉ dùng được trong DM!")
            return
            
        user_id = update.effective_user.id
        
        # Currency flags mapping
        currency_flags = {
            "TWD": "🇹🇼",
            "USD": "🇺🇸", 
            "EUR": "🇪🇺",
            "GBP": "🇬🇧",
            "JPY": "🇯🇵",
            "VND": "🇻🇳",
            "CNY": "🇨🇳",
            "KRW": "🇰🇷",
            "THB": "🇹🇭",
            "SGD": "🇸🇬"
        }
        
        try:
            # Get database user
            db_user = await db.get_user_by_tg_id(user_id)
            wallets = await db.get_user_wallets(db_user.id)
            pending_deductions = await db.get_user_pending_deductions(db_user.id)
            
            if not wallets and not pending_deductions:
                await update.message.reply_text(
                    "💰 **Danh sách ví**\n\n"
                    "❌ Bạn chưa có ví nào.\n\n"
                    "💡 Sử dụng /start → 💰 Quản lý Budget → ➕ Tạo ví mới"
                )
                return
            
            text = "💰 **Danh sách ví của bạn:**\n\n"
            
            # Show wallets with flags
            for wallet in wallets:
                balance = Decimal(wallet.current_balance)
                formatted_balance = currency_service.format_amount(balance, wallet.currency)
                
                # Get flag for currency
                flag = currency_flags.get(wallet.currency, "💰")
                status = "✅" if balance >= 0 else "⚠️"
                
                text += f"{status} **{flag} {wallet.currency}**: {formatted_balance}\n"
                if wallet.note:
                    text += f"   📝 {wallet.note}\n"
                text += "\n"
            
            # Show pending deductions
            if pending_deductions:
                text += "📋 **Ghi nợ chờ thanh toán:**\n\n"
                for pending in pending_deductions:
                    share_amount = Decimal(str(pending['share_amount']))
                    formatted_share = currency_service.format_amount(share_amount, pending['share_currency'])
                    
                    description = pending.get('description', 'Chi tiêu nhóm')
                    text += f"💳 {formatted_share} - {description}\n"
                    
                    if pending.get('suggested_wallet_id'):
                        suggested_amount = Decimal(str(pending['suggested_deduction_amount']))
                        wallet_currency = pending['wallet_currency']
                        formatted_suggested = currency_service.format_amount(suggested_amount, wallet_currency)
                        if pending['share_currency'] != wallet_currency:
                            text += f"   💡 Đề xuất: {formatted_suggested} từ ví {wallet_currency}\n"
                    text += "\n"
                
                text += "💡 Sử dụng menu bên dưới để thanh toán"
            
            # Create keyboard with pending payment options
            keyboard = []
            if pending_deductions:
                keyboard.append([InlineKeyboardButton("💳 Thanh toán ghi nợ", callback_data="pending_payments")])
            keyboard.append([InlineKeyboardButton("⚙️ Quản lý ví", callback_data="wallet_management")])
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in wallets command: {e}")
            await update.message.reply_text(
                "❌ Có lỗi xảy ra khi lấy thông tin ví.\n"
                "Vui lòng thử lại sau!"
            )

    @staticmethod
    async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries from inline keyboards."""
        query = update.callback_query
        data = query.data
        user_id = query.from_user.id
        
        logger.info(f"Processing callback query: {data} from user {user_id}")
        
        try:
            await query.answer()
        except Exception as e:
            logger.warning(f"Failed to answer callback query: {e}")
            # Continue processing even if answer fails

        try:
            if data == "main_menu":
                logger.info("Processing main_menu callback")
                await query.edit_message_text(
                    "Chọn một tùy chọn:",
                    reply_markup=Keyboards.main_dm_menu()
                )

            elif data == "budget_menu":
                logger.info("Processing budget_menu callback")
                
                # Get database user first
                db_user = await db.get_user_by_tg_id(user_id)
                wallets = await db.get_user_wallets(db_user.id)
                text = "💰 Quản lý Budget\n\n"
                if wallets:
                    text += "Ví hiện tại:\n"
                    for wallet in wallets:
                        balance_decimal = Decimal(wallet.current_balance)
                        balance_text = currency_service.format_amount(balance_decimal, wallet.currency)
                        text += f"• {balance_text}\n"
                
                await query.edit_message_text(text, reply_markup=Keyboards.budget_menu())
                logger.info("Completed budget_menu callback")

            elif data == "pending_payments":
                logger.info("Processing pending_payments callback")
                
                # Get database user
                db_user = await db.get_user_by_tg_id(user_id)
                pending_deductions = await db.get_user_pending_deductions(db_user.id)
                
                if not pending_deductions:
                    await query.edit_message_text(
                        "✅ **Không có ghi nợ nào cần thanh toán**\n\n"
                        "Tất cả khoản nợ của bạn đã được thanh toán.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Quay lại", callback_data="main_menu")]])
                    )
                    return
                
                text = "💳 **Ghi nợ cần thanh toán:**\n\n"
                keyboard = []
                
                for pending in pending_deductions:
                    share_amount = Decimal(str(pending['share_amount']))
                    formatted_share = currency_service.format_amount(share_amount, pending['share_currency'])
                    description = pending.get('description', 'Chi tiêu nhóm')
                    
                    text += f"📋 {formatted_share} - {description}\n"
                    if pending.get('suggested_wallet_id'):
                        suggested_amount = Decimal(str(pending['suggested_deduction_amount']))
                        wallet_currency = pending['wallet_currency']
                        formatted_suggested = currency_service.format_amount(suggested_amount, wallet_currency)
                        text += f"   💡 Đề xuất: {formatted_suggested} từ ví {wallet_currency}\n"
                    text += "\n"
                    
                    # Add button for each pending payment
                    keyboard.append([InlineKeyboardButton(
                        f"💳 Thanh toán {formatted_share}", 
                        callback_data=f"pay_pending_{pending['id']}"
                    )])
                
                keyboard.append([InlineKeyboardButton("🔙 Quay lại", callback_data="main_menu")])
                await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

            elif data == "wallet_management":
                logger.info("Processing wallet_management callback")
                
                # Get database user first
                db_user = await db.get_user_by_tg_id(user_id)
                wallets = await db.get_user_wallets(db_user.id)
                text = "💰 Quản lý Budget\n\n"
                if wallets:
                    text += "Ví hiện tại:\n"
                    for wallet in wallets:
                        balance_decimal = Decimal(wallet.current_balance)
                        balance_text = currency_service.format_amount(balance_decimal, wallet.currency)
                        text += f"• {balance_text}\n"
                
                await query.edit_message_text(text, reply_markup=Keyboards.budget_menu())

            elif data == "personal_expense_menu":
                logger.info("Processing personal_expense_menu callback")
                await query.edit_message_text(
                    "🧾 Chi tiêu cá nhân",
                    reply_markup=Keyboards.personal_expense_menu()
                )

            elif data.startswith("pay_pending_"):
                logger.info(f"Processing pay_pending callback: {data}")
                pending_id = int(data.replace("pay_pending_", ""))
                
                # Get pending deduction details
                db_user = await db.get_user_by_tg_id(user_id)
                pending_deductions = await db.get_user_pending_deductions(db_user.id)
                
                pending = None
                for p in pending_deductions:
                    if p['id'] == pending_id:
                        pending = p
                        break
                
                if not pending:
                    await query.edit_message_text(
                        "❌ Không tìm thấy ghi nợ này hoặc đã được thanh toán.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Quay lại", callback_data="pending_payments")]])
                    )
                    return
                
                # Show payment options
                share_amount = Decimal(str(pending['share_amount']))
                formatted_share = currency_service.format_amount(share_amount, pending['share_currency'])
                description = pending.get('description', 'Chi tiêu nhóm')
                
                text = f"💳 **Thanh toán ghi nợ**\n\n"
                text += f"📋 **Khoản nợ:** {formatted_share} - {description}\n\n"
                
                # Get user wallets for payment options
                wallets = await db.get_user_wallets(db_user.id)
                keyboard = []
                
                if pending.get('suggested_wallet_id'):
                    # Add suggested option first
                    suggested_amount = Decimal(str(pending['suggested_deduction_amount']))
                    wallet_currency = pending['wallet_currency']
                    formatted_suggested = currency_service.format_amount(suggested_amount, wallet_currency)
                    
                    text += f"💡 **Đề xuất:** {formatted_suggested} từ ví {wallet_currency}\n\n"
                    keyboard.append([InlineKeyboardButton(
                        f"✅ Thanh toán {formatted_suggested}", 
                        callback_data=f"confirm_payment_{pending_id}_{pending['suggested_wallet_id']}"
                    )])
                
                # Add other wallet options
                text += "🔄 **Hoặc chọn ví khác:**\n"
                for wallet in wallets:
                    if wallet.id != pending.get('suggested_wallet_id'):
                        balance = Decimal(wallet.current_balance)
                        formatted_balance = currency_service.format_amount(balance, wallet.currency)
                        keyboard.append([InlineKeyboardButton(
                            f"{wallet.currency}: {formatted_balance}", 
                            callback_data=f"confirm_payment_{pending_id}_{wallet.id}"
                        )])
                
                keyboard.append([InlineKeyboardButton("🔙 Quay lại", callback_data="pending_payments")])
                await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

            elif data.startswith("confirm_payment_"):
                logger.info(f"Processing confirm_payment callback: {data}")
                parts = data.replace("confirm_payment_", "").split("_")
                pending_id = int(parts[0])
                wallet_id = int(parts[1])
                
                try:
                    # Get pending deduction details
                    db_user = await db.get_user_by_tg_id(user_id)
                    pending_deductions = await db.get_user_pending_deductions(db_user.id)
                    
                    pending = None
                    for p in pending_deductions:
                        if p['id'] == pending_id:
                            pending = p
                            break
                    
                    if not pending:
                        await query.edit_message_text(
                            "❌ Không tìm thấy ghi nợ này hoặc đã được thanh toán.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Quay lại", callback_data="pending_payments")]])
                        )
                        return
                    
                    # Get wallet details
                    wallet = await db.get_wallet(wallet_id)
                    if not wallet or wallet.user_id != db_user.id:
                        await query.edit_message_text(
                            "❌ Ví không hợp lệ.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Quay lại", callback_data="pending_payments")]])
                        )
                        return
                    
                    # Calculate deduction amount
                    share_amount = Decimal(str(pending['share_amount']))
                    if wallet.currency == pending['share_currency']:
                        fx_rate = Decimal('1.0')
                        deduction_amount = share_amount
                    else:
                        fx_rate, deduction_amount = await currency_service.convert(
                            share_amount, pending['share_currency'], wallet.currency
                        )
                    
                    # Perform the actual deduction
                    success = await db.update_wallet_balance(
                        wallet.id, -deduction_amount, "Thanh toán ghi nợ nhóm"
                    )
                    
                    if success:
                        # Move to group_deductions
                        await db.add_group_deduction(
                            db_user.id, pending['trip_id'], pending['expense_id'],
                            share_amount, pending['share_currency'],
                            wallet.id, fx_rate, deduction_amount
                        )
                        
                        # Remove from pending
                        await db.cancel_pending_deduction(pending_id)
                        
                        # Show success message
                        formatted_share = currency_service.format_amount(share_amount, pending['share_currency'])
                        formatted_deduction = currency_service.format_amount(deduction_amount, wallet.currency)
                        
                        if pending['share_currency'] == wallet.currency:
                            success_text = f"✅ **Đã thanh toán {formatted_deduction}**\n\n"
                        else:
                            success_text = f"✅ **Đã thanh toán {formatted_share}**\n"
                            success_text += f"💱 Trừ {formatted_deduction} từ ví {wallet.currency}\n\n"
                        
                        success_text += "Ghi nợ đã được xóa khỏi danh sách chờ thanh toán."
                        
                        await query.edit_message_text(
                            success_text,
                            parse_mode='Markdown',
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("💰 Xem ví", callback_data="wallet_management")],
                                [InlineKeyboardButton("🔙 Menu chính", callback_data="main_menu")]
                            ])
                        )
                    else:
                        await query.edit_message_text(
                            "❌ Lỗi khi cập nhật ví. Vui lòng thử lại.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Quay lại", callback_data="pending_payments")]])
                        )
                        
                except Exception as e:
                    logger.error(f"Error in confirm_payment: {e}")
                    await query.edit_message_text(
                        "❌ Có lỗi xảy ra khi xử lý thanh toán. Vui lòng thử lại.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Quay lại", callback_data="pending_payments")]])
                    )

            elif data == "add_personal_expense":
                logger.info("Processing add_personal_expense callback")
                
                # Get user wallets
                db_user = await db.get_user_by_tg_id(user_id)
                wallets = await db.get_user_wallets(db_user.id)
                
                if not wallets:
                    await query.edit_message_text(
                        "❌ Bạn cần tạo ví trước khi thêm chi tiêu.\n\n"
                        "Vui lòng tạo ví đầu tiên:",
                        reply_markup=Keyboards.budget_menu()
                    )
                else:
                    await query.edit_message_text(
                        "🧾 Thêm chi tiêu cá nhân\n\n"
                        "Chọn ví để ghi nhận chi tiêu:",
                        reply_markup=Keyboards.wallet_selection_menu(wallets)
                    )

            elif data.startswith("wallet_") and data != "wallet_details":
                logger.info(f"Processing wallet selection: {data}")
                wallet_id = int(data.replace("wallet_", ""))
                
                # Store wallet selection for expense
                user_states[user_id] = {
                    'action': 'personal_expense_amount',
                    'wallet_id': wallet_id
                }
                
                await query.edit_message_text(
                    "💰 Nhập số tiền và mô tả chi tiêu\n\n"
                    "📝 Ví dụ: 120 ăn sáng\n"
                    "📝 Hoặc chỉ: 120\n\n"
                    "➡️ Nhập thông tin chi tiêu:",
                    reply_markup=Keyboards.back_to_expense_menu()
                )

            elif data == "settings_menu":
                # Get internal user ID
                db_user = await db.get_user_by_tg_id(user_id)
                if not db_user:
                    await query.edit_message_text("❌ Lỗi: Không tìm thấy thông tin user!")
                    return
                
                user_settings = await db.get_user_settings(db_user.id)
                
                # Build settings display (chỉ còn các mục cần thiết)
                text = "⚙️ **Cài đặt**\n\n"
                # Bank accounts section
                try:
                    bank_accounts = await db.get_user_bank_accounts(db_user.id)
                    if bank_accounts:
                        text += "🏦 **Tài khoản ngân hàng:**\n"
                        for account in bank_accounts:
                            bank_name = account[2]
                            account_number = account[3]
                            account_name = account[4] if account[4] else ""
                            text += f"• {bank_name}: {account_number}\n"
                            if account_name:
                                text += f"  Tên: {account_name}\n"
                        text += "\n"
                    else:
                        text += "🏦 **Tài khoản ngân hàng:** Chưa có\n\n"
                except Exception as e:
                    logger.error(f"Error getting bank accounts: {e}")
                    text += "🏦 **Tài khoản ngân hàng:** Lỗi tải dữ liệu\n\n"
                # Không hiển thị phần cài đặt thanh toán nữa
                await query.edit_message_text(text, reply_markup=Keyboards.settings_menu(), parse_mode='Markdown')

            elif data == "expense_history_7":
                logger.info("Processing expense_history_7 callback")
                
                # Get user expenses for the last 7 days
                db_user = await db.get_user_by_tg_id(user_id)
                expenses = await db.get_personal_expenses(db_user.id, 7)
                
                # Format using shared function
                text = await BotHandlers.format_expense_history_7(expenses)
                
                await query.edit_message_text(
                    text,
                    parse_mode='Markdown',
                    reply_markup=Keyboards.back_to_expense_menu()
                )

            elif data == "undo_expense":
                logger.info("Processing delete expense menu callback")
                
                # Get user's most recent expenses that can be undone
                db_user = await db.get_user_by_tg_id(user_id)
                expenses = await db.get_personal_expenses(db_user.id, 30)  # Last 30 days
                
                # No time limit: allow deleting any expense in the last 30 days
                undoable_expenses = expenses
                
                if not undoable_expenses:
                    await query.edit_message_text(
                        "🗑️ **Xóa chi tiêu**\n\n"
                        "❌ Không có chi tiêu nào để xóa.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.back_to_expense_menu()
                    )
                else:
                    # Pagination: show 20 per page, start at page 1
                    page = 1
                    page_size = 20
                    start = (page - 1) * page_size
                    end = start + page_size
                    page_items = undoable_expenses[start:end]

                    total = len(undoable_expenses)
                    total_pages = (total + page_size - 1) // page_size

                    undo_text = "🗑️ **Xóa chi tiêu**\n\n"
                    undo_text += f"Trang {page}/{total_pages} — Tổng: {total}\n\n"
                    undo_text += "Chọn chi tiêu muốn xóa:\n\n"

                    keyboard = []
                    for expense in page_items:
                        formatted_amount = currency_service.format_amount(expense.amount, expense.currency)
                        description = expense.note if expense.note else "Chi tiêu cá nhân"
                        if len(description) > 20:
                            description = description[:17] + "..."
                        button_text = f"{formatted_amount} - {description}"
                        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"undo_expense_{expense.id}")])

                    nav_row = []
                    if total_pages > 1:
                        if page < total_pages:
                            nav_row.append(InlineKeyboardButton("➡️ Trang sau", callback_data=f"undo_expense_page_{page+1}"))
                    if nav_row:
                        keyboard.append(nav_row)
                    keyboard.append([InlineKeyboardButton("🔙 Quay lại", callback_data="personal_expense_menu")])

                    await query.edit_message_text(
                        undo_text,
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )

            elif data.startswith("undo_expense_page_"):
                # Pagination handler for personal expense undo list
                try:
                    page = int(data.replace("undo_expense_page_", ""))
                except ValueError:
                    page = 1

                db_user = await db.get_user_by_tg_id(user_id)
                expenses = await db.get_personal_expenses(db_user.id, 30)
                if not expenses:
                    await query.edit_message_text(
                        "🗑️ **Xóa chi tiêu**\n\n"
                        "❌ Không có chi tiêu nào để xóa.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.back_to_expense_menu()
                    )
                    return

                page_size = 20
                total = len(expenses)
                total_pages = (total + page_size - 1) // page_size
                page = max(1, min(page, total_pages))
                start = (page - 1) * page_size
                end = start + page_size
                page_items = expenses[start:end]

                undo_text = "🗑️ **Xóa chi tiêu**\n\n"
                undo_text += f"Trang {page}/{total_pages} — Tổng: {total}\n\n"
                undo_text += "Chọn chi tiêu muốn xóa:\n\n"

                keyboard = []
                for expense in page_items:
                    formatted_amount = currency_service.format_amount(expense.amount, expense.currency)
                    description = expense.note if expense.note else "Chi tiêu cá nhân"
                    if len(description) > 20:
                        description = description[:17] + "..."
                    keyboard.append([InlineKeyboardButton(f"{formatted_amount} - {description}", callback_data=f"undo_expense_{expense.id}")])

                nav_row = []
                if page > 1:
                    nav_row.append(InlineKeyboardButton("⬅️ Trang trước", callback_data=f"undo_expense_page_{page-1}"))
                if page < total_pages:
                    nav_row.append(InlineKeyboardButton("➡️ Trang sau", callback_data=f"undo_expense_page_{page+1}"))
                if nav_row:
                    keyboard.append(nav_row)
                keyboard.append([InlineKeyboardButton("🔙 Quay lại", callback_data="personal_expense_menu")])

                await query.edit_message_text(
                    undo_text,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            # VietQR and Banking Handlers
            elif data == "bank_account_menu":
                try:
                    # Get user from database
                    db_user = await db.get_user_by_tg_id(user_id)
                    if not db_user:
                        await query.edit_message_text(
                            "❌ **Lỗi:** Không tìm thấy thông tin user!\n\n"
                            "Vui lòng khởi động lại bot bằng lệnh /start",
                            parse_mode='Markdown',
                            reply_markup=Keyboards.main_dm_menu()
                        )
                        return

                    # Get bank accounts
                    bank_accounts = await db.get_user_bank_accounts(db_user.id)
                    has_account = len(bank_accounts) > 0

                    text = "💳 **Quản lý tài khoản ngân hàng**\n\n"
                    if has_account:
                        # Show the single bank account info
                        account = bank_accounts[0]  # Only one account allowed
                        account_id, bank_code, bank_name, account_number, account_name = account[:5]
                        text += f"🏛️ **{bank_name}**\n"
                        text += f"💳 **STK:** `{account_number}`\n"
                        text += f"👤 **Tên:** {account_name}\n\n"
                        text += "📱 Sử dụng **Xem QR** để tạo mã QR nhận tiền"
                    else:
                        text += "❌ **Chưa có tài khoản nào**\n\n"
                        text += "Thêm tài khoản ngân hàng để:\n"
                        text += "• Nhận chuyển khoản VND\n"
                    text += "• Tạo mã QR thanh toán\n"
                    text += "• Quản lý giao dịch tự động"

                    # Create appropriate keyboard
                    keyboard = []
                    if has_account:
                        keyboard.append([InlineKeyboardButton("📱 Xem QR", callback_data="view_qr")])
                        keyboard.append([InlineKeyboardButton("🗑️ Xoá STK", callback_data="delete_bank_account")])
                    else:
                        keyboard.append([InlineKeyboardButton("➕ Thêm STK", callback_data="add_bank_account")])

                    keyboard.append([InlineKeyboardButton("🔙 Quay lại", callback_data="settings_menu")])

                    await query.edit_message_text(
                        text,
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )

                except Exception as e:
                    logger.error(f"Error in bank_account_menu: {e}")
                    await query.edit_message_text(
                        "❌ **Có lỗi xảy ra**\n\n"
                        "Không thể tải thông tin tài khoản ngân hàng.\n"
                        "Vui lòng thử lại sau.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.main_dm_menu()
                    )

            # Handle both text and photo messages
                except Exception:
                    # If edit fails (e.g., message is a photo), send new message
                    await query.answer()
                    await context.bot.send_message(
                        chat_id=query.message.chat.id,
                        text=text,
                        parse_mode='Markdown',
                        reply_markup=Keyboards.bank_account_menu(has_account)
                    )

            elif data == "view_qr_no_amount":
                # Get user's bank account (should be only one)
                db_user = await db.get_user_by_tg_id(user_id)
                if not db_user:
                    await query.edit_message_text("❌ Lỗi: Không tìm thấy thông tin user!")
                    return
                
                user_accounts = await db.get_user_bank_accounts(db_user.id)
                if not user_accounts:
                    await query.edit_message_text(
                        "❌ **Chưa có tài khoản ngân hàng**\n\n"
                        "Bạn cần thêm tài khoản ngân hàng trước khi xem QR.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.bank_account_menu(False)
                    )
                    return
                
                # Get the first (and only) bank account
                bank_account = user_accounts[0]
                account_id, bank_code, bank_name, account_number, account_name, is_default = bank_account
                
                # Generate QR without amount
                qr_url = await vietqr_service.generate_qr_direct(
                    bank_code,
                    account_number,
                    account_name,
                    amount=0,  # No amount
                    description="Chuyển khoản"
                )
                
                if qr_url:
                    # Create a nice formatted message
                    text = f"📱 **MÃ QR NHẬN TIỀN**\n\n"
                    text += f"🏛️ **Ngân hàng:** {bank_name}\n"
                    text += f"💳 **Số tài khoản:** `{account_number}`\n"
                    text += f"👤 **Tên tài khoản:** {account_name}\n\n"
                    text += "💡 **Hướng dẫn sử dụng:**\n"
                    text += "• Gửi mã QR này cho người muốn chuyển tiền\n"
                    text += "• Họ quét mã QR bằng app ngân hàng\n"
                    text += "• Tự nhập số tiền muốn chuyển\n"
                    text += "• Xác nhận chuyển khoản\n\n"
                    text += "✅ **QR này an toàn:** Không chứa số tiền cụ thể"
                    
                    # Send QR image with better formatting
                    await query.answer("📱 Đang tạo mã QR...")
                    await context.bot.send_photo(
                        chat_id=query.message.chat.id,
                        photo=qr_url,
                        caption=text,
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Tạo QR mới", callback_data="view_qr_no_amount")],
                            [InlineKeyboardButton("🔙 Quay lại", callback_data="bank_account_menu")]
                        ])
                    )
                else:
                    await query.edit_message_text(
                        "❌ **Lỗi tạo QR Code**\n\n"
                        "Không thể tạo mã QR. Vui lòng thử lại sau.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.bank_account_menu(True)
                    )

            elif data == "create_qr_with_amount":
                # Get user's bank account
                db_user = await db.get_user_by_tg_id(user_id)
                if not db_user:
                    await query.edit_message_text("❌ Lỗi: Không tìm thấy thông tin user!")
                    return
                
                user_accounts = await db.get_user_bank_accounts(db_user.id)
                if not user_accounts:
                    await query.edit_message_text(
                        "❌ **Chưa có tài khoản ngân hàng**\n\n"
                        "Bạn cần thêm tài khoản ngân hàng trước khi tạo QR.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.bank_account_menu(False)
                    )
                    return
                
                # Show amount input form
                await query.edit_message_text(
                    "💰 **TẠO QR CÓ SỐ TIỀN**\n\n"
                    "Nhập số tiền bạn muốn nhận (VND):\n\n"
                    "💡 **Lưu ý:** QR này sẽ có số tiền cố định.\n"
                    "Người chuyển không thể thay đổi số tiền.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Quay lại", callback_data="bank_account_menu")]
                    ])
                )
                
                # Set user state for amount input
                user_states[user_id] = {
                    'action': 'create_qr_with_amount',
                    'step': 'amount_input'
                }

            elif data == "payment_settings":
                text = "💰 **Cài đặt thanh toán**\n\n"
                text += "🇻🇳 Nhận chuyển khoản VND: ✅ Luôn bật\n"
                text += "💡 Khi có nợ bằng TWD, USD... sẽ luôn có tuỳ chọn nhận bằng VND (tự động quy đổi tỷ giá).\n"
                await query.edit_message_text(
                    text,
                    parse_mode='Markdown',
                    reply_markup=Keyboards.back_to_settings()
                )

            elif data == "add_bank_account":
                # Check if user already has a bank account
                user_accounts = await db.get_user_bank_accounts(user_id)
                if user_accounts:
                    await query.edit_message_text(
                        "⚠️ **Giới hạn tài khoản**\n\n"
                        "Bạn chỉ có thể đăng ký tối đa 1 tài khoản ngân hàng.\n"
                        "Vui lòng xóa tài khoản hiện tại nếu muốn thêm tài khoản mới.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.bank_account_menu(True)
                    )
                    return
                
                await query.edit_message_text(
                    "🏛️ **Thêm tài khoản ngân hàng**\n\n"
                    "Chọn ngân hàng của bạn:",
                    parse_mode='Markdown',
                    reply_markup=Keyboards.bank_selection()
                )

            elif data.startswith("select_bank_"):
                bank_code = data.replace("select_bank_", "")
                bank_name = vietqr_service.get_bank_name(bank_code)
                
                if not bank_name:
                    await query.edit_message_text("❌ Ngân hàng không hợp lệ!")
                    return
                
                # Store bank selection in user state
                user_states[user_id] = {
                    'action': 'add_bank_account',
                    'bank_code': bank_code,
                    'bank_name': bank_name
                }
                
                await query.edit_message_text(
                    f"🏛️ **Thêm tài khoản {bank_name}**\n\n"
                    "💳 Vui lòng nhập số tài khoản của bạn:",
                    parse_mode='Markdown'
                )

            elif data == "show_more_banks":
                await query.edit_message_text(
                    "🏛️ **Tất cả ngân hàng**\n\n"
                    "Chọn ngân hàng của bạn:",
                    parse_mode='Markdown',
                    reply_markup=Keyboards.bank_selection_all()
                )

            elif data == "show_main_banks":
                await query.edit_message_text(
                    "🏛️ **Thêm tài khoản ngân hàng**\n\n"
                    "Chọn ngân hàng của bạn:",
                    parse_mode='Markdown',
                    reply_markup=Keyboards.bank_selection()
                )

            elif data == "header_major":
                # Ignore header button clicks
                pass

            elif data == "edit_bank_account":
                db_user = await db.get_user_by_tg_id(user_id)
                user_accounts = await db.get_user_bank_accounts(db_user.id)
                
                if not user_accounts:
                    await query.edit_message_text(
                        "❌ **Không tìm thấy tài khoản**\n\n"
                        "Không có tài khoản nào để sửa.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.bank_account_menu(False)
                    )
                    return
                
                account = user_accounts[0]
                account_id, bank_code, bank_name, account_number, account_name = account[:5]
                
                await query.edit_message_text(
                    f"✏️ **Sửa thông tin tài khoản**\n\n"
                    f"🏛️ **{bank_name}**\n"
                    f"💳 **STK:** `{account_number}`\n"
                    f"👤 **Tên:** {account_name}\n\n"
                    f"💡 Hiện tại chỉ hỗ trợ xóa và tạo lại tài khoản mới.",
                    parse_mode='Markdown',
                    reply_markup=Keyboards.bank_account_menu(True)
                )

            elif data == "set_default_bank":
                db_user = await db.get_user_by_tg_id(user_id)
                user_accounts = await db.get_user_bank_accounts(db_user.id)
                
                if not user_accounts:
                    await query.edit_message_text(
                        "❌ **Không tìm thấy tài khoản**\n\n"
                        "Bạn chưa có tài khoản ngân hàng nào.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.bank_account_menu(False)
                    )
                    return
                
                account = user_accounts[0]
                account_id, bank_code, bank_name, account_number, account_name = account[:5]
                
                # Since only one account is allowed, it's already the default
                await query.edit_message_text(
                    f"✅ **Tài khoản mặc định**\n\n"
                    f"🏛️ **{bank_name}**\n"
                    f"💳 **STK:** `{account_number}`\n"
                    f"👤 **Tên:** {account_name}\n\n"
                    f"💡 Tài khoản này đã là tài khoản mặc định của bạn.",
                    parse_mode='Markdown',
                    reply_markup=Keyboards.bank_account_menu(True)
                )

            elif data == "list_bank_accounts":
                db_user = await db.get_user_by_tg_id(user_id)
                user_accounts = await db.get_user_bank_accounts(db_user.id)
                
                if not user_accounts:
                    await query.edit_message_text(
                        "❌ **Không tìm thấy tài khoản**\n\n"
                        "Bạn chưa có tài khoản ngân hàng nào.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.bank_account_menu(False)
                    )
                    return
                
                account = user_accounts[0]
                account_id, bank_code, bank_name, account_number, account_name = account[:5]
                
                text = f"💳 **Thông tin tài khoản ngân hàng**\n\n"
                text += f"🏛️ **{bank_name}**\n"
                text += f"💳 **STK:** `{account_number}`\n"
                text += f"👤 **Tên:** {account_name}\n\n"
                text += "💡 Sử dụng các tùy chọn bên dưới để quản lý tài khoản."
                
                await query.edit_message_text(
                    text,
                    parse_mode='Markdown',
                    reply_markup=Keyboards.bank_account_menu(True)
                )

            elif data == "delete_bank_account":
                db_user = await db.get_user_by_tg_id(user_id)
                user_accounts = await db.get_user_bank_accounts(db_user.id)
                
                if not user_accounts:
                    await query.edit_message_text(
                        "❌ **Không tìm thấy tài khoản**\n\n"
                        "Không có tài khoản nào để xóa.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.bank_account_menu(False)
                    )
                    return
                
                account = user_accounts[0]
                account_id, bank_code, bank_name, account_number, account_name = account[:5]
                
                # Delete the account
                await db.delete_bank_account(account_id)
                
                await query.edit_message_text(
                    f"✅ **Đã xóa tài khoản**\n\n"
                    f"Tài khoản {bank_name} - {account_number} đã được xóa thành công.\n\n"
                    f"Bạn có thể thêm tài khoản mới nếu cần.",
                    parse_mode='Markdown',
                    reply_markup=Keyboards.bank_account_menu(False)
                )

            elif data == "toggle_accept_vnd":
                db_user = await db.get_user_by_tg_id(user_id)
                preferences = await db.get_payment_preferences(db_user.id)
                
                current_setting = preferences[0] if preferences else False
                new_setting = not current_setting
                
                await db.update_payment_preferences(db_user.id, accept_vnd=new_setting)
                
                text = f"🇻🇳 **Nhận chuyển khoản VND: {'✅ Bật' if new_setting else '❌ Tắt'}**\n\n"
                if new_setting:
                    text += "✅ Bạn có thể nhận chuyển khoản VND từ người khác.\n"
                    text += "💡 Hãy thêm tài khoản ngân hàng để sử dụng tính năng này."
                else:
                    text += "❌ Bạn sẽ không nhận được tùy chọn chuyển khoản VND."
                
                await query.edit_message_text(
                    text,
                    parse_mode='Markdown',
                    reply_markup=Keyboards.back_to_settings()
                )

            elif data == "toggle_auto_convert":
                db_user = await db.get_user_by_tg_id(user_id)
                preferences = await db.get_payment_preferences(db_user.id)
                
                current_setting = preferences[1] if preferences else False
                new_setting = not current_setting
                
                await db.update_payment_preferences(db_user.id, auto_convert=new_setting)
                
                text = f"🔄 **Tự động chuyển đổi nợ: {'✅ Bật' if new_setting else '❌ Tắt'}**\n\n"
                if new_setting:
                    text += "✅ Nợ sẽ được tự động chuyển đổi sang VND khi gửi thông báo."
                else:
                    text += "❌ Nợ sẽ hiển thị theo tiền tệ gốc."
                
                await query.edit_message_text(
                    text,
                    parse_mode='Markdown',
                    reply_markup=Keyboards.back_to_settings()
                )

            # Admin Exchange Rate Handlers
            elif data == "view_rates":
                if user_id != ADMIN_USER_ID:
                    await query.edit_message_text("❌ Không có quyền truy cập!")
                    return
                
                rates = await db.get_all_exchange_rates()
                text = "📈 **Tỷ giá hiện tại**\n\n"
                
                if rates:
                    for rate in rates:
                        from_currency, to_currency, rate_value, created_at = rate
                        text += f"💱 {from_currency}/{to_currency}: {rate_value}\n"
                        text += f"   ⏰ Cập nhật: {created_at[:19]}\n\n"
                else:
                    text += "❌ Chưa có tỷ giá nào được thiết lập."
                
                await query.edit_message_text(
                    text,
                    parse_mode='Markdown',
                    reply_markup=Keyboards.admin_exchange_rate_menu()
                )

            elif data == "set_twd_vnd_rate":
                if user_id != ADMIN_USER_ID:
                    await query.edit_message_text("❌ Không có quyền truy cập!")
                    return
                
                user_states[user_id] = {
                    'action': 'set_exchange_rate',
                    'from_currency': 'TWD',
                    'to_currency': 'VND'
                }
                
                await query.edit_message_text(
                    "💱 **Cập nhật tỷ giá TWD/VND**\n\n"
                    "💰 Nhập tỷ giá mới (VND cho 1 TWD):\n"
                    "Ví dụ: 875 nghĩa là 1 TWD = 875 VND",
                    parse_mode='Markdown'
                )

            elif data == "set_usd_vnd_rate":
                if user_id != ADMIN_USER_ID:
                    await query.edit_message_text("❌ Không có quyền truy cập!")
                    return
                
                user_states[user_id] = {
                    'action': 'set_exchange_rate',
                    'from_currency': 'USD',
                    'to_currency': 'VND'
                }
                
                await query.edit_message_text(
                    "💲 **Cập nhật tỷ giá USD/VND**\n\n"
                    "💰 Nhập tỷ giá mới (VND cho 1 USD):\n"
                    "Ví dụ: 24500 nghĩa là 1 USD = 24,500 VND",
                    parse_mode='Markdown'
                )

            elif data == "set_custom_rate":
                if user_id != ADMIN_USER_ID:
                    await query.edit_message_text("❌ Không có quyền truy cập!")
                    return
                
                await query.edit_message_text(
                    "⚙️ **Tỷ giá tùy chỉnh**\n\n"
                    "Chức năng đang phát triển.\n"
                    "Hiện tại chỉ hỗ trợ TWD/VND và USD/VND.",
                    parse_mode='Markdown',
                    reply_markup=Keyboards.admin_exchange_rate_menu()
                )

            elif data == "view_rates":
                if user_id != ADMIN_USER_ID:
                    await query.edit_message_text("❌ Không có quyền truy cập!")
                    return
                
                # Get current rates from database
                try:
                    rates_text = "📈 **Tỷ giá hiện tại**\n\n"
                    
                    # Get TWD/VND rate
                    twd_rate = await db.get_latest_exchange_rate('TWD', 'VND')
                    if twd_rate:
                        rates_text += f"💱 TWD/VND: {twd_rate['rate']}\n"
                        rates_text += f"📅 Cập nhật: {twd_rate['created_at']}\n\n"
                    else:
                        rates_text += "💱 TWD/VND: Chưa thiết lập\n\n"
                    
                    # Get USD/VND rate  
                    usd_rate = await db.get_latest_exchange_rate('USD', 'VND')
                    if usd_rate:
                        rates_text += f"💲 USD/VND: {usd_rate['rate']}\n"
                        rates_text += f"📅 Cập nhật: {usd_rate['created_at']}\n\n"
                    else:
                        rates_text += "💲 USD/VND: Chưa thiết lập\n\n"
                    
                    rates_text += "💡 Sử dụng các nút bên dưới để cập nhật tỷ giá"
                    
                    await query.edit_message_text(
                        rates_text,
                        parse_mode='Markdown',
                        reply_markup=Keyboards.admin_exchange_rate_menu()
                    )
                    
                except Exception as e:
                    logger.error(f"Error viewing rates: {e}")
                    await query.edit_message_text(
                        "❌ Lỗi khi lấy thông tin tỷ giá!",
                        reply_markup=Keyboards.admin_exchange_rate_menu()
                    )

            elif data == "create_wallet":
                logger.info("Processing create_wallet callback")
                
                # Check existing wallets first
                db_user = await db.get_user_by_tg_id(user_id)
                existing_wallets = await db.get_user_wallets(db_user.id)
                existing_currencies = {wallet.currency for wallet in existing_wallets}
                
                if len(existing_currencies) >= 5:  # Limit to 5 wallets
                    await query.edit_message_text(
                        "⚠️ **Giới hạn ví**\n\n"
                        "Bạn đã tạo tối đa 5 ví. Vui lòng xóa ví cũ nếu muốn tạo ví mới.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.budget_menu()
                    )
                else:
                    await query.edit_message_text(
                        "💰 Tạo ví mới\n\n"
                        "Chọn loại tiền tệ cho ví:",
                        reply_markup=Keyboards.currency_selection_menu(exclude_currencies=existing_currencies)
                    )
                
                
            elif data == "view_wallets" or data == "list_wallets":
                logger.info("Processing view_wallets/list_wallets callback")
                
                # Get database user first
                db_user = await db.get_user_by_tg_id(user_id)
                wallets = await db.get_user_wallets(db_user.id)
                logger.info(f"Found {len(wallets)} wallets for user {db_user.id}")
                
                if not wallets:
                    text = "💰 Bạn chưa có ví nào.\n\nTạo ví đầu tiên để bắt đầu quản lý budget!"
                    reply_markup = Keyboards.budget_menu()
                else:
                    text = "💰 Danh sách ví của bạn:\n\n"
                    for wallet in wallets:
                        balance_decimal = Decimal(wallet.current_balance)
                        balance_text = currency_service.format_amount(balance_decimal, wallet.currency)
                        text += f"• {balance_text}"
                        if wallet.note:
                            text += f" - {wallet.note}"
                        text += "\n"
                    reply_markup = Keyboards.wallet_management_menu()
                
                try:
                    await query.edit_message_text(text, reply_markup=reply_markup)
                except Exception as e:
                    if "Message is not modified" in str(e):
                        logger.warning("Message content is identical, skipping edit")
                        await query.answer("📱 Thông tin đã được cập nhật", show_alert=False)
                    else:
                        raise e

            elif data == "wallet_details":
                logger.info("Processing wallet_details callback")
                
                # Currency flag mapping
                currency_flags = {
                    "TWD": "🇹🇼",  # Taiwan
                    "VND": "🇻🇳",  # Vietnam  
                    "USD": "🇺🇸",  # United States
                    "EUR": "🇪🇺",  # European Union
                    "JPY": "🇯🇵",  # Japan
                    "KRW": "🇰🇷",  # South Korea
                    "CNY": "🇨🇳",  # China
                    "THB": "🇹🇭",  # Thailand
                    "SGD": "🇸🇬",  # Singapore
                    "MYR": "🇲🇾",  # Malaysia
                    "PHP": "🇵🇭",  # Philippines
                    "IDR": "🇮🇩",  # Indonesia
                    "GBP": "🇬🇧",  # United Kingdom
                    "AUD": "🇦🇺",  # Australia
                    "CAD": "🇨🇦",  # Canada
                }
                
                # Get database user first
                db_user = await db.get_user_by_tg_id(user_id)
                wallets = await db.get_user_wallets(db_user.id)
                
                if not wallets:
                    await query.edit_message_text(
                        "💰 Bạn chưa có ví nào.\n\nTạo ví đầu tiên để bắt đầu quản lý budget!",
                        reply_markup=Keyboards.budget_menu()
                    )
                    return
                
                text = "📊 **Tóm tắt tất cả ví**\n\n"
                
                for wallet in wallets:
                    balance_decimal = Decimal(wallet.current_balance)
                    balance_text = currency_service.format_amount(balance_decimal, wallet.currency)
                    
                    # Get currency flag
                    flag = currency_flags.get(wallet.currency, "💳")
                    
                    # Wallet header with flag
                    text += f"{flag} {balance_text}\n"
                    
                    if wallet.note:
                        text += f"📝 Ghi chú: {wallet.note}\n"
                    
                    # Get recent transactions for this wallet
                    try:
                        # Get last 3 transactions for this wallet
                        transactions = await db.get_wallet_transactions(wallet.id, limit=3)
                        if transactions:
                            text += f"📊 **Giao dịch gần đây:**\n"
                            for tx in transactions:
                                amount_decimal = Decimal(tx['amount'])
                                amount_text = currency_service.format_amount(amount_decimal, wallet.currency)
                                # Transaction type icon
                                if amount_decimal > 0:
                                    icon = "💰"  # Income
                                    sign = "+"
                                else:
                                    icon = "💸"  # Expense
                                    sign = ""
                                # Format date
                                try:
                                    if isinstance(tx['created_at'], str):
                                        from datetime import datetime
                                        tx_date = datetime.fromisoformat(tx['created_at'].replace('Z', '+00:00'))
                                        date_str = tx_date.strftime('%d/%m')
                                    else:
                                        date_str = tx['created_at'].strftime('%d/%m')
                                except:
                                    date_str = "N/A"
                                # Transaction description
                                desc = tx['description'] if tx['description'] else "Giao dịch"
                                if len(desc) > 20:
                                    desc = desc[:20] + "..."
                                text += f"  {icon} {sign}{amount_text} - {desc} ({date_str})\n"
                        else:
                            text += f"📊 **Chưa có giao dịch nào**\n"
                    except Exception as e:
                        logger.warning(f"Could not get transactions for wallet {wallet.id}: {e}")
                        text += f"📊 **Chưa có giao dịch nào**\n"
                    
                    text += "\n"
                
                # Add today's expenses section like in summary command
                expenses_today = await db.get_personal_expenses_today(db_user.id)
                if expenses_today:
                    text += "🧾 **Chi tiêu hôm nay:**\n"
                    daily_totals = {}  # Track totals by currency
                    for expense in expenses_today:
                        amount_decimal = Decimal(expense.amount)
                        
                        # Track total by currency
                        if expense.currency not in daily_totals:
                            daily_totals[expense.currency] = Decimal('0')
                        daily_totals[expense.currency] += amount_decimal
                        
                        amount_text = currency_service.format_amount(amount_decimal, expense.currency)
                        
                        # Parse datetime from string if needed and convert to timezone
                        if isinstance(expense.created_at, str):
                            from datetime import datetime
                            created_at = datetime.fromisoformat(expense.created_at.replace('Z', '+00:00'))
                        else:
                            created_at = expense.created_at
                        
                        # Convert to local timezone
                        if created_at.tzinfo is None:
                            created_at = pytz.UTC.localize(created_at).astimezone(TIMEZONE)
                        else:
                            created_at = created_at.astimezone(TIMEZONE)
                        
                        time_str = created_at.strftime('%H:%M')
                        desc = f" - {expense.note}" if expense.note else ""
                        text += f"• {time_str} | {amount_text}{desc}\n"
                    
                    # Show totals by currency with flags
                    text += "\n📊 **Tổng chi hôm nay:**\n"
                    for currency, total in daily_totals.items():
                        total_text = currency_service.format_amount(total, currency)
                        flag = currency_flags.get(currency, "💳")
                        text += f"{flag} {total_text}\n"
                else:
                    text += "✨ **Chưa có chi tiêu nào hôm nay!**"
                
                try:
                    await query.edit_message_text(
                        text, 
                        parse_mode='Markdown',
                        reply_markup=Keyboards.personal_expense_menu()
                    )
                except Exception as e:
                    if "Message is not modified" in str(e):
                        logger.warning("Wallet details message content is identical, skipping edit")
                        await query.answer("📱 Thông tin ví đã được cập nhật", show_alert=False)
                    else:
                        raise e

            elif data == "topup_wallet":
                logger.info("Processing topup_wallet callback")
                
                # Get database user first
                db_user = await db.get_user_by_tg_id(user_id)
                wallets = await db.get_user_wallets(db_user.id)
                if not wallets:
                    await query.edit_message_text(
                        "❌ Bạn cần tạo ví trước khi nạp tiền.\n\n"
                        "Vui lòng tạo ví đầu tiên:",
                        reply_markup=Keyboards.budget_menu()
                    )
                else:
                    await query.edit_message_text(
                        "💳 Nạp tiền vào ví\n\n"
                        "Chọn ví để nạp tiền:",
                        reply_markup=Keyboards.wallet_selection_for_topup(wallets)
                    )

            elif data == "decrease_wallet":
                logger.info("Processing decrease_wallet callback")
                
                # Get database user first
                db_user = await db.get_user_by_tg_id(user_id)
                wallets = await db.get_user_wallets(db_user.id)
                if not wallets:
                    await query.edit_message_text(
                        "❌ Bạn cần tạo ví trước khi giảm tiền.\n\n"
                        "Vui lòng tạo ví đầu tiên:",
                        reply_markup=Keyboards.budget_menu()
                    )
                else:
                    await query.edit_message_text(
                        "➖ Giảm tiền trong ví\n\n"
                        "Chọn ví để giảm tiền:",
                        reply_markup=Keyboards.wallet_selection_for_decrease(wallets)
                    )

            elif data == "delete_wallet":
                logger.info("Processing delete_wallet callback")
                
                # Get database user first
                db_user = await db.get_user_by_tg_id(user_id)
                wallets = await db.get_user_wallets(db_user.id)
                if not wallets:
                    await query.edit_message_text(
                        "❌ Bạn không có ví nào để xóa.\n\n"
                        "Tạo ví đầu tiên:",
                        reply_markup=Keyboards.budget_menu()
                    )
                else:
                    await query.edit_message_text(
                        "🗑️ Xóa ví\n\n"
                        "⚠️ Cảnh báo: Hành động này không thể hoàn tác!\n"
                        "Chọn ví để xóa:",
                        reply_markup=Keyboards.wallet_selection_for_delete(wallets)
                    )

            elif data == "add_expense":
                logger.info("Processing add_expense callback")
                
                # Get database user first
                db_user = await db.get_user_by_tg_id(user_id)
                wallets = await db.get_user_wallets(db_user.id)
                if not wallets:
                    await query.edit_message_text(
                        "❌ Bạn cần tạo ví trước khi thêm chi tiêu.\n\n"
                        "Vui lòng tạo ví đầu tiên:",
                        reply_markup=Keyboards.budget_menu()
                    )
                else:
                    await query.edit_message_text(
                        "🧾 Thêm chi tiêu cá nhân\n\n"
                        "Chọn ví để ghi nhận chi tiêu:",
                        reply_markup=Keyboards.wallet_selection_menu(wallets)
                    )

            elif data.startswith("currency_"):
                # Handle currency selection for wallet creation
                currency = data.replace("currency_", "")
                logger.info(f"Processing currency selection: {currency}")
                
                # Store currency choice in user state
                if user_id not in user_states:
                    user_states[user_id] = {}
                user_states[user_id]['action'] = 'create_wallet_amount'
                user_states[user_id]['currency'] = currency
                logger.info(f"Set user state for wallet creation: {user_states[user_id]}")
                
                await query.edit_message_text(
                    f"💰 Tạo ví {currency}\n\n"
                    f"Nhập số tiền ban đầu cho ví (VD: 10000):",
                    reply_markup=Keyboards.back_to_budget_menu()
                )

            elif data.startswith("undo_expense_"):
                # Handle deleting specific personal expense (no time limit)
                expense_id = int(data.replace("undo_expense_", ""))
                logger.info(f"Processing delete personal expense: {expense_id}")
                
                # Get user from database
                db_user = await db.get_user_by_tg_id(user_id)
                if not db_user:
                    await query.edit_message_text("❌ Lỗi: Không tìm thấy thông tin user!")
                    return
                
                # Hard delete
                success = await db.delete_personal_expense(expense_id, db_user.id)
                if success:
                    await query.edit_message_text(
                        "✅ **Đã xóa chi tiêu thành công!**",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.back_to_expense_menu()
                    )
                else:
                    await query.edit_message_text(
                        "❌ **Không thể xóa chi tiêu**",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.back_to_expense_menu()
                    )

            elif data == "undo_group_expense_menu":
                logger.info("Processing undo group expense menu callback")
                
                # Get user's most recent group expenses that can be undone (from all group chats)
                db_user = await db.get_user_by_tg_id(user_id)
                
                # Get all user's group expenses from all trips (last 30 days)
                all_group_expenses = []
                
                # Get user's trips
                user_trips = await db.get_user_trips(db_user.id)
                
                if not user_trips:
                    await query.edit_message_text(
                        "🗑️ **Hoàn tác giao dịch**\n\n"
                        "❌ Bạn chưa tham gia group chat nào.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.back_to_main_menu()
                    )
                    return
                
                # Collect all group expenses from all group chats
                for trip in user_trips:
                    trip_expenses = await db.get_group_expenses_by_user(db_user.id, trip.id, 30)
                    for expense in trip_expenses:
                        all_group_expenses.append(expense)
                
                # Sort by creation time (newest first)
                all_group_expenses.sort(key=lambda x: x.created_at, reverse=True)
                
                if not all_group_expenses:
                    await query.edit_message_text(
                        "🗑️ **Hoàn tác giao dịch**\n\n"
                        "❌ Không có giao dịch nào để hoàn tác.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.back_to_main_menu()
                    )
                    return
                
                                    # Show list of undoable group expenses
                    undo_text = "🗑️ **Hoàn tác giao dịch**\n\n"
                    undo_text += "Chọn giao dịch muốn hoàn tác:\n\n"
                    
                    keyboard = []
                    for expense in all_group_expenses[:8]:  # Show max 8 recent expenses
                        formatted_amount = currency_service.format_amount(expense.amount, expense.currency)
                        description = expense.description if expense.description else "Giao dịch"
                        if len(description) > 15:
                            description = description[:12] + "..."
                    
                    # Check if expense can still be undone
                    can_undo = True
                    if hasattr(expense, 'undo_until') and expense.undo_until:
                        try:
                            undo_until = expense.undo_until
                            if isinstance(undo_until, str):
                                undo_until = datetime.fromisoformat(undo_until)
                            can_undo = undo_until > datetime.now()
                        except:
                            can_undo = True
                    
                    button_text = f"{formatted_amount} - {description}"
                    if not can_undo:
                        button_text += " ⏰"
                    
                    keyboard.append([InlineKeyboardButton(
                        button_text, 
                        callback_data=f"undo_group_expense_{expense.id}"
                    )])
                
                keyboard.append([InlineKeyboardButton("🔙 Quay lại", callback_data="main_menu")])
                
                await query.edit_message_text(
                    undo_text,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            elif data.startswith("undo_group_expense_"):
                # Handle deleting specific group expense
                expense_id = int(data.replace("undo_group_expense_", ""))
                logger.info(f"Processing delete group expense: {expense_id}")
                
                # Get user from database
                db_user = await db.get_user_by_tg_id(user_id)
                if not db_user:
                    await query.edit_message_text("❌ Lỗi: Không tìm thấy thông tin user!")
                    return
                
                # Check if expense can be undone
                try:
                    # Get expense details
                    expense = await db.get_group_expense_by_id(expense_id)
                    if not expense:
                        await query.edit_message_text(
                            "❌ **Không tìm thấy chi tiêu**",
                            parse_mode='Markdown',
                            reply_markup=Keyboards.back_to_main_menu()
                        )
                        return
                    
                    # Check if user is the payer
                    if expense.payer_id != db_user.id:
                        await query.edit_message_text(
                            "❌ **Bạn không thể hoàn tác chi tiêu này**\n\n"
                            "Chỉ người chi tiêu mới có thể hoàn tác.",
                            parse_mode='Markdown',
                            reply_markup=Keyboards.back_to_main_menu()
                        )
                        return
                    
                    # Check time limit
                    can_undo = True
                    if hasattr(expense, 'undo_until') and expense.undo_until:
                        try:
                            undo_until = expense.undo_until
                            if isinstance(undo_until, str):
                                undo_until = datetime.fromisoformat(undo_until)
                            can_undo = undo_until > datetime.now()
                        except:
                            can_undo = True
                    
                    if not can_undo:
                        await query.edit_message_text(
                            "⏰ **Không thể hoàn tác chi tiêu này**\n\n"
                            "Đã quá thời gian cho phép hoàn tác.",
                            parse_mode='Markdown',
                            reply_markup=Keyboards.back_to_main_menu()
                        )
                        return
                    
                    # Show confirmation dialog
                    formatted_amount = currency_service.format_amount(expense.amount, expense.currency)
                    description = expense.description if expense.description else "Giao dịch"
                    
                    confirm_text = f"🗑️ **Xác nhận hoàn tác giao dịch**\n\n"
                    confirm_text += f"💰 **Số tiền**: {formatted_amount}\n"
                    confirm_text += f"📝 **Mô tả**: {description}\n"
                    confirm_text += f"⏰ **Thời gian**: {expense.created_at[:19] if expense.created_at else 'N/A'}\n\n"
                    confirm_text += "⚠️ **Cảnh báo**:\n"
                    confirm_text += "• Hành động này KHÔNG THỂ hoàn tác\n"
                    confirm_text += "• Sẽ ảnh hưởng đến tính toán nợ của nhóm\n"
                    confirm_text += "• Tất cả dữ liệu liên quan sẽ bị xóa vĩnh viễn\n\n"
                    confirm_text += "Bạn có chắc chắn muốn hoàn tác?"
                    
                    keyboard = [
                        [
                            InlineKeyboardButton("✅ Xác nhận hoàn tác", callback_data=f"confirm_undo_group_{expense_id}"),
                            InlineKeyboardButton("❌ Hủy bỏ", callback_data="undo_group_expense_menu")
                        ]
                    ]
                    
                    await query.edit_message_text(
                        confirm_text,
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                
                except Exception as e:
                    logger.error(f"Error undoing group expense: {e}")
                    await query.edit_message_text(
                        "❌ **Có lỗi xảy ra**\n\n"
                        "Vui lòng thử lại sau.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.back_to_main_menu()
                    )

            elif data.startswith("confirm_undo_group_"):
                # Handle confirming group expense undo
                expense_id = int(data.replace("confirm_undo_group_", ""))
                logger.info(f"Confirming undo group expense: {expense_id}")
                
                # Get user from database
                db_user = await db.get_user_by_tg_id(user_id)
                if not db_user:
                    await query.edit_message_text("❌ Lỗi: Không tìm thấy thông tin user!")
                    return
                
                try:
                    # Hard delete the expense
                    success = await db.delete_group_expense(expense_id, db_user.id)
                    if success:
                        await query.edit_message_text(
                            "✅ **Đã hoàn tác giao dịch thành công!**\n\n"
                            "⚠️ **Lưu ý**: Việc hoàn tác có thể ảnh hưởng đến tính toán nợ của group.",
                            parse_mode='Markdown',
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("🔙 Quay lại", callback_data="main_menu")
                            ]])
                        )
                    else:
                        await query.edit_message_text(
                            "❌ **Không thể hoàn tác giao dịch**\n\n"
                            "Có lỗi xảy ra khi hoàn tác. Vui lòng thử lại.",
                            parse_mode='Markdown',
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("🔙 Quay lại", callback_data="main_menu")
                            ]])
                        )
                        
                except Exception as e:
                    logger.error(f"Error confirming undo group expense: {e}")
                    await query.edit_message_text(
                        "❌ **Có lỗi xảy ra**\n\n"
                        "Vui lòng thử lại sau.",
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 Quay lại", callback_data="main_menu")
                        ]])
                    )

            elif data.startswith("decrease_"):
                # Handle decrease wallet selection
                wallet_id = int(data.replace("decrease_", ""))
                logger.info(f"Processing decrease for wallet: {wallet_id}")
                
                # Store wallet choice in user state
                if user_id not in user_states:
                    user_states[user_id] = user_states.get(user_id, {})
                user_states[user_id]['action'] = 'decrease_amount'
                user_states[user_id]['wallet_id'] = wallet_id
                
                wallet = await db.get_wallet(wallet_id)
                balance_decimal = Decimal(wallet.current_balance)
                balance_text = currency_service.format_amount(balance_decimal, wallet.currency)
                
                await query.edit_message_text(
                    f"➖ **Giảm tiền trong ví {wallet.currency}**\n\n"
                    f"💵 Số dư hiện tại: {balance_text}\n\n"
                    f"Nhập số tiền muốn giảm (VD: 500):",
                    parse_mode='Markdown',
                    reply_markup=Keyboards.back_to_budget_menu()
                )

            elif data.startswith("delete_"):
                # Handle delete wallet selection
                wallet_id = int(data.replace("delete_", ""))
                logger.info(f"Processing delete for wallet: {wallet_id}")
                
                wallet = await db.get_wallet(wallet_id)
                balance_decimal = Decimal(wallet.current_balance)
                balance_text = currency_service.format_amount(balance_decimal, wallet.currency)
                
                await query.edit_message_text(
                    f"🗑️ **Xác nhận xóa ví**\n\n"
                    f"💰 Ví: {wallet.currency}\n"
                    f"💵 Số dư: {balance_text}\n\n"
                    f"⚠️ **Cảnh báo**: Hành động này không thể hoàn tác!\n"
                    f"Bạn có chắc chắn muốn xóa ví này?",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ Xác nhận xóa", callback_data=f"confirm_delete_{wallet_id}"),
                            InlineKeyboardButton("❌ Hủy bỏ", callback_data="budget_menu")
                        ]
                    ])
                )

            elif data.startswith("confirm_delete_"):
                # Handle confirm delete wallet
                wallet_id = int(data.replace("confirm_delete_", ""))
                logger.info(f"Confirming delete for wallet: {wallet_id}")
                
                try:
                    success = await db.delete_wallet(wallet_id)
                    if success:
                        await query.edit_message_text(
                            "✅ **Xóa ví thành công!**\n\n"
                            "Ví đã được xóa khỏi hệ thống.",
                            parse_mode='Markdown',
                            reply_markup=Keyboards.budget_menu()
                        )
                    else:
                        await query.edit_message_text(
                            "❌ **Không thể xóa ví**\n\n"
                            "Có lỗi xảy ra khi xóa ví. Vui lòng thử lại.",
                            parse_mode='Markdown',
                            reply_markup=Keyboards.budget_menu()
                        )
                except Exception as e:
                    logger.error(f"Error deleting wallet: {e}")
                    await query.edit_message_text(
                        "❌ **Lỗi hệ thống**\n\n"
                        "Đã xảy ra lỗi khi xóa ví. Vui lòng thử lại sau.",
                        parse_mode='Markdown',
                        reply_markup=Keyboards.budget_menu()
                    )

            elif data.startswith("wallet_"):
                # Handle wallet selection for expenses
                wallet_id = int(data.replace("wallet_", ""))
                logger.info(f"Processing wallet selection: {wallet_id}")
                
                # Store wallet choice in user state  
                if user_id not in user_states:
                    user_states[user_id] = {}
                user_states[user_id]['action'] = 'add_expense'
                user_states[user_id]['wallet_id'] = wallet_id
                
                wallet = await db.get_wallet(wallet_id)
                balance_decimal = Decimal(wallet.current_balance)
                balance_text = currency_service.format_amount(balance_decimal, wallet.currency)
                
                await query.edit_message_text(
                    f"🧾 Thêm chi tiêu\n\n"
                    f"💰 Ví: {wallet.currency}\n"
                    f"💵 Số dư hiện tại: {balance_text}\n\n"
                    f"**Nhập số tiền và lý do chi tiêu:**\n"
                    f"VD: 120 ăn sáng\n"
                    f"VD: 50.5 cafe\n"
                    f"VD: 1000 mua đồ\n"
                    f"VD: 25 (chỉ số tiền)",
                    parse_mode='Markdown',
                    reply_markup=Keyboards.back_to_expense_menu()
                )

            elif data.startswith("pay_cash_"):
                # Parse callback data
                parts = data.split("_")
                group_id = int(parts[2])
                creditor_id = int(parts[3])
                amount = Decimal(parts[4])
                currency = parts[5]
                debtor_id = query.from_user.id
                # Gửi thông báo cho B
                creditor_user = await db.get_user_by_tg_id(creditor_id)
                debtor_name = await get_user_name(context.application, debtor_id)
                creditor_name = await get_user_name(context.application, creditor_id)
                notify_text = f"✅ {debtor_name} đã trả nợ {creditor_name} {amount} {currency} bằng tiền mặt."
                await context.bot.send_message(chat_id=creditor_user.tg_user_id, text=notify_text)
                await query.edit_message_text("Đã xác nhận trả tiền mặt!", reply_markup=Keyboards.main_dm_menu())

            elif data.startswith("pay_qr_"):
                # Parse callback data
                parts = data.split("_")
                group_id = int(parts[2])
                creditor_id = int(parts[3])
                vnd_amount = Decimal(parts[4])
                debtor_id = query.from_user.id
                creditor_user = await db.get_user_by_tg_id(creditor_id)
                debtor_name = await get_user_name(context.application, debtor_id)
                creditor_name = await get_user_name(context.application, creditor_id)
                # Tạo mã QR
                qr_url = await vietqr_service.generate_payment_qr(creditor_user.id, vnd_amount, f"No {creditor_name}", "VND")
                text = f"📱 **Mã QR chuyển khoản VND**\n\nSố tiền: {vnd_amount:,.0f} ₫\n\nQuét mã QR để chuyển khoản cho {creditor_name}. Sau khi chuyển, nhấn 'Quay về menu chính'."
                keyboard = [[InlineKeyboardButton("🔙 Quay về menu chính", callback_data=f"qr_back_{group_id}_{creditor_id}_{vnd_amount}")]]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

            elif data.startswith("qr_back_"):
                # Khi người dùng quay về menu chính sau khi chuyển khoản
                parts = data.split("_")
                group_id = int(parts[2])
                creditor_id = int(parts[3])
                vnd_amount = Decimal(parts[4])
                debtor_id = query.from_user.id
                creditor_user = await db.get_user_by_tg_id(creditor_id)
                debtor_name = await get_user_name(context.application, debtor_id)
                creditor_name = await get_user_name(context.application, creditor_id)
                notify_text = f"✅ {debtor_name} đã chuyển khoản trả nợ {creditor_name} (quy đổi VND): {vnd_amount:,.0f} ₫."
                await context.bot.send_message(chat_id=creditor_user.tg_user_id, text=notify_text)
                await query.edit_message_text("Đã xác nhận chuyển khoản!", reply_markup=Keyboards.main_dm_menu())
                # Do nothing for disabled buttons
                await query.answer("Tùy chọn này không khả dụng", show_alert=False)

            elif data == "help_menu":
                await query.edit_message_text(
                    "📚 **Trung Tâm Trợ Giúp**\n\n"
                    "🎯 Chọn chủ đề bạn muốn tìm hiểu:\n"
                    "👇 Nhấn vào các nút bên dưới",
                    parse_mode='Markdown',
                    reply_markup=Keyboards.help_menu()
                )

            elif data == "help_wallet":
                text = (
                    "💰 **Hướng dẫn quản lý ví**\n\n"
                    "**Tạo ví mới:**\n"
                    "• Chọn 'Tạo ví mới' → chọn tiền tệ → nhập số dư ban đầu\n"
                    "• Hỗ trợ: TWD, VND, USD, EUR, GBP, JPY, KRW, CNY\n\n"
                    "**Nạp tiền:**\n"
                    "• Chọn 'Nạp tiền' → chọn ví → nhập số tiền cần nạp\n"
                    "• Có thể nạp từ số âm lên số dương\n\n"
                    "**Giảm tiền:**\n" 
                    "• Chọn 'Giảm tiền' → chọn ví → nhập số tiền cần trừ\n"
                    "• Có thể trừ xuống số âm (âm quỹ luôn được phép)\n\n"
                    "**Chuyển tiền:**\n"
                    "• Chuyển giữa các ví của bạn với tỷ giá tự động\n"
                    "• Ví dụ: TWD → VND theo tỷ giá hiện tại\n\n"
                    "**Xóa ví:**\n"
                    "• Chọn 'Xóa ví' → chọn ví muốn xóa → xác nhận\n"
                    "• Chỉ xóa được ví có số dư = 0\n\n"
                    "**Lệnh nhanh:**\n"
                    "• `/wallets` - Mở menu quản lý ví ngay lập tức"
                )
                await query.edit_message_text(text, parse_mode='Markdown', reply_markup=Keyboards.back_to_help())

            elif data == "help_expense":
                text = (
                    "🧾 **Hướng dẫn chi tiêu**\n\n"
                    "**Chi tiêu cá nhân:**\n"
                    "• Chọn 'Chi tiêu cá nhân' → 'Thêm chi tiêu' → chọn ví\n"
                    "• Nhập: `số tiền + mô tả` (VD: `120 ăn sáng`)\n"
                    "• Hoặc chỉ số tiền: `120`\n"
                    "• ✅ **Có thể chi khi ví âm** - không cần lo thiếu tiền\n\n"
                    "**Chi tiêu nhóm:**\n"
                    "• Trong group: `/add` → chọn tiền tệ → nhập chi tiêu\n"
                    "• Bot tự động chia đều cho thành viên tham gia\n"
                    "• Tự động trừ tiền từ ví phù hợp nhất\n\n"
                    "**Xem lịch sử:**\n"
                    "• Chọn 'Lịch sử (7 ngày)' để xem chi tiêu gần đây\n\n"
                    "**Hoàn tác (24 giờ):**\n"
                    "• Chọn 'Hoàn tác' để hủy chi tiêu trong vòng 1 ngày\n"
                    "• Áp dụng cho cả chi tiêu cá nhân và nhóm\n\n"
                    "**Lệnh nhanh:**\n"
                    "• `/add` - Thêm chi tiêu (cá nhân trong DM, nhóm trong group)\n"
                    "• `/undo` - Hoàn tác chi tiêu cuối"
                )
                await query.edit_message_text(text, parse_mode='Markdown', reply_markup=Keyboards.back_to_help())

            elif data == "help_group":
                text = (
                    "👥 **Hướng dẫn chức năng nhóm**\n\n"
                    "**Tạo chuyến đi:**\n"
                    "• Trong group: `/newtrip <tên chuyến đi>`\n"
                    "• Bot tạo mã tham gia 6 ký tự\n"
                    "• Chia sẻ mã để mọi người join\n\n"
                    "**Tham gia chuyến đi:**\n"
                    "• `/join <mã>` để tham gia\n"
                    "• Tự động được thêm vào danh sách thành viên\n\n"
                    "**Chi tiêu nhóm:**\n"
                    "• `/add` trong group → chọn tiền tệ → nhập chi tiêu\n"
                    "• Bot tự động chia đều cho tất cả thành viên\n"
                    "• Tự động trừ tiền từ ví của người chi\n"
                    "• Tự động tạo nợ cho các thành viên khác\n\n"
                    "**Thanh toán nợ:**\n"
                    "• `/settle` để xem tổng quan nợ nhóm\n"
                    "• Bot tối ưu hóa các khoản nợ (A nợ B, B nợ C → A nợ C)\n"
                    "• Nhận mã QR tự động để chuyển khoản VND\n"
                    "• Nhấn 'Đã chuyển' khi hoàn tất\n\n"
                    "**Hoàn tác nhóm:**\n"
                    "• `/undo` trong group để hủy chi tiêu cuối (24h)\n"
                    "• Chỉ người tạo expense mới được hoàn tác\n\n"
                    "**Thông báo tự động:**\n"
                    "• 10h sáng hàng ngày: Nhắc nhở nợ qua tin nhắn riêng\n"
                    "• Bao gồm thông tin STK và mã QR thanh toán"
                )
                await query.edit_message_text(text, parse_mode='Markdown', reply_markup=Keyboards.back_to_help())

            elif data == "help_settings":
                text = (
                    "⚙️ **Hướng dẫn cài đặt**\n\n"
                    "**Tài khoản ngân hàng:**\n"
                    "• Quản lý thông tin STK để nhận chuyển khoản\n"
                    "• Tự động tạo mã QR cho việc thanh toán\n\n"
                    "**Cài đặt thanh toán:**\n"
                    "• Thiết lập tiền tệ ưa thích (TWD, VND, USD, EUR...)\n"
                    "• Dùng cho ví mới và quy đổi tiền tệ\n\n"
                    "**Tự động hóa:**\n"
                    "• ✅ **Cho phép âm quỹ:** Luôn bật - có thể chi khi thiếu tiền\n"
                    "• ✅ **Tự trừ share nhóm:** Luôn bật - tự động trừ khi chia tiền\n\n"
                    "**Lệnh nhanh:**\n"
                    "• `/settings` - Mở cài đặt ngay\n"
                    "• `/register_bank` - Đăng ký ngân hàng"
                )
                await query.edit_message_text(text, parse_mode='Markdown', reply_markup=Keyboards.back_to_help())

            elif data == "help_commands":
                text = (
                    "⌨️ **Danh sách lệnh**\n\n"
                    "**Lệnh cá nhân (DM):**\n"
                    "• `/start` - Bắt đầu & đăng ký 🚀\n"
                    "• `/help` - Trợ giúp ❓\n"
                    "• `/wallets` - Quản lý ví tiền 💰\n"
                    "• `/add` - Thêm chi tiêu cá nhân 🧾\n"
                    "• `/undo` - Hoàn tác chi tiêu (24h) ↩️\n"
                    "• `/history` - Lịch sử chi tiêu 📊\n"
                    "• `/settings` - Cài đặt tài khoản ⚙️\n"
                    "• `/rates` - Xem tỷ giá hiện tại 💱\n\n"
                    "**Lệnh nhóm:**\n"
                    "• `/newtrip <tên>` - Tạo chuyến đi mới ✈️\n"
                    "• `/join <mã>` - Tham gia chuyến đi 🎫\n"
                    "• `/add` - Chi tiêu nhóm & chia tiền 👥\n"
                    "• `/undo` - Hoàn tác chi tiêu nhóm ↩️\n"
                    "• `/settle` - Tính toán & thanh toán nợ ✅\n"
                    "• `/rates` - Xem tỷ giá (công khai) 💱\n\n"
                    "**Lệnh admin:**\n"
                    "• `/setrates` - Thiết lập tỷ giá 🔧\n\n"
                    "**Mẹo sử dụng:**\n"
                    "• Lệnh cá nhân chỉ hoạt động trong DM\n"
                    "• Lệnh nhóm chỉ hoạt động trong group\n"
                    "• Bot tự động xử lý âm quỹ và chia tiền"
                )
                await query.edit_message_text(text, parse_mode='Markdown', reply_markup=Keyboards.back_to_help())

            elif data.startswith("group_currency_"):
                # Group expense currency selection
                currency = data.replace("group_currency_", "")
                user_id = query.from_user.id
                
                if user_id in group_expense_states:
                    group_expense_states[user_id]['currency'] = currency
                    group_expense_states[user_id]['step'] = 'amount'
                    
                    await query.edit_message_text(
                        f"💰 Chi tiêu nhóm ({currency})\n\n"
                        "Nhập số tiền và mô tả:\n"
                        "📝 Ví dụ: 120 ăn sáng\n"
                        "📝 Hoặc chỉ: 120\n\n"
                        "➡️ Nhập thông tin chi tiêu:"
                    )

            elif data.startswith("select_payer_"):
                # Handle payer selection
                payer_id = int(data.replace("select_payer_", ""))
                user_id = query.from_user.id
                
                if user_id in group_expense_states:
                    group_expense_states[user_id]['payer_id'] = payer_id
                    group_expense_states[user_id]['step'] = 'participants'
                    group_expense_states[user_id]['selected_participants'] = []
                    
                    # Get payer name
                    try:
                        payer_member = await context.bot.get_chat_member(group_expense_states[user_id]['group_id'], payer_id)
                        payer_name = payer_member.user.first_name
                    except:
                        payer_name = "Người đó"
                    
                    # Get chat members for participant selection  
                    try:
                        # Try to get member count to determine strategy
                        chat_member_count = await context.bot.get_chat_member_count(group_expense_states[user_id]['group_id'])
                        if chat_member_count <= 200:  # Small group
                            chat_members = await context.bot.get_chat_administrators(group_expense_states[user_id]['group_id'])
                        else:
                            # For large groups, use administrators as fallback  
                            chat_members = await context.bot.get_chat_administrators(group_expense_states[user_id]['group_id'])
                    except:
                        # Fallback to administrators only
                        chat_members = await context.bot.get_chat_administrators(group_expense_states[user_id]['group_id'])
                    
                    amount_text = currency_service.format_amount(group_expense_states[user_id]['amount'], group_expense_states[user_id]['currency'])
                    desc_text = f" - {group_expense_states[user_id]['description']}" if group_expense_states[user_id].get('description') else ""
                    
                    await query.edit_message_text(
                        f"💰 Chi tiêu: {amount_text}{desc_text}\n"
                        f"👤 Người trả: {payer_name}\n\n"
                        "👥 **Chọn người tham gia chia tiền:**\n"
                        "(Bao gồm cả người trả tiền)",
                        reply_markup=Keyboards.group_participant_selection(chat_members, [])
                    )

            elif data.startswith("toggle_participant_"):
                # Toggle participant selection
                participant_id = int(data.replace("toggle_participant_", ""))
                user_id = query.from_user.id
                
                if user_id in group_expense_states and 'selected_participants' in group_expense_states[user_id]:
                    selected = group_expense_states[user_id]['selected_participants']
                    if participant_id in selected:
                        selected.remove(participant_id)
                    else:
                        selected.append(participant_id)
                    
                    # Update keyboard with new selection
                    try:
                        chat_member_count = await context.bot.get_chat_member_count(group_expense_states[user_id]['group_id'])
                        if chat_member_count <= 200:
                            chat_members = await context.bot.get_chat_administrators(group_expense_states[user_id]['group_id'])
                        else:
                            chat_members = await context.bot.get_chat_administrators(group_expense_states[user_id]['group_id'])
                    except:
                        chat_members = await context.bot.get_chat_administrators(group_expense_states[user_id]['group_id'])
                    await query.edit_message_reply_markup(
                        reply_markup=Keyboards.group_participant_selection(chat_members, selected)
                    )

            elif data == "select_all_participants":
                # Select all participants
                user_id = query.from_user.id
                if user_id in group_expense_states:
                    try:
                        chat_member_count = await context.bot.get_chat_member_count(group_expense_states[user_id]['group_id'])
                        if chat_member_count <= 200:
                            chat_members = await context.bot.get_chat_administrators(group_expense_states[user_id]['group_id'])
                        else:
                            chat_members = await context.bot.get_chat_administrators(group_expense_states[user_id]['group_id'])
                    except:
                        chat_members = await context.bot.get_chat_administrators(group_expense_states[user_id]['group_id'])
                    all_user_ids = [m.user.id for m in chat_members if not m.user.is_bot and m.user.id != user_id]
                    group_expense_states[user_id]['selected_participants'] = all_user_ids
                    
                    await query.edit_message_reply_markup(
                        reply_markup=Keyboards.group_participant_selection(chat_members, all_user_ids)
                    )

            elif data == "deselect_all_participants":
                # Deselect all participants
                user_id = query.from_user.id
                if user_id in group_expense_states:
                    group_expense_states[user_id]['selected_participants'] = []
                    chat_members = await context.bot.get_chat_administrators(group_expense_states[user_id]['group_id'])
                    
                    await query.edit_message_reply_markup(
                        reply_markup=Keyboards.group_participant_selection(chat_members, [])
                    )

            elif data == "split_equally":
                # Split expense equally among selected participants
                user_id = query.from_user.id
                if user_id in group_expense_states:
                    state = group_expense_states[user_id]
                    selected = state.get('selected_participants', [])
                    
                    if not selected:
                        await query.answer("❌ Chưa chọn người tham gia!", show_alert=True)
                        return
                    
                    # Create group expense
                    expense_id = await db.create_group_expense(
                        state['group_id'],
                        state['payer_id'], 
                        state['amount'],
                        state['currency'],
                        state.get('description')
                    )
                    
                    # Calculate equal shares
                    share_amount = state['amount'] / len(selected)
                    participants = [(user_id, share_amount) for user_id in selected]
                    await db.add_expense_participants(expense_id, participants)
                    
                    # Get payer name properly
                    try:
                        payer_member = await context.bot.get_chat_member(state['group_id'], state['payer_id'])
                        payer_name = payer_member.user.first_name
                    except:
                        payer_name = "Ai đó"
                    
                    # Send notifications to participants
                    amount_text = currency_service.format_amount(state['amount'], state['currency'])
                    description = state.get('description', 'Chi tiêu nhóm')
                    share_text = currency_service.format_amount(share_amount, state['currency'])
                    
                    for participant_id in selected:
                        try:
                            # Skip sending notification to the payer
                            if participant_id == state['payer_id']:
                                continue
                                
                            await context.bot.send_message(
                                participant_id,
                                f"💰 **Bạn vừa tiêu {share_text} cho {description}**\n"
                                f"từ ({payer_name})\n\n"
                                f"💵 **Tổng tiền:** {amount_text}\n"
                                f"� **Chia cho:** {len(selected)} người\n\n"
                                f"� **Chọn cách thanh toán:**",
                                parse_mode='Markdown',
                                reply_markup=Keyboards.payment_options(expense_id, participant_id)
                            )
                        except Exception as e:
                            logger.warning(f"Could not send DM to user {participant_id}: {e}")
                    
                    # Update group debt tracking
                    for participant_id in selected:
                        await db.update_group_debts(
                            state['group_id'],
                            participant_id,  # debtor
                            state['payer_id'],  # creditor
                            share_amount,
                            state['currency']
                        )
                    
                    await query.edit_message_text(
                        f"✅ Đã tạo chi tiêu nhóm!\n\n"
                        f"🧾 {description}\n"
                        f"💵 Tổng: {amount_text}\n"
                        f"👥 Người tham gia: {len(selected)}\n"
                        f"📝 Mỗi người: {share_text}\n\n"
                        f"Đã gửi thông báo đến từng người! 📱"
                    )
                    
                    # Clear state
                    del group_expense_states[user_id]

            elif data.startswith("undo_personal_expense_"):
                # Handle personal expense delete (no time limit)
                expense_id = int(data.replace("undo_personal_expense_", ""))
                user_id = query.from_user.id
                
                # Get user from database
                db_user = await db.get_user_by_tg_id(user_id)
                if not db_user:
                    await query.edit_message_text("❌ Lỗi: Không tìm thấy thông tin user!")
                    return
                
                success = await db.delete_personal_expense(expense_id, db_user.id)
                if success:
                    await query.edit_message_text(
                        "✅ **Đã xóa chi tiêu thành công!**"
                    )
                else:
                    await query.edit_message_text(
                        "❌ **Không thể xóa chi tiêu**"
                    )

            elif data.startswith("undo_group_expense_"):
                # Handle group expense delete (no time limit)
                expense_id = int(data.replace("undo_group_expense_", ""))
                user_id = query.from_user.id
                
                # Get user from database
                db_user = await db.get_user_by_tg_id(user_id)
                if not db_user:
                    await query.edit_message_text("❌ Lỗi: Không tìm thấy thông tin user!")
                    return
                
                success = await db.delete_group_expense(expense_id, db_user.id)
                if success:
                    await query.edit_message_text(
                        "✅ **Đã xóa chi tiêu nhóm thành công!**"
                    )
                else:
                    await query.edit_message_text(
                        "❌ **Không thể xóa chi tiêu nhóm**"
                    )

            elif data.startswith("pay_now_"):
                # Mark as paid immediately
                expense_id = int(data.replace("pay_now_", ""))
                user_id = query.from_user.id
                
                await db.mark_participant_paid(expense_id, user_id)
                
                await query.edit_message_text(
                    "✅ Cảm ơn! Đã ghi nhận bạn đã thanh toán.\n\n"
                    "Chi tiêu này đã được đánh dấu là đã trả."
                )

            elif data.startswith("pay_later_"):
                # Mark for end-of-day reminder
                expense_id = int(data.replace("pay_later_", ""))
                
                await query.edit_message_text(
                    "⏰ Được rồi! Tôi sẽ nhắc bạn vào cuối ngày.\n\n"
                    "Bạn sẽ nhận được thông báo tính nợ tối ưu."
                )

            elif data.startswith("paid_now_"):
                # Handle "Trả rồi" button
                parts = data.replace("paid_now_", "").split("_")
                expense_id = int(parts[0])
                participant_id = int(parts[1])
                
                # Mark as paid in database
                await db.mark_participant_paid(expense_id, participant_id, 'paid_now')
                
                # Get expense details for notification
                expense = await db.get_expense_by_id(expense_id)
                if expense:
                    # Notify the payer
                    try:
                        participant_name = query.from_user.first_name
                        await context.bot.send_message(
                            expense['payer_user_id'],
                            f"💰 **{participant_name}** đã trả tiền cho chi tiêu:\n"
                            f"**{expense.get('description', 'Chi tiêu nhóm')}** rồi nhé! ✅",
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.warning(f"Could not notify payer: {e}")
                
                await query.edit_message_text(
                    "✅ **Đã ghi nhận bạn đã thanh toán!**\n\n"
                    "Người trả tiền đã được thông báo. 📱"
                )

            elif data.startswith("pay_end_day_"):
                # Handle "Cuối ngày" button  
                parts = data.replace("pay_end_day_", "").split("_")
                expense_id = int(parts[0])
                participant_id = int(parts[1])
                
                # Mark for end-of-day reminder
                await db.mark_participant_paid(expense_id, participant_id, 'end_of_day')
                
                await query.edit_message_text(
                    "⏰ **Được rồi!** \n\n"
                    "Tôi sẽ cộng vào tổng kết cuối ngày để tính nợ tối ưu."
                )

            elif data == "cancel_group_expense":
                # Cancel group expense creation
                user_id = query.from_user.id
                if user_id in group_expense_states:
                    del group_expense_states[user_id]
                
                await query.edit_message_text("❌ Đã hủy tạo chi tiêu nhóm.")

            elif data == "mark_debt_paid":
                logger.info(f"Processing mark_debt_paid callback for user {user_id}")
                await query.edit_message_text(
                    "✅ **Đã xác nhận thanh toán!**\n\n"
                    "Cảm ơn bạn đã xác nhận đã chuyển tiền qua ngân hàng.\n"
                    "Nợ của bạn đã được ghi nhận là đã thanh toán.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Menu chính", callback_data="main_menu")]
                    ])
                )

            elif data == "mark_debt_paid_cash":
                logger.info(f"Processing mark_debt_paid_cash callback for user {user_id}")
                await query.edit_message_text(
                    "💵 **Đã xác nhận thanh toán bằng tiền mặt!**\n\n"
                    "Cảm ơn bạn đã xác nhận đã trả bằng tiền mặt.\n"
                    "Nợ của bạn đã được ghi nhận là đã thanh toán.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Menu chính", callback_data="main_menu")]
                    ])
                )

            elif data == "debt_details":
                logger.info(f"Processing debt_details callback for user {user_id}")
                await query.edit_message_text(
                    "ℹ️ **Chi tiết nợ**\n\n"
                    "Đây là thông tin chi tiết về khoản nợ của bạn:\n\n"
                    "• 📱 Xem mã QR: Quét mã để chuyển tiền\n"
                    "• ✅ Đã chuyển: Xác nhận khi đã chuyển qua ngân hàng\n"
                    "• 💵 Trả tiền mặt: Xác nhận khi đã trả bằng tiền mặt\n\n"
                    "Nợ sẽ được xóa khỏi hệ thống sau khi xác nhận thanh toán.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Quay lại", callback_data="main_menu")]
                    ])
                )

            else:
                # Handle unrecognized callback
                logger.warning(f"Unhandled callback query: {data}")
                await query.edit_message_text(
                    "⚠️ Chức năng này đang được phát triển.\nVui lòng quay lại menu chính.",
                    reply_markup=Keyboards.main_dm_menu()
                )

        except Exception as e:
            logger.error(f"Error handling callback query {data}: {e}")
            try:
                await query.edit_message_text("❌ Đã xảy ra lỗi. Vui lòng thử lại.")
            except Exception:
                # If edit fails, just log
                logger.error("Failed to send error message to user")

    @staticmethod
    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages for multi-step operations."""
        user_id = update.effective_user.id
        text = update.message.text.strip()
        
        logger.info(f"Received message from user {user_id}: '{text}'")
        logger.info(f"Current user_states: {user_states}")
        logger.info(f"Current group_expense_states: {group_expense_states}")
        
        # Check for group expense state first (only in group chats)
        if user_id in group_expense_states and update.effective_chat.type in ['group', 'supergroup']:
            state = group_expense_states[user_id]
            if state.get('step') == 'amount':
                try:
                    # Parse amount and description like "120 ăn sáng"
                    parts = text.split(None, 1)  # Split into max 2 parts
                    amount = Decimal(parts[0])
                    description = parts[1] if len(parts) > 1 else None
                    
                    if amount <= 0:
                        await update.message.reply_text("❌ Số tiền phải lớn hơn 0!")
                        return
                    
                    # Store amount and description
                    state['amount'] = amount
                    state['description'] = description
                    state['payer_id'] = user_id  # Person who enters = payer
                    state['step'] = 'participants'
                    state['selected_participants'] = []
                    
                    # Get chat members for participant selection
                    try:
                        # Try to get all chat members first (if bot has permission)
                        try:
                            chat_member_count = await context.bot.get_chat_member_count(state['group_id'])
                            if chat_member_count <= 200:  # Small group, try to get all members
                                # Note: get_chat_administrators is more reliable than get_chat_members
                                chat_members = await context.bot.get_chat_administrators(state['group_id'])
                            else:
                                # For large groups, use administrators as fallback
                                chat_members = await context.bot.get_chat_administrators(state['group_id'])
                        except:
                            # Fallback to administrators only
                            chat_members = await context.bot.get_chat_administrators(state['group_id'])
                        
                        # Filter out bots and add manual participant option
                        human_members = [m for m in chat_members if not m.user.is_bot]
                        
                        amount_text = currency_service.format_amount(amount, state['currency'])
                        desc_text = f" - {description}" if description else ""
                        payer_name = update.effective_user.first_name
                        
                        await update.message.reply_text(
                            f"💰 Chi tiêu: {amount_text}{desc_text}\n"
                            f"👤 Người trả: {payer_name} (bạn)\n\n"
                            "👥 **Chọn người tham gia chia tiền:**\n"
                            "(Bao gồm cả bạn - người trả tiền)\n\n"
                            "💡 Nếu không thấy người cần chọn, có thể họ chưa tương tác với bot trong group này.",
                            reply_markup=Keyboards.group_participant_selection(human_members, [])
                        )
                        return
                        
                    except Exception as e:
                        logger.error(f"Error getting chat members: {e}")
                        await update.message.reply_text(
                            "❌ Không thể lấy danh sách thành viên group. "
                            "Đảm bảo bot có quyền admin trong group!"
                        )
                        return
                    
                    amount_text = currency_service.format_amount(amount, state['currency'])
                    desc_text = f" - {description}" if description else ""
                    
                    await update.message.reply_text(
                        f"💰 Chi tiêu: {amount_text}{desc_text}\n\n"
                        "� **Ai là người trả tiền?**\n"
                        "Chọn người đã trả tiền:",
                        reply_markup=Keyboards.group_payer_selection(chat_members, user_id)
                    )
                    return
                    
                except (ValueError, InvalidOperation):
                    await update.message.reply_text(
                        "❌ Định dạng không đúng!\n\n"
                        "📝 Ví dụ đúng:\n"
                        "• 120 ăn sáng\n" 
                        "• 50.5 cafe\n"
                        "• 1000"
                    )
                    return
        
        # Handle quick expense input in DM (e.g., "120 ăn sáng")
        if update.effective_chat.type == 'private' and user_id not in user_states:
            try:
                # Try to parse as quick expense: "amount description"
                parts = text.split(None, 1)
                if len(parts) >= 1:
                    amount = Decimal(parts[0])
                    description = parts[1] if len(parts) > 1 else None
                    
                    if amount > 0:
                        # Get user from database
                        db_user = await db.get_user_by_tg_id(user_id)
                        if not db_user:
                            await update.message.reply_text(
                                "❌ Vui lòng gõ /start để đăng ký trước!"
                            )
                            return
                        
                        # Create expense with default currency (VND)
                        currency = 'VND'
                        
                        # Process the expense
                        await BotHandlers.process_personal_expense(
                            update.message.reply_text, 
                            db_user.id, 
                            amount, 
                            currency, 
                            description
                        )
                        return
                        
            except (ValueError, InvalidOperation):
                # Not a valid expense format, ignore
                pass
        
        if user_id not in user_states:
            logger.info(f"User {user_id} not in user_states, ignoring message")
            return

        state = user_states[user_id]
        action = state.get('action')

        try:
            if action == 'create_wallet_amount':
                # Handle wallet creation amount input
                logger.info(f"Processing wallet creation amount for user {user_id}: {text}")
                try:
                    amount = Decimal(text)
                    if amount < 0:
                        await update.message.reply_text("❌ Số tiền phải lớn hơn 0!")
                        return
                    
                    currency = state['currency']
                    note = state.get('note')
                    logger.info(f"Creating wallet - Currency: {currency}, Amount: {amount}, Note: {note}")
                    
                    # Create wallet
                    db_user = await db.get_user_by_tg_id(user_id)
                    logger.info(f"Found user: {db_user.id}")
                    
                    wallet = await db.create_wallet(db_user.id, currency, amount, note)
                    logger.info(f"Wallet created successfully: {wallet.id}")
                    
                    formatted_amount = currency_service.format_amount(amount, currency)
                    note_text = f"\n📝 Ghi chú: {note}" if note else ""
                    
                    success_message = (
                        f"✅ **Tạo ví thành công!**\n\n"
                        f"💰 Loại tiền: {currency}\n"
                        f"💵 Số dư ban đầu: {formatted_amount}{note_text}\n\n"
                        f"Bạn có thể sử dụng các chức năng khác trong menu."
                    )
                    
                    logger.info(f"Sending success message to user {user_id}")
                    await update.message.reply_text(
                        success_message,
                        reply_markup=Keyboards.main_dm_menu(),
                        parse_mode='Markdown'
                    )
                    logger.info(f"Success message sent successfully")
                    
                    del user_states[user_id]
                    
                except (InvalidOperation, ValueError) as e:
                    logger.error(f"Invalid amount error: {e}")
                    await update.message.reply_text("❌ Số tiền không hợp lệ! Vui lòng nhập lại:")
                except Exception as e:
                    logger.error(f"Error creating wallet: {e}")
                    # Check if it's a UNIQUE constraint error (wallet already exists)
                    if "UNIQUE constraint failed" in str(e):
                        await update.message.reply_text(
                            f"⚠️ **Ví {state['currency']} đã tồn tại!**\n\n"
                            f"Bạn chỉ có thể tạo một ví cho mỗi loại tiền.\n"
                            f"Vui lòng chọn loại tiền khác hoặc quản lý ví hiện tại.",
                            parse_mode='Markdown',
                            reply_markup=Keyboards.budget_menu()
                        )
                    else:
                        await update.message.reply_text("❌ Có lỗi xảy ra khi tạo ví. Vui lòng thử lại!")
                    if user_id in user_states:
                        del user_states[user_id]

            elif action == 'wallet_note':
                # Handle wallet note input
                state['note'] = text if text.lower() != 'skip' else None
                state['action'] = 'create_wallet_amount'
                
                currency = state['currency']
                await update.message.reply_text(f"Nhập số tiền ban đầu cho ví {currency}:")
                user_states[user_id] = state

            elif action == 'add_expense' or action == 'personal_expense_amount':
                # Handle expense amount input
                logger.info(f"Processing expense amount for user {user_id}: {text}")
                try:
                    # Parse input to extract amount and description
                    # Format: "120 ăn sáng" or "120.50 mua đồ" or just "120"
                    text_parts = text.strip().split(' ', 1)  # Split into max 2 parts
                    amount_str = text_parts[0].replace(',', '.')  # Allow comma as decimal separator
                    
                    # Extract amount
                    amount = Decimal(amount_str)
                    if amount <= 0:
                        await update.message.reply_text("❌ Số tiền phải lớn hơn 0! Vui lòng nhập lại (VD: 120 ăn sáng):")
                        return
                    
                    # Extract description (reason for expense)
                    description = text_parts[1].strip() if len(text_parts) > 1 else "Chi tiêu cá nhân"
                    
                    wallet_id = state['wallet_id']
                    wallet = await db.get_wallet(wallet_id)
                    
                    # Create expense record with description
                    db_user = await db.get_user_by_tg_id(user_id)
                    expense = await db.add_personal_expense(db_user.id, amount, wallet.currency, wallet_id, description)
                    
                    # Update wallet balance
                    success = await db.update_wallet_balance(wallet_id, -amount, f"Chi tiêu: {description}")
                    
                    if success:
                        # Get updated wallet info
                        updated_wallet = await db.get_wallet(wallet_id)
                        remaining_balance = Decimal(updated_wallet.current_balance)
                        
                        # Get today's total expenses for this wallet
                        today_expenses = await db.get_personal_expenses_today(db_user.id, wallet.currency)
                        total_spent_today = sum(Decimal(exp.amount) for exp in today_expenses)
                        
                        # Format amounts
                        spent_amount = currency_service.format_amount(amount, wallet.currency)
                        remaining_amount = currency_service.format_amount(remaining_balance, wallet.currency)
                        today_total = currency_service.format_amount(total_spent_today, wallet.currency)
                        
                        # Success message with detailed info
                        success_message = (
                            f"✅ **Đã ghi nhận chi tiêu!**\n\n"
                            f"💸 Số tiền: {spent_amount}\n"
                            f"� Lý do: {description}\n"
                            f"�💰 Ví: {wallet.currency}\n"
                            f"💵 Số dư còn lại: {remaining_amount}\n"
                            f"📊 Tổng chi hôm nay: {today_total}\n\n"
                            f"Bạn có thể tiếp tục sử dụng các chức năng khác."
                        )
                        
                        await update.message.reply_text(
                            success_message,
                            reply_markup=Keyboards.main_dm_menu(),
                            parse_mode='Markdown'
                        )
                        logger.info(f"Expense recorded successfully for user {user_id}: {amount} {wallet.currency} for '{description}'")
                    else:
                        await update.message.reply_text("❌ Không đủ số dư trong ví! Chi tiêu đã được ghi nhận nhưng ví âm quỹ.")
                    
                    del user_states[user_id]
                    
                except (InvalidOperation, ValueError) as e:
                    logger.error(f"Invalid expense amount: {e}")
                    await update.message.reply_text(
                        "❌ Số tiền không hợp lệ! \n\n"
                        "**Cách nhập:**\n"
                        "• 120 ăn sáng\n"
                        "• 50.5 cafe\n"
                        "• 1000 mua đồ\n"
                        "• 25 (không có lý do)\n\n"
                        "Vui lòng thử lại:"
                    )
                except Exception as e:
                    logger.error(f"Error adding expense: {e}")
                    await update.message.reply_text("❌ Có lỗi xảy ra khi ghi nhận chi tiêu. Vui lòng thử lại!")
                    if user_id in user_states:
                        del user_states[user_id]

            elif action == 'topup_amount':
                # Handle topup amount input
                logger.info(f"Processing topup amount for user {user_id}: {text}")
                try:
                    amount = Decimal(text.replace(',', '.'))
                    if amount <= 0:
                        await update.message.reply_text("❌ Số tiền phải lớn hơn 0! Vui lòng nhập lại:")
                        return
                    
                    wallet_id = state['wallet_id']
                    wallet = await db.get_wallet(wallet_id)
                    
                    # Update wallet balance (add money)
                    success = await db.update_wallet_balance(wallet_id, amount, "Nạp tiền")
                    
                    if success:
                        # Get updated wallet info
                        updated_wallet = await db.get_wallet(wallet_id)
                        new_balance = Decimal(updated_wallet.current_balance)
                        
                        # Format amounts
                        topup_amount = currency_service.format_amount(amount, wallet.currency)
                        new_balance_text = currency_service.format_amount(new_balance, wallet.currency)
                        
                        await update.message.reply_text(
                            f"✅ **Nạp tiền thành công!**\n\n"
                            f"💳 Số tiền nạp: {topup_amount}\n"
                            f"💰 Ví: {wallet.currency}\n"
                            f"💵 Số dư mới: {new_balance_text}\n\n"
                            f"Ví của bạn đã được cập nhật!",
                            reply_markup=Keyboards.main_dm_menu(),
                            parse_mode='Markdown'
                        )
                        logger.info(f"Topup successful for user {user_id}: +{amount} {wallet.currency}")
                    else:
                        await update.message.reply_text("❌ Có lỗi xảy ra khi nạp tiền. Vui lòng thử lại!")
                    
                    del user_states[user_id]
                    
                except (InvalidOperation, ValueError) as e:
                    logger.error(f"Invalid topup amount: {e}")
                    await update.message.reply_text("❌ Số tiền không hợp lệ! Vui lòng nhập số (VD: 1000):")
                except Exception as e:
                    logger.error(f"Error processing topup: {e}")
                    await update.message.reply_text("❌ Có lỗi xảy ra khi nạp tiền. Vui lòng thử lại!")
                    if user_id in user_states:
                        del user_states[user_id]

            elif action == 'decrease_amount':
                # Handle decrease amount input
                logger.info(f"Processing decrease amount for user {user_id}: {text}")
                try:
                    amount = Decimal(text.replace(',', '.'))
                    if amount <= 0:
                        await update.message.reply_text("❌ Số tiền phải lớn hơn 0! Vui lòng nhập lại:")
                        return
                    
                    wallet_id = state['wallet_id']
                    wallet = await db.get_wallet(wallet_id)
                    current_balance = Decimal(wallet.current_balance)
                    
                    if amount > current_balance:
                        await update.message.reply_text(
                            f"❌ Số tiền giảm không thể lớn hơn số dư hiện tại!\n\n"
                            f"💵 Số dư hiện tại: {currency_service.format_amount(current_balance, wallet.currency)}\n"
                            f"Vui lòng nhập số tiền nhỏ hơn hoặc bằng số dư."
                        )
                        return
                    
                    # Update wallet balance (subtract money)
                    success = await db.update_wallet_balance(wallet_id, -amount, "Giảm tiền")
                    
                    if success:
                        # Get updated wallet info
                        updated_wallet = await db.get_wallet(wallet_id)
                        new_balance = Decimal(updated_wallet.current_balance)
                        
                        # Format amounts
                        decrease_amount = currency_service.format_amount(amount, wallet.currency)
                        new_balance_text = currency_service.format_amount(new_balance, wallet.currency)
                        
                        await update.message.reply_text(
                            f"✅ **Giảm tiền thành công!**\n\n"
                            f"➖ Số tiền giảm: {decrease_amount}\n"
                            f"💰 Ví: {wallet.currency}\n"
                            f"💵 Số dư mới: {new_balance_text}\n\n"
                            f"Ví của bạn đã được cập nhật!",
                            reply_markup=Keyboards.main_dm_menu(),
                            parse_mode='Markdown'
                        )
                        logger.info(f"Decrease successful for user {user_id}: -{amount} {wallet.currency}")
                    else:
                        await update.message.reply_text("❌ Có lỗi xảy ra khi giảm tiền. Vui lòng thử lại!")
                    
                    del user_states[user_id]
                    
                except (InvalidOperation, ValueError) as e:
                    logger.error(f"Invalid decrease amount: {e}")
                    await update.message.reply_text("❌ Số tiền không hợp lệ! Vui lòng nhập số (VD: 500):")
                except Exception as e:
                    logger.error(f"Error processing decrease: {e}")
                    await update.message.reply_text("❌ Có lỗi xảy ra khi giảm tiền. Vui lòng thử lại!")
                    if user_id in user_states:
                        del user_states[user_id]

            elif action == 'create_qr_with_amount' and state.get('step') == 'amount_input':
                # Handle amount input for QR creation
                try:
                    amount = Decimal(text.replace(',', '.'))
                    if amount <= 0:
                        await update.message.reply_text("❌ Số tiền phải lớn hơn 0! Vui lòng nhập lại:")
                        return
                    
                    # Get user's bank account
                    db_user = await db.get_user_by_tg_id(user_id)
                    user_accounts = await db.get_user_bank_accounts(db_user.id)
                    bank_account = user_accounts[0]
                    account_id, bank_code, bank_name, account_number, account_name, is_default = bank_account
                    
                    # Generate QR with amount
                    qr_url = await vietqr_service.generate_qr_direct(
                        bank_code,
                        account_number,
                        account_name,
                        amount=amount,
                        description=f"Chuyển khoản {amount:,.0f} VND"
                    )
                    
                    if qr_url:
                        text = f"💰 **MÃ QR NHẬN TIỀN**\n\n"
                        text += f"🏛️ **Ngân hàng:** {bank_name}\n"
                        text += f"💳 **Số tài khoản:** `{account_number}`\n"
                        text += f"👤 **Tên tài khoản:** {account_name}\n"
                        text += f"💵 **Số tiền:** {amount:,.0f} VND\n\n"
                        text += "💡 **Hướng dẫn sử dụng:**\n"
                        text += "• Gửi mã QR này cho người muốn chuyển tiền\n"
                        text += "• Họ quét mã QR bằng app ngân hàng\n"
                        text += f"• Số tiền sẽ tự động điền: {amount:,.0f} VND\n"
                        text += "• Chỉ cần xác nhận chuyển khoản\n\n"
                        text += "⚠️ **Lưu ý:** QR này có số tiền cố định"
                        
                        await update.message.reply_text(
                            "✅ **Đã tạo mã QR thành công!**",
                            parse_mode='Markdown'
                        )
                        
                        await context.bot.send_photo(
                            chat_id=update.message.chat.id,
                            photo=qr_url,
                            caption=text,
                            parse_mode='Markdown',
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔄 Tạo QR mới", callback_data="create_qr_with_amount")],
                                [InlineKeyboardButton("🔙 Quay lại", callback_data="bank_account_menu")]
                            ])
                        )
                    else:
                        await update.message.reply_text(
                            "❌ **Lỗi tạo QR Code**\n\n"
                            "Không thể tạo mã QR. Vui lòng thử lại sau.",
                            parse_mode='Markdown',
                            reply_markup=Keyboards.bank_account_menu(True)
                        )
                    
                    # Clear state
                    del user_states[user_id]
                    
                except (InvalidOperation, ValueError) as e:
                    logger.error(f"Invalid amount: {e}")
                    await update.message.reply_text("❌ Số tiền không hợp lệ! Vui lòng nhập số (VD: 50000):")
                except Exception as e:
                    logger.error(f"Error creating QR: {e}")
                    await update.message.reply_text("❌ Có lỗi xảy ra khi tạo QR. Vui lòng thử lại!")
                    if user_id in user_states:
                        del user_states[user_id]

            elif action == 'add_bank_account' and state.get('step') == 'account_name':
                # Handle account name input
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
                    del user_states[user_id]
                    
                except Exception as e:
                    logger.error(f"Error adding bank account: {e}")
                    await update.message.reply_text("❌ Có lỗi khi thêm tài khoản. Vui lòng thử lại!")

            elif action == 'add_bank_account':
                # Handle bank account number input
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

            elif action == 'set_exchange_rate':
                # Handle exchange rate input (admin only)
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
                        reply_markup=Keyboards.admin_exchange_rate_menu()
                    )
                    
                    del user_states[user_id]
                    
                except (InvalidOperation, ValueError) as e:
                    logger.error(f"Invalid exchange rate: {e}")
                    await update.message.reply_text("❌ Tỷ giá không hợp lệ! Vui lòng nhập số (VD: 875):")
                except Exception as e:
                    logger.error(f"Error setting exchange rate: {e}")
                    await update.message.reply_text("❌ Có lỗi xảy ra khi cập nhật tỷ giá. Vui lòng thử lại!")
                    if user_id in user_states:
                        del user_states[user_id]

            # Handle other message states...
            # [Additional message handlers would go here]

        except Exception as e:
            logger.error(f"Error handling message for state {action}: {e}")
            await update.message.reply_text("❌ Đã xảy ra lỗi. Vui lòng thử lại.")
            if user_id in user_states:
                del user_states[user_id]


async def setup_bot_commands(application: Application):
    """Set up bot commands for the menu."""
    
    # First clear all existing commands
def main():
    """Main function to run the bot."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found in environment variables!")
        return

    # Create application with faster timeout settings
    request = HTTPXRequest(
        connection_pool_size=16,
        read_timeout=5,
        write_timeout=5,
        connect_timeout=3,
        pool_timeout=5
    )
    application = Application.builder().token(BOT_TOKEN).request(request).build()

    # Add handlers
    application.add_handler(CommandHandler("start", BotHandlers.start_command))
    application.add_handler(CommandHandler("help", BotHandlers.help_command))
    application.add_handler(CommandHandler("rates", BotHandlers.rates_command))
    application.add_handler(CommandHandler("setrates", BotHandlers.setrates_command))
    application.add_handler(CommandHandler("spend", BotHandlers.spend_command))
    application.add_handler(CommandHandler("summary", BotHandlers.summary_command))
    application.add_handler(CommandHandler("gspend", BotHandlers.gspend_command))
    application.add_handler(CommandHandler("undo", BotHandlers.undo_command))
    application.add_handler(CommandHandler("settle", BotHandlers.settle_command))
    application.add_handler(CommandHandler("expense_history_7", BotHandlers.expense_history_7_command))
    application.add_handler(CommandHandler("wallets", BotHandlers.wallets_command))
    application.add_handler(CommandHandler("active", BotHandlers.active_command))
    
    # Legacy handlers for backward compatibility
    application.add_handler(CommandHandler("expense", BotHandlers.spend_command))  # Alias
    application.add_handler(CommandHandler("history", BotHandlers.summary_command))  # Alias
    application.add_handler(CommandHandler("settings", BotHandlers.settings_command))
    application.add_handler(CommandHandler("newtrip", BotHandlers.newtrip_command))
    application.add_handler(CommandHandler("join", BotHandlers.join_command))
    application.add_handler(CommandHandler("add", BotHandlers.gspend_command))  # Alias for group spend
    application.add_handler(CommandHandler("overview", BotHandlers.settle_command))  # Alias
    
    application.add_handler(CallbackQueryHandler(BotHandlers.handle_callback_query))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, BotHandlers.handle_message))
    
    # Add error handler
    application.add_error_handler(error_handler)

    # Initialize database and set up commands
    async def post_init(application: Application):
        await db.init_db()
        
        # Set bot commands for new bot
        try:
            # Commands for private chats (DMs)
            dm_commands = [
                BotCommand("start", "Bắt đầu & đăng ký 🚀"),
                BotCommand("help", "Trợ giúp ❓"),
                BotCommand("spend", "Ghi chi tiêu cá nhân 🧾"),
                BotCommand("summary", "Tóm tắt cá nhân 📊"),
                BotCommand("expense_history_7", "Lịch sử chi tiêu 7 ngày 📚"),
                BotCommand("wallets", "Xem danh sách ví �"),
                BotCommand("rates", "Xem tỷ giá hiện tại 💱"),
                BotCommand("setrates", "Quản lý tỷ giá (Admin) ⚙️"),
            ]
            
            # Commands for group chats
            group_commands = [
                BotCommand("start", "Bắt đầu & đăng ký 🚀"),
                BotCommand("help", "Trợ giúp ❓"),
                BotCommand("gspend", "Chi nhóm & chia tiền 👥"),
                BotCommand("undo", "Hoàn tác chi tiêu gần đây ↩️"),
                BotCommand("settle", "Tổng kết công nợ ✅"),
                BotCommand("rates", "Xem tỷ giá hiện tại 💱"),
            ]
            
            # Set commands for private chats
            await application.bot.set_my_commands(dm_commands, scope=BotCommandScopeAllPrivateChats())
            await application.bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())
            
            logger.info(f"Set {len(dm_commands)} commands for DMs and {len(group_commands)} commands for groups")
            
        except Exception as e:
            logger.error(f"Error setting commands: {e}")
        
        logger.info("Bot initialized successfully")
        
        # Start daily task scheduler
        asyncio.create_task(schedule_daily_tasks(application))

    async def post_stop(application: Application):
        await currency_service.close()
        logger.info("Bot stopped")

    application.post_init = post_init
    application.post_stop = post_stop

    # Run the bot (webhook or polling)
    logger.info("Starting bot...")
    logger.info(f"USE_WEBHOOK={USE_WEBHOOK}, WEBHOOK_DOMAIN={WEBHOOK_DOMAIN}, WEBHOOK_PATH={WEBHOOK_PATH}, WEBHOOK_PORT={WEBHOOK_PORT}")
    if USE_WEBHOOK:
        # Build full webhook URL
        if not WEBHOOK_DOMAIN:
            logger.error("USE_WEBHOOK=true nhưng thiếu WEBHOOK_DOMAIN")
            return
        webhook_url = f"https://{WEBHOOK_DOMAIN}{WEBHOOK_PATH}"
        logger.info(f"Using webhook URL: {webhook_url}")

        application.run_webhook(
            listen="0.0.0.0",
            port=WEBHOOK_PORT,
            url_path=WEBHOOK_PATH.lstrip('/'),
            webhook_url=webhook_url,
            secret_token=WEBHOOK_SECRET,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    else:
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
