#!/bin/bash
# Install missing ODBC drivers for SQL Server on Ubuntu
echo "🔄 Installing ODBC drivers for SQL Server..."

# Install Microsoft ODBC driver for SQL Server
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
curl https://packages.microsoft.com/config/ubuntu/22.04/prod.list > /etc/apt/sources.list.d/mssql-release.list
sudo apt update
sudo ACCEPT_EULA=Y apt install -y msodbcsql18

# Install unixODBC development headers
sudo apt install -y unixodbc unixodbc-dev

echo "✅ ODBC drivers installed successfully!"
echo ""
echo "🧪 Test connection:"
echo "python3 test_azure_simple.py"
