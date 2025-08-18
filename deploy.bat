@echo off
echo Deploying to Azure...
echo IP: 172.188.96.174
echo Key: C:\Users\PC\Downloads\ec2.pem
echo User: azureuser

REM Create directory
ssh -i "C:\Users\PC\Downloads\ec2.pem" azureuser@172.188.96.174 "mkdir -p /home/azureuser/bot"

REM Backup database trước khi deploy
echo Backing up database...
ssh -i "C:\Users\PC\Downloads\ec2.pem" azureuser@172.188.96.174 "cd /home/azureuser/bot && if [ -f bot.db ]; then cp bot.db bot.db.backup.$(date +%Y%m%d_%H%M%S); fi"

REM Upload files (KHÔNG upload database)
scp -i "C:\Users\PC\Downloads\ec2.pem" -r "C:\Users\PC\Desktop\bot\*.py" azureuser@172.188.96.174:/home/azureuser/bot/
scp -i "C:\Users\PC\Downloads\ec2.pem" -r "C:\Users\PC\Desktop\bot\requirements.txt" azureuser@172.188.96.174:/home/azureuser/bot/
scp -i "C:\Users\PC\Downloads\ec2.pem" -r "C:\Users\PC\Desktop\bot\services" azureuser@172.188.96.174:/home/azureuser/bot/
scp -i "C:\Users\PC\Downloads\ec2.pem" -r "C:\Users\PC\Desktop\bot\handlers" azureuser@172.188.96.174:/home/azureuser/bot/
scp -i "C:\Users\PC\Downloads\ec2.pem" -r "C:\Users\PC\Desktop\bot\bot_manager.sh" azureuser@172.188.96.174:/home/azureuser/bot/
scp -i "C:\Users\PC\Downloads\ec2.pem" -r "C:\Users\PC\Desktop\bot\env_template.txt" azureuser@172.188.96.174:/home/azureuser/bot/

REM Không upload database - giữ nguyên database cũ
echo Database preserved - not overwritten

echo Deploy completed!
echo Next steps:
echo 1. SSH: ssh -i "C:\Users\PC\Downloads\ec2.pem" azureuser@172.188.96.174
echo 2. cd /home/azureuser/bot
echo 3. Restart bot: sudo systemctl restart telegram-bot
echo 4. Check status: sudo systemctl status telegram-bot
pause
