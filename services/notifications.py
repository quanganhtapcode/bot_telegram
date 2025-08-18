"""
Notification service for sending debt summaries and VietQR payments.
Handles private notifications to maintain privacy.
"""
import logging
from decimal import Decimal

import db
from services.currency import CurrencyService
from services.vietqr import VietQRService

logger = logging.getLogger(__name__)

class NotificationService:
    """Handles all notification sending"""
    
    def __init__(self, bot):
        self.bot = bot
        self.currency_service = CurrencyService()
        self.vietqr_service = VietQRService()

    async def send_group_debt_notifications(self, group_id):
        """Send private debt notifications to group members"""
        try:
            # Get all members with debts in this group
            group_debts = await db.get_group_debts(group_id)
            
            if not group_debts:
                return
            
            # Group debts by debtor
            debtor_notifications = {}
            
            for debt in group_debts:
                debtor_id = debt['debtor_id']
                creditor_id = debt['creditor_id']
                amount = Decimal(debt['amount'])
                currency = debt['currency']
                
                if debtor_id not in debtor_notifications:
                    debtor_notifications[debtor_id] = []
                
                debtor_notifications[debtor_id].append({
                    'creditor_id': creditor_id,
                    'amount': amount,
                    'currency': currency
                })
            
            # Send notifications to each debtor
            for debtor_id, debts in debtor_notifications.items():
                await self.send_private_debt_notification(debtor_id, debts)
                
        except Exception as e:
            logger.error(f"Error sending group debt notifications: {e}")

    async def send_private_debt_notification(self, debtor_id, debts):
        """Send private debt notification to a specific user"""
        try:
            # Get debtor info
            debtor = await db.get_user(debtor_id)
            if not debtor:
                return
            
            message = "💳 **Thông báo công nợ cá nhân**\n\n"
            
            for debt in debts:
                creditor = await db.get_user(debt['creditor_id'])
                if not creditor:
                    continue
                
                amount_text = self.currency_service.format_amount(debt['amount'], debt['currency'])
                message += f"💰 Nợ {creditor.name}: {amount_text}\n"
                
                # Add VietQR payment info if available
                payment_info = await self.vietqr_service.get_user_payment_info(debt['creditor_id'])
                if payment_info and debt['currency'] == 'VND':
                    qr_url = self.vietqr_service.generate_payment_qr(
                        payment_info['bank_code'],
                        payment_info['account_number'],
                        payment_info['account_name'],
                        debt['amount'],
                        f"Thanh toan {creditor.name}"
                    )
                    message += f"📱 [Thanh toán QR]({qr_url})\n"
                
                message += "\n"
            
            message += "🔒 Thông tin này chỉ được gửi riêng cho bạn để bảo mật"
            
            await self.bot.send_message(
                chat_id=debtor.telegram_id,
                text=message,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error sending private debt notification: {e}")
