"""
Vercel deployment entry point for the admin panel.
This file is used by Vercel to run the FastAPI application.
"""
import os
import sys

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the admin app
from admin.app import app

# For Vercel serverless functions
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
