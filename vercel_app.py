"""
Vercel deployment entry point for the admin panel.
This file is used by Vercel to run the FastAPI application.
"""
import os
import sys

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    # Import the admin app
    from admin.app import app
except Exception as e:
    # Fallback app if import fails
    from fastapi import FastAPI
    app = FastAPI(title="Telegram Bot Admin")
    
    @app.get("/")
    async def root():
        return {"message": "Admin panel is starting up...", "error": str(e)}
    
    @app.get("/health")
    async def health():
        return {"status": "ok"}

# For Vercel serverless functions
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
