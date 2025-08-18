#!/bin/bash

# Simple bot management script for EC2

BOT_DIR="/home/ubuntu/bot"
LOG_FILE="$BOT_DIR/bot.log"
PID_FILE="$BOT_DIR/bot.pid"

case "$1" in
    start)
        echo "🚀 Starting Telegram Bot..."
        cd $BOT_DIR
        source .venv/bin/activate
        nohup python main.py > $LOG_FILE 2>&1 &
        echo $! > $PID_FILE
        echo "✅ Bot started! PID: $(cat $PID_FILE)"
        echo "📋 Check logs: tail -f $LOG_FILE"
        ;;
    
    stop)
        echo "🛑 Stopping Telegram Bot..."
        if [ -f $PID_FILE ]; then
            PID=$(cat $PID_FILE)
            kill $PID 2>/dev/null
            rm $PID_FILE
            echo "✅ Bot stopped!"
        else
            echo "❌ Bot PID file not found. Checking for running processes..."
            pkill -f "python main.py"
            echo "✅ Killed any running bot processes"
        fi
        ;;
    
    restart)
        echo "🔄 Restarting Telegram Bot..."
        $0 stop
        sleep 2
        $0 start
        ;;
    
    status)
        echo "📊 Bot Status:"
        if [ -f $PID_FILE ]; then
            PID=$(cat $PID_FILE)
            if ps -p $PID > /dev/null; then
                echo "✅ Bot is running (PID: $PID)"
                echo "📈 Memory usage:"
                ps -p $PID -o pid,ppid,user,etime,pmem,pcpu,cmd
            else
                echo "❌ Bot PID file exists but process not found"
                rm $PID_FILE
            fi
        else
            echo "❌ Bot is not running"
        fi
        echo ""
        echo "🔍 All Python processes:"
        ps aux | grep python | grep -v grep
        ;;
    
    logs)
        echo "📋 Bot Logs (last 50 lines):"
        tail -50 $LOG_FILE
        echo ""
        echo "📡 Follow logs: tail -f $LOG_FILE"
        ;;
    
    update)
        echo "🔄 Updating bot..."
        echo "ℹ️  Remember to upload new files first with SCP"
        $0 stop
        sleep 2
        cd $BOT_DIR
        source .venv/bin/activate
        pip install --upgrade -r requirements.txt
        $0 start
        ;;
    
    backup)
        BACKUP_NAME="bot_backup_$(date +%Y%m%d_%H%M%S).tar.gz"
        echo "💾 Creating backup: $BACKUP_NAME"
        cd /home/ubuntu
        tar -czf $BACKUP_NAME bot/ --exclude='bot/.venv' --exclude='bot/__pycache__' --exclude='bot/*.log'
        echo "✅ Backup created: /home/ubuntu/$BACKUP_NAME"
        ;;
    
    *)
        echo "🤖 Telegram Bot Management Script"
        echo ""
        echo "Usage: $0 {start|stop|restart|status|logs|update|backup}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the bot in background"
        echo "  stop    - Stop the bot"
        echo "  restart - Restart the bot"
        echo "  status  - Check bot status and processes"
        echo "  logs    - Show recent logs"
        echo "  update  - Update and restart bot"
        echo "  backup  - Create backup of bot files"
        echo ""
        exit 1
        ;;
esac
