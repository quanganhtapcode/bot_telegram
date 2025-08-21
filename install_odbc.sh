#!/bin/bash
# Install ODBC drivers and Python packages for Azure SQL Database
# Run this script on your Azure Ubuntu server

echo "🔄 Updating package list..."
sudo apt update

echo "📦 Installing ODBC drivers..."
sudo apt install -y unixodbc unixodbc-dev freetds-dev freetds-bin

echo "🐍 Installing Python packages..."
pip3 install pyodbc aioodbc sqlalchemy

echo "✅ Installation completed!"
echo ""
echo "🧪 Test connection:"
echo "python3 test_azure_simple.py"
