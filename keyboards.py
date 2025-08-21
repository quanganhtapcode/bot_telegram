"""
Inline keyboard layouts for the Telegram bot.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import List, Optional
from models import UserWallet, User


class Keyboards:
    @staticmethod
    def main_dm_menu() -> InlineKeyboardMarkup:
        """Main menu for DM conversations."""
        keyboard = [
            [InlineKeyboardButton("💰 Quản lý ví", callback_data="budget_menu")],
            [InlineKeyboardButton("💸 Chi tiêu cá nhân", callback_data="personal_expense_menu")],
            [InlineKeyboardButton("⚙️ Cài đặt", callback_data="settings_menu"), 
             InlineKeyboardButton("❓ Trợ giúp", callback_data="help_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def budget_menu() -> InlineKeyboardMarkup:
        """Budget management menu."""
        keyboard = [
            [
                InlineKeyboardButton("➕ Tạo ví mới", callback_data="create_wallet"),
                InlineKeyboardButton("💰 Nạp tiền", callback_data="topup_wallet")
            ],
            [
                InlineKeyboardButton("💸 Rút tiền", callback_data="decrease_wallet"),
                InlineKeyboardButton("🗑️ Xóa ví", callback_data="delete_wallet")
            ],
            [InlineKeyboardButton("📊 Chi tiết ví", callback_data="wallet_details")],
            [InlineKeyboardButton("🔙 Quay lại", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def personal_expense_menu() -> InlineKeyboardMarkup:
        """Personal expense menu."""
        keyboard = [
            [InlineKeyboardButton("➕ Thêm chi tiêu", callback_data="add_personal_expense")],
            [InlineKeyboardButton("📊 Lịch sử (7 ngày)", callback_data="expense_history_7")],
            [InlineKeyboardButton("🔄 Hoàn tác giao dịch", callback_data="undo_expense")],
            [InlineKeyboardButton("🔙 Quay lại", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def settings_menu() -> InlineKeyboardMarkup:
        """Settings menu."""
        keyboard = [
            [InlineKeyboardButton("🏦 Quản lý tài khoản", callback_data="bank_account_menu")],
            [InlineKeyboardButton("💱 Cài đặt tiền tệ", callback_data="currency_settings")],
            [InlineKeyboardButton("🔙 Quay lại", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def currency_selection() -> InlineKeyboardMarkup:
        """Currency selection keyboard."""
        currencies = [
            ("TWD", "🇹🇼 TWD"),
            ("USD", "🇺🇸 USD"),
            ("EUR", "🇪🇺 EUR"),
            ("GBP", "🇬🇧 GBP"),
            ("JPY", "🇯🇵 JPY"),
            ("VND", "🇻🇳 VND")
        ]
        
        keyboard = []
        for i in range(0, len(currencies), 2):
            row = []
            row.append(InlineKeyboardButton(currencies[i][1], callback_data=f"currency_{currencies[i][0]}"))
            if i + 1 < len(currencies):
                row.append(InlineKeyboardButton(currencies[i+1][1], callback_data=f"currency_{currencies[i+1][0]}"))
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔙 Quay lại", callback_data="settings_menu")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def wallet_selection(wallets: List[UserWallet], action: str) -> InlineKeyboardMarkup:
        """Wallet selection keyboard."""
        keyboard = []
        for wallet in wallets:
            balance_text = f"{wallet.current_balance:,.2f}" if wallet.currency != "VND" else f"{wallet.current_balance:,.0f}"
            text = f"{wallet.currency}: {balance_text}"
            keyboard.append([InlineKeyboardButton(text, callback_data=f"{action}_wallet_{wallet.id}")])
        
        keyboard.append([InlineKeyboardButton("🔙 Quay lại", callback_data="budget_menu")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def confirm_action(action: str, item_id: Optional[str] = None) -> InlineKeyboardMarkup:
        """Confirmation keyboard for actions."""
        callback_confirm = f"confirm_{action}_{item_id}" if item_id else f"confirm_{action}"
        callback_cancel = f"cancel_{action}"
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Xác nhận", callback_data=callback_confirm),
                InlineKeyboardButton("❌ Huỷ", callback_data=callback_cancel)
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def group_main_menu() -> InlineKeyboardMarkup:
        """Main menu for group conversations."""
        keyboard = [
            [InlineKeyboardButton("💸 Thêm chi tiêu nhóm", callback_data="add_group_expense")],
            [InlineKeyboardButton("📊 Tổng quan chi tiêu", callback_data="group_overview")],
            [InlineKeyboardButton("🔄 Hoàn tác giao dịch", callback_data="undo_group_expense_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def participant_selection(members: List[User], selected: List[int] = None) -> InlineKeyboardMarkup:
        """Participant selection for group expenses."""
        if selected is None:
            selected = []
        
        keyboard = []
        for member in members:
            emoji = "✅" if member.id in selected else "☐"
            text = f"{emoji} {member.name}"
            callback_data = f"toggle_participant_{member.id}"
            keyboard.append([InlineKeyboardButton(text, callback_data=callback_data)])
        
        if selected:
            keyboard.append([InlineKeyboardButton("💰 Chia đều", callback_data="split_equal")])
        
        keyboard.append([InlineKeyboardButton("❌ Huỷ", callback_data="cancel_group_expense")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def deduction_options(wallets: List[tuple], share_amount, share_currency: str) -> InlineKeyboardMarkup:
        """Wallet options for group expense deduction."""
        keyboard = []
        
        # Add existing wallet options
        for wallet, fx_rate, deduction_amount in wallets:
            if share_currency == wallet.currency:
                text = f"💳 {wallet.currency}: {deduction_amount:,.2f}"
            else:
                text = f"💳 {wallet.currency}: {deduction_amount:,.2f} (từ {share_amount:,.2f} {share_currency})"
            keyboard.append([InlineKeyboardButton(text, callback_data=f"deduct_wallet_{wallet.id}")])
        
        # Add create new wallet option
        keyboard.append([InlineKeyboardButton(f"➕ Tạo ví {share_currency}", callback_data=f"create_deduct_{share_currency}")])
        
        # Add skip option
        keyboard.append([InlineKeyboardButton("⏭️ Bỏ qua", callback_data="skip_deduction")])
        
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def undo_expense_selection(expenses: List[tuple]) -> InlineKeyboardMarkup:
        """Expense selection for undo operation."""
        keyboard = []
        
        for expense, remaining_time in expenses:
            time_text = f"{remaining_time.total_seconds()/60:.0f}p" if remaining_time.total_seconds() > 0 else "Hết hạn"
            amount_text = f"{expense.amount:,.2f}" if expense.currency != "VND" else f"{expense.amount:,.0f}"
            text = f"{amount_text} {expense.currency} - {time_text}"
            if expense.note:
                text += f" ({expense.note[:20]}...)" if len(expense.note) > 20 else f" ({expense.note})"
            
            if remaining_time.total_seconds() > 0:
                keyboard.append([InlineKeyboardButton(text, callback_data=f"undo_expense_{expense.id}")])
            else:
                keyboard.append([InlineKeyboardButton(f"❌ {text}", callback_data="expired")])
        
        keyboard.append([InlineKeyboardButton("🔙 Quay lại", callback_data="personal_expense_menu")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def boolean_setting(setting_name: str, current_value: bool) -> InlineKeyboardMarkup:
        """Boolean setting toggle keyboard."""
        on_emoji = "✅" if current_value else "☐"
        off_emoji = "☐" if current_value else "✅"
        
        keyboard = [
            [
                InlineKeyboardButton(f"{on_emoji} Bật", callback_data=f"set_{setting_name}_true"),
                InlineKeyboardButton(f"{off_emoji} Tắt", callback_data=f"set_{setting_name}_false")
            ],
            [InlineKeyboardButton("🔙 Quay lại", callback_data="settings_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def back_to_menu(menu: str = "main_menu") -> InlineKeyboardMarkup:
        """Simple back button."""
        keyboard = [[InlineKeyboardButton("🔙 Quay lại", callback_data=menu)]]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def currency_selection_menu(exclude_currencies=None) -> InlineKeyboardMarkup:
        """Currency selection menu for wallet creation."""
        if exclude_currencies is None:
            exclude_currencies = set()
            
        all_currencies = [
            ("🇹🇼 TWD (Đài Loan)", "currency_TWD", "TWD"),
            ("🇺🇸 USD (Mỹ)", "currency_USD", "USD"),
            ("🇻🇳 VND (Việt Nam)", "currency_VND", "VND"),
            ("🇪🇺 EUR (Châu Âu)", "currency_EUR", "EUR"),
        ]
        
        keyboard = []
        for display_name, callback_data, currency_code in all_currencies:
            if currency_code not in exclude_currencies:
                keyboard.append([InlineKeyboardButton(display_name, callback_data=callback_data)])
        
        # Add unavailable currencies with disabled state
        if exclude_currencies:
            unavailable_text = []
            for display_name, callback_data, currency_code in all_currencies:
                if currency_code in exclude_currencies:
                    unavailable_text.append(f"❌ {display_name} (đã tồn tại)")
            
            if unavailable_text:
                keyboard.append([InlineKeyboardButton("─" * 20, callback_data="ignore")])
                for text in unavailable_text:
                    keyboard.append([InlineKeyboardButton(text, callback_data="ignore")])
        
        keyboard.append([InlineKeyboardButton("🔙 Quay lại", callback_data="budget_menu")])
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def wallet_management_menu() -> InlineKeyboardMarkup:
        """Wallet management menu."""
        keyboard = [
            [InlineKeyboardButton("➕ Thêm tiền", callback_data="add_money")],
            [InlineKeyboardButton("📊 Chi tiết ví", callback_data="wallet_details")],
            [InlineKeyboardButton("🔙 Quay lại", callback_data="budget_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def wallet_details_menu() -> InlineKeyboardMarkup:
        """Wallet details view menu - only back button."""
        keyboard = [
            [InlineKeyboardButton("🔙 Quay lại", callback_data="budget_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def wallet_selection_menu(wallets) -> InlineKeyboardMarkup:
        """Wallet selection menu for expenses."""
        keyboard = []
        for wallet in wallets:
            balance_decimal = wallet.current_balance if isinstance(wallet.current_balance, str) else str(wallet.current_balance)
            button_text = f"{wallet.currency} - {balance_decimal}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"wallet_{wallet.id}")])
        
        keyboard.append([InlineKeyboardButton("🔙 Quay lại", callback_data="personal_expense_menu")])
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def back_to_budget_menu() -> InlineKeyboardMarkup:
        """Back to budget menu."""
        keyboard = [
            [InlineKeyboardButton("🔙 Quay lại", callback_data="budget_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def back_to_expense_menu() -> InlineKeyboardMarkup:
        """Back to expense menu."""
        keyboard = [
            [InlineKeyboardButton("🔙 Quay lại", callback_data="personal_expense_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def wallet_selection_for_topup(wallets) -> InlineKeyboardMarkup:
        """Wallet selection menu for top up."""
        keyboard = []
        for wallet in wallets:
            balance_decimal = wallet.current_balance if isinstance(wallet.current_balance, str) else str(wallet.current_balance)
            button_text = f"{wallet.currency} - {balance_decimal}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"topup_{wallet.id}")])
        
        keyboard.append([InlineKeyboardButton("🔙 Quay lại", callback_data="budget_menu")])
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def wallet_selection_for_decrease(wallets) -> InlineKeyboardMarkup:
        """Wallet selection menu for decrease."""
        keyboard = []
        for wallet in wallets:
            balance_decimal = wallet.current_balance if isinstance(wallet.current_balance, str) else str(wallet.current_balance)
            button_text = f"{wallet.currency} - {balance_decimal}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"decrease_{wallet.id}")])
        
        keyboard.append([InlineKeyboardButton("🔙 Quay lại", callback_data="budget_menu")])
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def wallet_selection_for_delete(wallets) -> InlineKeyboardMarkup:
        """Wallet selection menu for delete."""
        keyboard = []
        for wallet in wallets:
            balance_decimal = wallet.current_balance if isinstance(wallet.current_balance, str) else str(wallet.current_balance)
            button_text = f"🗑️ {wallet.currency} - {balance_decimal}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_{wallet.id}")])
        
        keyboard.append([InlineKeyboardButton("🔙 Quay lại", callback_data="budget_menu")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def help_menu() -> InlineKeyboardMarkup:
        """Help menu with different help topics."""
        keyboard = [
            [InlineKeyboardButton("💰 Hướng dẫn quản lý ví", callback_data="help_wallet")],
            [InlineKeyboardButton("💸 Hướng dẫn chi tiêu", callback_data="help_expense")],
            [InlineKeyboardButton("👥 Hướng dẫn nhóm", callback_data="help_group")],
            [InlineKeyboardButton("⚙️ Cài đặt & Tài khoản", callback_data="help_settings")],
            [InlineKeyboardButton("📋 Danh sách lệnh", callback_data="help_commands")],
            [InlineKeyboardButton("🔙 Quay lại", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def back_to_help() -> InlineKeyboardMarkup:
        """Back to help menu."""
        keyboard = [
            [InlineKeyboardButton("🔙 Quay lại Help", callback_data="help_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def back_to_settings() -> InlineKeyboardMarkup:
        """Back to settings menu."""
        keyboard = [
            [InlineKeyboardButton("🔙 Quay lại", callback_data="settings_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def group_expense_currency_selection() -> InlineKeyboardMarkup:
        """Currency selection for group expenses."""
        currencies = [
            ("TWD", "🇹🇼 TWD"),
            ("USD", "🇺🇸 USD"),
            ("EUR", "🇪🇺 EUR"),
            ("VND", "🇻🇳 VND")
        ]
        
        keyboard = []
        for code, display in currencies:
            keyboard.append([InlineKeyboardButton(display, callback_data=f"group_currency_{code}")])
        
        keyboard.append([InlineKeyboardButton("❌ Hủy", callback_data="cancel_group_expense")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def group_participant_selection(chat_members: List, selected: List[int] = None) -> InlineKeyboardMarkup:
        """Participant selection for group expenses."""
        if selected is None:
            selected = []
            
        keyboard = []
        
        # Individual participants
        for member in chat_members:
            if member.user.is_bot:
                continue
                
            is_selected = member.user.id in selected
            status = "✅" if is_selected else "⭕"
            callback_data = f"toggle_participant_{member.user.id}"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"{status} {member.user.first_name}", 
                    callback_data=callback_data
                )
            ])
        
        # Control buttons
        control_row = []
        if len(selected) < len([m for m in chat_members if not m.user.is_bot]):
            control_row.append(InlineKeyboardButton("✅ Chọn tất cả", callback_data="select_all_participants"))
        if selected:
            control_row.append(InlineKeyboardButton("❌ Bỏ chọn tất cả", callback_data="deselect_all_participants"))
            
        if control_row:
            keyboard.append(control_row)
            
        # Action buttons
        action_row = []
        if selected:
            action_row.append(InlineKeyboardButton("✅ Xong - Chia đều", callback_data="split_equally"))
        action_row.append(InlineKeyboardButton("❌ Hủy", callback_data="cancel_group_expense"))
        
        keyboard.append(action_row)
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def group_payer_selection(chat_members: List, initiator_id: int) -> InlineKeyboardMarkup:
        """Payer selection for group expenses."""
        keyboard = []
        
        # Individual members as potential payers
        for member in chat_members:
            if member.user.is_bot:
                continue
                
            # Highlight the person who initiated the command
            prefix = "👤" if member.user.id == initiator_id else "👥"
            callback_data = f"select_payer_{member.user.id}"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"{prefix} {member.user.first_name}", 
                    callback_data=callback_data
                )
            ])
        
        # Cancel button
        keyboard.append([
            InlineKeyboardButton("❌ Hủy", callback_data="cancel_group_expense")
        ])
        
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def expense_payment_options(expense_id: int) -> InlineKeyboardMarkup:
        """Payment options for expense participants."""
        keyboard = [
            [InlineKeyboardButton("✅ Đã trả", callback_data=f"pay_now_{expense_id}")],
            [InlineKeyboardButton("⏰ Để cuối ngày", callback_data=f"pay_later_{expense_id}")],
            [InlineKeyboardButton("ℹ️ Chi tiết", callback_data=f"expense_details_{expense_id}")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod  
    def debt_settlement_options(group_id: int) -> InlineKeyboardMarkup:
        """Options for debt settlement."""
        keyboard = [
            [InlineKeyboardButton("💸 Xem nợ tối ưu", callback_data=f"optimized_debts_{group_id}")],
            [InlineKeyboardButton("📊 Xem tất cả nợ", callback_data=f"all_debts_{group_id}")],
            [InlineKeyboardButton("✅ Đánh dấu đã trả", callback_data=f"mark_paid_{group_id}")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def bank_account_menu() -> InlineKeyboardMarkup:
        """Bank account management menu."""
        def _menu_with_account():
            return InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Xem STK", callback_data="list_bank_accounts")],
                [InlineKeyboardButton("🏛️ Đổi STK mặc định", callback_data="set_default_bank")],
                [InlineKeyboardButton("🗑️ Xóa STK", callback_data="delete_bank_account")],
                [InlineKeyboardButton("🔙 Quay lại", callback_data="settings_menu")]
            ])
        def _menu_no_account():
            return InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Thêm STK", callback_data="add_bank_account")],
                [InlineKeyboardButton("🔙 Quay lại", callback_data="settings_menu")]
            ])
        # Accept argument
        def menu(has_account: bool):
            return _menu_with_account() if has_account else _menu_no_account()
        return menu

    @staticmethod
    def payment_settings_menu() -> InlineKeyboardMarkup:
        """Payment settings menu."""
        keyboard = [
            [InlineKeyboardButton("🇻🇳 Nhận chuyển khoản VND", callback_data="toggle_accept_vnd")],
            [InlineKeyboardButton("🔄 Tự động chuyển đổi nợ", callback_data="toggle_auto_convert")],
            [InlineKeyboardButton("🔙 Quay lại", callback_data="settings_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def bank_selection() -> InlineKeyboardMarkup:
        """Bank selection with complete list as buttons."""
        # Major banks first (most popular)
        major_banks = [
            ("VCB", "Vietcombank"),
            ("BIDV", "BIDV"), 
            ("ICB", "VietinBank"),
            ("VBA", "Agribank"),
            ("TCB", "Techcombank"),
            ("MB", "MBBank"),
            ("ACB", "ACB"),
            ("VPB", "VPBank"),
            ("TPB", "TPBank"),
            ("STB", "Sacombank"),
            ("HDB", "HDBank"),
            ("VIB", "VIB"),
            ("SHB", "SHB"),
            ("MSB", "MSB"),
            ("OCB", "OCB"),
            ("EIB", "Eximbank")
        ]
        
        # Other banks
        other_banks = [
            ("VCCB", "VietCapitalBank"),
            ("SCB", "SCB"),
            ("BAB", "BacABank"),
            ("SGICB", "SaigonBank"),
            ("PVCB", "PVcomBank"),
            ("NCB", "NCB"),
            ("SHBVN", "ShinhanBank"),
            ("ABB", "ABBANK"),
            ("VAB", "VietABank"),
            ("NAB", "NamABank"),
            ("PGB", "PGBank"),
            ("VIETBANK", "VietBank"),
            ("BVB", "BaoVietBank"),
            ("SEAB", "SeABank"),
            ("LPB", "LPBank"),
            ("KLB", "KienLongBank"),
            ("COOPBANK", "COOPBANK"),
            ("CAKE", "CAKE"),
            ("UBANK", "Ubank"),
            ("TIMO", "Timo"),
            ("KBANK", "KBank"),
            ("WVN", "Woori"),
            ("CIMB", "CIMB"),
            ("PVDB", "PVcomBank Pay")
        ]
        
        keyboard = []
        
        # Add major banks (2 per row)
        keyboard.append([InlineKeyboardButton("🏛️ **NGÂN HÀNG PHỔ BIẾN**", callback_data="header_major")])
        for i in range(0, len(major_banks), 2):
            row = []
            for j in range(i, min(i + 2, len(major_banks))):
                code, name = major_banks[j]
                row.append(InlineKeyboardButton(name, callback_data=f"select_bank_{code}"))
            keyboard.append(row)
        
        # Toggle for other banks
        keyboard.append([InlineKeyboardButton("📋 Xem thêm ngân hàng khác", callback_data="show_more_banks")])
        
        # Cancel button
        keyboard.append([InlineKeyboardButton("❌ Hủy", callback_data="bank_account_menu")])
        
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def bank_selection_all() -> InlineKeyboardMarkup:
        """Complete bank list when user wants to see all."""
        # All banks combined
        all_banks = [
            ("VCB", "Vietcombank"), ("BIDV", "BIDV"), ("ICB", "VietinBank"), ("VBA", "Agribank"),
            ("TCB", "Techcombank"), ("MB", "MBBank"), ("ACB", "ACB"), ("VPB", "VPBank"),
            ("TPB", "TPBank"), ("STB", "Sacombank"), ("HDB", "HDBank"), ("VIB", "VIB"),
            ("SHB", "SHB"), ("MSB", "MSB"), ("OCB", "OCB"), ("EIB", "Eximbank"),
            ("VCCB", "VietCapitalBank"), ("SCB", "SCB"), ("BAB", "BacABank"), ("SGICB", "SaigonBank"),
            ("PVCB", "PVcomBank"), ("NCB", "NCB"), ("SHBVN", "ShinhanBank"), ("ABB", "ABBANK"),
            ("VAB", "VietABank"), ("NAB", "NamABank"), ("PGB", "PGBank"), ("VIETBANK", "VietBank"),
            ("BVB", "BaoVietBank"), ("SEAB", "SeABank"), ("LPB", "LPBank"), ("KLB", "KienLongBank"),
            ("COOPBANK", "COOPBANK"), ("CAKE", "CAKE"), ("UBANK", "Ubank"), ("TIMO", "Timo"),
            ("KBANK", "KBank"), ("WVN", "Woori"), ("CIMB", "CIMB"), ("PVDB", "PVcomBank Pay")
        ]
        
        keyboard = []
        
        # Add all banks (2 per row)
        for i in range(0, len(all_banks), 2):
            row = []
            for j in range(i, min(i + 2, len(all_banks))):
                code, name = all_banks[j]
                row.append(InlineKeyboardButton(name, callback_data=f"select_bank_{code}"))
            keyboard.append(row)
        
        # Back button
        keyboard.append([InlineKeyboardButton("🔙 Quay lại danh sách chính", callback_data="show_main_banks")])
        keyboard.append([InlineKeyboardButton("❌ Hủy", callback_data="bank_account_menu")])
        
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def payment_options_with_qr(debt_amount: str, qr_url: str, creditor_name: str) -> InlineKeyboardMarkup:
        """Payment options with QR code for debt settlement."""
        keyboard = [
            [InlineKeyboardButton("📱 Xem mã QR", url=qr_url)],
            [InlineKeyboardButton("✅ Đã chuyển", callback_data=f"mark_debt_paid")],
            [InlineKeyboardButton("ℹ️ Chi tiết nợ", callback_data=f"debt_details")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def admin_exchange_rate_menu() -> InlineKeyboardMarkup:
        """Admin menu for exchange rate management."""
        keyboard = [
            [InlineKeyboardButton("📈 Xem tỷ giá hiện tại", callback_data="view_rates")],
            [InlineKeyboardButton("💱 Cập nhật TWD/VND", callback_data="set_twd_vnd_rate")],
            [InlineKeyboardButton("💲 Cập nhật USD/VND", callback_data="set_usd_vnd_rate")],
            [InlineKeyboardButton("⚙️ Tỷ giá khác", callback_data="set_custom_rate")],
            [InlineKeyboardButton("🔙 Quay lại", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def back_to_main_menu() -> InlineKeyboardMarkup:
        """Back to main menu button."""
        keyboard = [
            [InlineKeyboardButton("🔙 Quay lại menu chính", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)
