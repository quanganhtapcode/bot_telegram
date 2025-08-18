# 🚀 Deploy Telegram Bot lên Azure

## 📋 Yêu cầu
- File key SSH: `C:\Users\PC\Downloads\ec2.pem`
- IP Azure: `172.188.96.174`
- Username: `azureuser`

## 🎯 Deploy

### Bước 1: Chạy script deploy
```bash
deploy.bat
```

### Bước 2: SSH vào Azure và cài đặt
```bash
# Kết nối SSH
ssh -i "C:\Users\PC\Downloads\ec2.pem" azureuser@172.188.96.174

# Vào thư mục bot
cd /home/azureuser/bot

# Cài đặt Python
sudo apt update
sudo apt install -y python3.11 python3.11-pip python3.11-venv

# Tạo môi trường ảo
python3.11 -m venv .venv
source .venv/bin/activate

# Cài đặt dependencies
pip install -r requirements.txt

# Tạo file .env (QUAN TRỌNG!)
cp env_template.txt .env
nano .env
# Cập nhật BOT_TOKEN thật của bạn

# Chạy bot
./bot_manager.sh start
```

## 🔍 Lệnh hữu ích
```bash
# Kiểm tra trạng thái
ssh -i "C:\Users\PC\Downloads\ec2.pem" azureuser@172.188.96.174 "cd /home/azureuser/bot && ./bot_manager.sh status"

# Xem logs
ssh -i "C:\Users\PC\Downloads\ec2.pem" azureuser@172.188.96.174 "cd /home/azureuser/bot && ./bot_manager.sh logs"

# Dừng bot
ssh -i "C:\Users\PC\Downloads\ec2.pem" azureuser@172.188.96.174 "cd /home/azureuser/bot && ./bot_manager.sh stop"
```

## ⚠️ Lưu ý
- **PHẢI** tạo file `.env` với BOT_TOKEN thật
- Đảm bảo file key SSH có quyền đọc đúng
- Môi trường ảo phải được kích hoạt trước khi chạy bot
