"""
Command handlers for the bot.
Split from main.py to improve code organization.
"""
import logging
from decimal import Decimal, InvalidOperation
from telegram import Update
from telegram.ext import ContextTypes

import db
from keyboards import Keyboards

logger = logging.getLogger(__name__)

class CommandHandlers:
    """Handles all bot commands"""
    
    def __init__(self):
        self.currency_service = None
    
    async def _get_currency_service(self):
        """Lazy initialize currency service"""
        if self.currency_service is None:
            from services.currency import CurrencyService
            self.currency_service = CurrencyService(db)
        return self.currency_service
    
    @staticmethod
    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        user_id = update.effective_user.id
        user_name = update.effective_user.full_name
        
        # Create or update user
        await db.create_or_update_user(user_id, user_name)
        
        if update.effective_chat.type == 'private':
            # DM - show main menu
            await update.message.reply_text(
                f"👋 Xin chào {user_name}!\n\n"
                "🤖 Bot quản lý chi tiêu cá nhân và nhóm\n"
                "📱 Sử dụng menu bên dưới để bắt đầu:",
                reply_markup=Keyboards.main_dm_menu()
            )
        else:
            # Group - show group menu  
            await update.message.reply_text(
                f"👋 Xin chào nhóm!\n\n"
                "🤖 Bot quản lý chi tiêu nhóm\n"
                "📱 Sử dụng menu bên dưới:",
                reply_markup=Keyboards.group_main_menu()
            )

    @staticmethod
    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        help_text = """
🤖 **Hướng dẫn sử dụng Bot Chi tiêu**

**📱 Lệnh cơ bản:**
• `/start` - Khởi động bot
• `/help` - Hướng dẫn này

**💰 Chi tiêu cá nhân (DM):**
• `120 ăn sáng` - Ghi chi tiêu nhanh
• `50 cafe` - Ghi chi tiêu với ghi chú
• Menu "Cá nhân" để quản lý chi tiết

**👥 Chi tiêu nhóm:**
• Menu "Nhóm" để chia sẻ chi phí
• Tự động tính toán và tối ưu hóa nợ
• Thông báo riêng tư cho từng người

**⚙️ Cài đặt:**
• Menu "Cài đặt" để cấu hình ví, múi giờ
• Thêm tài khoản ngân hàng cho VietQR
• Admin có thể set tỷ giá chuyển đổi

**💡 Mẹo:**
• Nhập số tiền + mô tả (VD: "120 ăn sáng")  
• Bot tự động chia đều chi phí nhóm
• Nhận thông báo riêng về công nợ
        """
        
        await update.message.reply_text(help_text, parse_mode='Markdown')

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
            # Initialize currency service
            from services.currency import CurrencyService
            currency_service = CurrencyService(db)
            
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

        await update.message.reply_text(
            "💸 Ghi chi tiêu cá nhân\n\n"
            "Cách sử dụng:\n"
            "• Nhập: `120 ăn sáng`\n"  
            "• Hoặc chỉ số: `120`\n"
            "• Dùng menu để quản lý chi tiết",
            parse_mode='Markdown',
            reply_markup=Keyboards.personal_expense_menu()
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
    async def group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /group command."""
        if update.effective_chat.type == 'private':
            await update.message.reply_text("Lệnh này chỉ dùng được trong nhóm!")
            return

        await update.message.reply_text(
            "👥 Chi tiêu nhóm\n\n"
            "Chọn loại tiền tệ để bắt đầu:",
            reply_markup=Keyboards.group_currency_selection()
        )

    @staticmethod
    async def settle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /settle command."""
        if update.effective_chat.type == 'private':
            await update.message.reply_text("Lệnh này chỉ dùng được trong nhóm!")
            return

        # Show settlement statistics without sensitive details
        await update.message.reply_text(
            "💳 **Thống kê thanh toán nhóm**\n\n"
            "📊 Các thành viên đã nhận thông báo riêng về công nợ\n"
            "🔒 Thông tin chi tiết được gửi riêng để bảo mật\n\n"
            "💡 Kiểm tra tin nhắn riêng với bot để xem chi tiết thanh toán",
            parse_mode='Markdown'
        )

    @staticmethod
    async def admin_rates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /admin_rates command (admin only)."""
        user_id = update.effective_user.id
        
        # Import ADMIN_USER_ID (will be fixed in refactor)
        ADMIN_USER_ID = 5245151002
        
        if user_id != ADMIN_USER_ID:
            await update.message.reply_text("❌ Không có quyền truy cập!")
            return

        if update.effective_chat.type != 'private':
            await update.message.reply_text("Lệnh này chỉ dùng được trong DM!")
            return

        await update.message.reply_text(
            "💱 **Quản lý tỷ giá (Admin)**\n\n"
            "Chọn loại tỷ giá cần cập nhật:",
            parse_mode='Markdown',
            reply_markup=Keyboards.admin_exchange_rate_menu()
        )
