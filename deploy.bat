@echo off
chcp 65001 >nul
setlocal

set "IP=172.188.96.174"
set "KEY=C:\Users\PC\Downloads\ec2.pem"
set "USER=azureuser"
set "REMOTE_DIR=/home/azureuser/bot"
set "PROJECT_DIR=C:\Users\PC\Desktop\bot"
set "GITHUB_REPO=https://github.com/quanganhtapcode/bot_telegram.git"

echo Deploying to Azure...
echo IP: %IP%
echo Key: %KEY%
echo User: %USER%
echo GitHub Repo: %GITHUB_REPO%

REM Check required tools
where ssh >nul 2>nul || (echo ERROR: ssh not found in PATH. Install OpenSSH Client in Windows Optional Features. & goto :end)
where scp >nul 2>nul || (echo ERROR: scp not found in PATH. Install OpenSSH Client in Windows Optional Features. & goto :end)
where git >nul 2>nul || (echo ERROR: git not found in PATH. Install Git for Windows. & goto :end)

REM Git operations - Commit and Push to GitHub
echo.
echo ========================================
echo Pushing code to GitHub...
echo ========================================
cd /d "%PROJECT_DIR%"

REM Check if git repository exists
if not exist ".git" (
    echo Initializing git repository...
    git init
    git remote add origin %GITHUB_REPO%
)

REM Add all files
echo Adding files to git...
git add .
if errorlevel 1 goto :git_err

REM Commit changes
echo Committing changes...
git commit -m "Auto-deploy: %date% %time%" || echo "No changes to commit"

REM Push to GitHub
echo Pushing to GitHub...
git push -u origin main || (
    echo Trying to push to master branch...
    git push -u origin master || echo "Push failed but continuing with Azure deploy..."
)

echo GitHub operations completed!
echo.

REM Create directory on server
ssh -o StrictHostKeyChecking=no -i "%KEY%" %USER%@%IP% "mkdir -p %REMOTE_DIR%"
if errorlevel 1 goto :err

REM Backup database before deploy
echo Backing up database...
ssh -o StrictHostKeyChecking=no -i "%KEY%" %USER%@%IP% "cd %REMOTE_DIR% && if [ -f bot.db ]; then cp bot.db bot.db.backup.$(date +%Y%m%d_%H%M%S); fi"
if errorlevel 1 goto :err

REM Upload files (excluding database)
echo Uploading files...
scp -o StrictHostKeyChecking=no -i "%KEY%" "%PROJECT_DIR%\*.py" %USER%@%IP%:%REMOTE_DIR%/
if errorlevel 1 goto :err
scp -o StrictHostKeyChecking=no -i "%KEY%" "%PROJECT_DIR%\requirements.txt" %USER%@%IP%:%REMOTE_DIR%/
if errorlevel 1 goto :err
scp -o StrictHostKeyChecking=no -i "%KEY%" -r "%PROJECT_DIR%\services" %USER%@%IP%:%REMOTE_DIR%/
if errorlevel 1 goto :err
scp -o StrictHostKeyChecking=no -i "%KEY%" -r "%PROJECT_DIR%\handlers" %USER%@%IP%:%REMOTE_DIR%/
if errorlevel 1 goto :err
scp -o StrictHostKeyChecking=no -i "%KEY%" -r "%PROJECT_DIR%\admin" %USER%@%IP%:%REMOTE_DIR%/
if errorlevel 1 goto :err
scp -o StrictHostKeyChecking=no -i "%KEY%" "%PROJECT_DIR%\bot_manager.sh" %USER%@%IP%:%REMOTE_DIR%/
if errorlevel 1 goto :err
if exist "%PROJECT_DIR%\env_template.txt" scp -o StrictHostKeyChecking=no -i "%KEY%" "%PROJECT_DIR%\env_template.txt" %USER%@%IP%:%REMOTE_DIR%/

echo Database preserved - not overwritten
echo Deploy completed!
echo Next steps:
echo 1. SSH: ssh -i "%KEY%" %USER%@%IP%
echo 2. cd %REMOTE_DIR%
echo 3. Restart bot: sudo systemctl restart telegram-bot
echo 4. Check status: sudo systemctl status telegram-bot

:git_err
echo GitHub operations failed. See errors above.
echo Please check your git configuration and try again.
goto :end

:err
echo Deployment failed. See errors above.

:end
endlocal
pause
