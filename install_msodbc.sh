#!/bin/bash
# Install Microsoft ODBC Driver for SQL Server 18 on Ubuntu 22.04
# Run this script on your Azure Ubuntu server

echo "🔑 Adding Microsoft GPG key..."
sudo curl https://packages.microsoft.com/keys/microsoft.asc | sudo tee /etc/apt/trusted.gpg.d/microsoft.asc

echo "📦 Adding Microsoft SQL Server repository..."
sudo curl https://packages.microsoft.com/config/ubuntu/22.04/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list

echo "🔄 Updating package list..."
sudo apt update

echo "📦 Installing base ODBC drivers..."
sudo apt install -y unixodbc unixodbc-dev freetds-dev freetds-bin

echo "📥 Installing Microsoft ODBC Driver 18..."
sudo ACCEPT_EULA=Y apt install -y msodbcsql18

echo "🐍 Installing Python packages..."
pip3 install pyodbc aioodbc sqlalchemy

echo "✅ Installation completed!"
echo ""
echo "🧪 Test connection:"
echo "python3 test_azure_connection.py"
