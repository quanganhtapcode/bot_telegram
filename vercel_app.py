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
    print("Successfully imported admin.app")
except Exception as e:
    # Fallback app if import fails
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    app = FastAPI(title="Telegram Bot Admin")

    print(f"Failed to import admin.app: {e}")
    import traceback
    traceback.print_exc()

    @app.get("/", response_class=HTMLResponse)
    async def root():
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Admin Panel - Error</title>
            <style>
                body {{ font-family: Inter, sans-serif; margin: 24px; background: #f8f9fa; }}
                .container {{ max-width: 800px; margin: 0 auto; }}
                .card {{ background: white; padding: 24px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                .error {{ color: #dc3545; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <h1 class="error">❌ Admin Panel Import Error</h1>
                    <p><strong>Error:</strong> {str(e)}</p>
                    <details>
                        <summary>Stack Trace</summary>
                        <pre>{traceback.format_exc()}</pre>
                    </details>
                </div>
            </div>
        </body>
        </html>
        """)

    @app.get("/health")
    async def health():
        return {"status": "error", "error": str(e)}

    @app.get("/debug")
    async def debug():
        return {"error": str(e), "traceback": traceback.format_exc()}

# For Vercel serverless functions
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
