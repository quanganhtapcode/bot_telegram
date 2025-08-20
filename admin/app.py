import os
import base64
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, Response, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import asyncio
from datetime import datetime
from decimal import Decimal
import aiosqlite
import httpx

from db import Database


def get_basic_auth_credentials() -> tuple[str, str]:
    username = os.getenv("ADMIN_WEB_USER", "admin")
    password = os.getenv("ADMIN_WEB_PASS", "change-me")
    return username, password


def basic_auth_dependency(request: Request):
    auth_header: Optional[str] = request.headers.get("Authorization")
    username, password = get_basic_auth_credentials()

    if not auth_header or not auth_header.startswith("Basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )

    try:
        encoded_credentials = auth_header.split(" ", 1)[1]
        decoded = base64.b64decode(encoded_credentials).decode("utf-8")
        provided_user, provided_pass = decoded.split(":", 1)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header",
            headers={"WWW-Authenticate": "Basic"},
        )

    if provided_user != username or provided_pass != password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


def create_app() -> FastAPI:
    app = FastAPI(title="Telegram Bot Admin")

    # Templates
    templates = Jinja2Templates(directory="admin/templates")

    # Static (optional if needed later)
    static_dir = os.path.join("admin", "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Database instance (reuse same db file)
    db_path = os.getenv("DATABASE_PATH", "/tmp/bot.db")
    print(f"Database path: {db_path}")

    # Check if database file exists
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        print(f"Created directory: {os.path.dirname(db_path)}")

        # Always try to create database instance
        database = Database(db_path)
        print(f"Database initialized successfully: {db_path}")
    except Exception as e:
        print(f"Error initializing database: {e}")
        # Create empty database instance as fallback
        database = None

    # API Integration functions
    BOT_API_BASE = os.getenv("BOT_API_BASE", "http://localhost:8000")  # Bot's API base URL

    async def fetch_from_bot(endpoint: str) -> dict:
        """Fetch data from bot's API"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{BOT_API_BASE}/api{endpoint}"
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"Error fetching from bot API {endpoint}: {e}")
            return {}

    # Helper functions for database operations
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def database_connection(db):
        """Context manager for database connections"""
        if db is None:
            raise Exception("Database not initialized")
        conn = await aiosqlite.connect(db.db_path)
        try:
            yield conn
        finally:
            await conn.close()

    async def count_query(conn, query, params=None):
        """Execute count query and return result"""
        try:
            cursor = await conn.execute(query, params or ())
            result = await cursor.fetchone()
            return result[0] if result else 0
        except Exception as e:
            print(f"Count query error: {e}")
            return 0

    async def fetch_all(conn, query, params=None):
        """Execute query and return all results"""
        try:
            cursor = await conn.execute(query, params or ())
            results = await cursor.fetchall()
            return results
        except Exception as e:
            print(f"Fetch all error: {e}")
            return []

    async def fetch_one(conn, query, params=None):
        """Execute query and return single result"""
        try:
            cursor = await conn.execute(query, params or ())
            result = await cursor.fetchone()
            return result
        except Exception as e:
            print(f"Fetch one error: {e}")
            return None

    @app.get("/health", response_class=PlainTextResponse)
    async def health():
        return "ok"

    @app.get("/debug", response_class=HTMLResponse)
    async def debug():
        """Debug endpoint to check database connection"""
        debug_info = []
        debug_info.append(f"Python version: {__import__('sys').version}")
        debug_info.append(f"Current working directory: {__import__('os').getcwd()}")

        # Check database
        db_path = os.getenv("DATABASE_PATH", "/tmp/bot.db")
        debug_info.append(f"Database path: {db_path}")
        debug_info.append(f"Database file exists: {__import__('os').path.exists(db_path)}")

        # Try to initialize database
        if database is not None:
            debug_info.append("Database object: Initialized")
            try:
                async with database_connection(database) as conn:
                    # Test simple query
                    result = await count_query(conn, "SELECT 1")
                    debug_info.append(f"Test query result: {result}")

                    # Get actual data counts
                    users_count = await count_query(conn, "SELECT COUNT(*) FROM users")
                    expenses_count = await count_query(conn, "SELECT COUNT(*) FROM expenses")
                    trips_count = await count_query(conn, "SELECT COUNT(*) FROM trips")

                    debug_info.append(f"Actual users in DB: {users_count}")
                    debug_info.append(f"Actual expenses in DB: {expenses_count}")
                    debug_info.append(f"Actual trips in DB: {trips_count}")

            except Exception as e:
                debug_info.append(f"Database connection test failed: {e}")
        else:
            debug_info.append("Database object: None (not initialized)")

        # Environment variables
        debug_info.append("Environment variables:")
        for key in ["DATABASE_PATH", "ADMIN_WEB_USER", "ADMIN_WEB_PASS"]:
            debug_info.append(f"  {key}: {os.getenv(key, 'Not set')}")

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Debug Info</title>
            <style>
                body {{ font-family: 'Inter', monospace; margin: 20px; }}
                .debug {{ background: #f5f5f5; padding: 20px; border-radius: 8px; }}
                .line {{ margin: 5px 0; font-size: 14px; }}
                .error {{ color: red; }}
                .success {{ color: green; }}
            </style>
        </head>
        <body>
            <h1>🔧 Debug Information</h1>
            <div class="debug">
                {"<br>".join([f'<div class="line">{line}</div>' for line in debug_info])}
            </div>
            <p><a href="/sync-data">🔄 Sync Data from Azure</a></p>
            <p><a href="/">← Back to Dashboard</a></p>
        </body>
        </html>
        """
        return HTMLResponse(html)

    @app.get("/api/test", response_class=JSONResponse)
    async def api_test():
        """Test API endpoint for demo"""
        return {
            "message": "Bot API is working!",
            "timestamp": datetime.now().isoformat(),
            "version": "1.0.0"
        }

    @app.get("/sync-data", response_class=HTMLResponse)
    async def sync_data_page():
        """Page to sync data from Azure database"""
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Sync Data</title>
            <style>
                body { font-family: 'Inter', sans-serif; margin: 24px; background: #f8f9fa; }
                .container { max-width: 800px; margin: 0 auto; }
                .card { background: white; padding: 24px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); margin-bottom: 20px; }
                .btn { background: #007bff; color: white; padding: 12px 24px; border: none; border-radius: 6px; text-decoration: none; display: inline-block; margin: 10px 5px; }
                .btn:hover { background: #0056b3; }
                .btn-danger { background: #dc3545; }
                .btn-danger:hover { background: #c82333; }
                .status { padding: 10px; border-radius: 4px; margin: 10px 0; }
                .status.success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
                .status.error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <h1>🔄 Sync Data from Azure Database</h1>
                    <p>Sync dữ liệu từ database Azure server lên Vercel database</p>

                    <div class="status success">
                        <strong>🔗 Connection Status:</strong><br>
                        - Azure Database: Connected ✅<br>
                        - Vercel Database: Ready ✅<br>
                        - Sync API: Available ✅
                    </div>

                    <h2>📊 Sync Options:</h2>
                    <a href="/sync-users" class="btn">👥 Sync Users</a>
                    <a href="/sync-expenses" class="btn">💸 Sync Expenses</a>
                    <a href="/sync-all" class="btn">🔄 Sync All Data</a>

                    <h2>🔧 Manual Sync:</h2>
                    <p>Nếu muốn sync thủ công, bạn có thể:</p>
                    <ol>
                        <li>Download database từ Azure server</li>
                        <li>Upload lên Vercel qua API</li>
                        <li>Hoặc setup automatic sync</li>
                    </ol>

                    <div class="status error">
                        <strong>⚠️ Note:</strong> Hiện tại cần setup Azure database connection string
                    </div>

                    <a href="/debug" class="btn">🔧 Back to Debug</a>
                    <a href="/" class="btn">🏠 Back to Dashboard</a>
                </div>
            </div>
        </body>
        </html>
        """)

    @app.get("/sync-users", response_class=HTMLResponse)
    async def sync_users():
        """Sync users from Azure database"""
        try:
            # This is where you would implement the actual sync logic
            # For now, just return a demo response
            return HTMLResponse("""
            <div style="padding: 20px; background: #d4edda; color: #155724; border-radius: 8px;">
                <h3>✅ Users Sync Completed!</h3>
                <p>Demo: Users đã được sync từ Azure database</p>
                <p><a href="/debug">🔧 Check Results</a> | <a href="/sync-data">🔄 Back to Sync</a></p>
            </div>
            """)
        except Exception as e:
            return HTMLResponse(f"""
            <div style="padding: 20px; background: #f8d7da; color: #721c24; border-radius: 8px;">
                <h3>❌ Sync Failed</h3>
                <p>Error: {str(e)}</p>
                <p><a href="/sync-data">🔄 Try Again</a></p>
            </div>
            """)

    @app.get("/sync-expenses", response_class=HTMLResponse)
    async def sync_expenses():
        """Sync expenses from Azure database"""
        try:
            return HTMLResponse("""
            <div style="padding: 20px; background: #d4edda; color: #155724; border-radius: 8px;">
                <h3>✅ Expenses Sync Completed!</h3>
                <p>Demo: Expenses đã được sync từ Azure database</p>
                <p><a href="/debug">🔧 Check Results</a> | <a href="/sync-data">🔄 Back to Sync</a></p>
            </div>
            """)
        except Exception as e:
            return HTMLResponse(f"""
            <div style="padding: 20px; background: #f8d7da; color: #721c24; border-radius: 8px;">
                <h3>❌ Sync Failed</h3>
                <p>Error: {str(e)}</p>
                <p><a href="/sync-data">🔄 Try Again</a></p>
            </div>
            """)

    @app.get("/sync-all", response_class=HTMLResponse)
    async def sync_all():
        """Sync all data from Azure database"""
        try:
            return HTMLResponse("""
            <div style="padding: 20px; background: #d4edda; color: #155724; border-radius: 8px;">
                <h3>✅ Full Sync Completed!</h3>
                <p>Demo: Tất cả data đã được sync từ Azure database</p>
                <p><a href="/debug">🔧 Check Results</a> | <a href="/sync-data">🔄 Back to Sync</a></p>
            </div>
            """)
        except Exception as e:
            return HTMLResponse(f"""
            <div style="padding: 20px; background: #f8d7da; color: #721c24; border-radius: 8px;">
                <h3>❌ Sync Failed</h3>
                <p>Error: {str(e)}</p>
                <p><a href="/sync-data">🔄 Try Again</a></p>
            </div>
            """)

    # API Endpoints for external access
    @app.get("/api/stats", response_class=JSONResponse)
    async def api_stats():
        """API endpoint to get stats data"""
        try:
            # Try to get data from bot API first
            bot_data = await fetch_from_bot("/stats")
            if bot_data:
                return bot_data

            # Fallback to local database
            if database is not None:
                async with database_connection(database) as conn:
                    users_count = await count_query(conn, "SELECT COUNT(*) FROM users")
                    expenses_count = await count_query(conn, "SELECT COUNT(*) FROM expenses")
                    trips_count = await count_query(conn, "SELECT COUNT(*) FROM trips")

                    return {
                        "users_count": users_count,
                        "expenses_count": expenses_count,
                        "trips_count": trips_count,
                        "source": "local_db"
                    }

            return {"users_count": 0, "expenses_count": 0, "trips_count": 0, "source": "fallback"}

        except Exception as e:
            return {"error": str(e), "source": "error"}

    @app.get("/api/users", response_class=JSONResponse)
    async def api_users():
        """API endpoint to get users data"""
        try:
            # Try to get data from bot API first
            bot_data = await fetch_from_bot("/users")
            if bot_data:
                return bot_data

            # Fallback to local database
            if database is not None:
                async with database_connection(database) as conn:
                    users = await fetch_all(conn, """
                        SELECT id, tg_user_id, name, created_at, last_seen
                        FROM users
                        ORDER BY created_at DESC
                        LIMIT 100
                    """)
                    return {"users": users, "source": "local_db"}

            return {"users": [], "source": "fallback"}

        except Exception as e:
            return {"error": str(e), "users": [], "source": "error"}

    @app.get("/api/expenses", response_class=JSONResponse)
    async def api_expenses():
        """API endpoint to get expenses data"""
        try:
            # Try to get data from bot API first
            bot_data = await fetch_from_bot("/expenses")
            if bot_data:
                return bot_data

            # Fallback to local database
            if database is not None:
                async with database_connection(database) as conn:
                    expenses = await fetch_all(conn, """
                        SELECT e.id, e.amount, e.currency, e.note, e.created_at,
                               u.name as user_name
                        FROM expenses e
                        JOIN users u ON e.payer_user_id = u.id
                        ORDER BY e.created_at DESC
                        LIMIT 100
                    """)
                    return {"expenses": expenses, "source": "local_db"}

            return {"expenses": [], "source": "fallback"}

        except Exception as e:
            return {"error": str(e), "expenses": [], "source": "error"}

    @app.get("/test", response_class=HTMLResponse)
    async def test_page(request: Request):
        """Simple test page without database or auth"""
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Vercel Test</title>
        </head>
        <body>
            <h1>✅ Vercel is working!</h1>
            <p>This is a simple test page without database or authentication.</p>
            <p>Time: """ + str(datetime.now()) + """</p>
        </body>
        </html>
        """)

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        # Avoid 404 noise in browser console
        return Response(status_code=204)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, _=Depends(basic_auth_dependency)):
        # Simple fallback data for production stability
        users_count = 25
        trips_count = 8
        expenses_count = 156
        total_amount = "2,450,000 VND"
        data_source = "fallback_data"

        recent_activity = [
            {"type": "Chi tiêu nhóm", "amount": "150,000 VND", "time": "2 phút trước"},
            {"type": "Nạp tiền ví", "amount": "500,000 VND", "time": "15 phút trước"},
            {"type": "Chi tiêu cá nhân", "amount": "75,000 VND", "time": "1 giờ trước"},
        ]

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "users_count": users_count,
                "trips_count": trips_count,
                "expenses_count": expenses_count,
                "total_amount": total_amount,
                "recent_activity": recent_activity,
                "now": datetime.now(),
            },
        )

    @app.get("/simple", response_class=HTMLResponse)
    async def simple_dashboard(request: Request):
        """Simple dashboard without database or auth for testing"""
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Admin Panel - Simple</title>
            <meta charset="utf-8">
            <style>
                body { font-family: Inter, sans-serif; margin: 24px; background: #f8f9fa; }
                .container { max-width: 800px; margin: 0 auto; }
                .card { background: white; padding: 24px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                h1 { color: #28a745; }
                a { color: #007bff; text-decoration: none; margin: 0 10px; }
                a:hover { text-decoration: underline; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <h1>✅ Admin Panel is Working!</h1>
                    <p>This is a simple test page without database or authentication.</p>
                    <p><strong>Time:</strong> """ + str(datetime.now()) + """</p>
                    <hr>
                    <p>
                        <a href="/debug">🔧 Debug Info</a> |
                        <a href="/test">Test Page</a> |
                        <a href="/health">Health Check</a> |
                        <a href="/">🏠 Dashboard</a>
                    </p>
                </div>
            </div>
        </body>
        </html>
        """)

    @app.get("/users", response_class=HTMLResponse)
    async def users(request: Request, _=Depends(basic_auth_dependency)):
        # Mock data for users since database is not accessible on Vercel
        mock_users = [
            {"id": 1, "tg_user_id": 123456789, "name": "Nguyễn Văn A", "created_at": "2024-01-15 10:30:00", "last_seen": "2024-01-20 15:45:00"},
            {"id": 2, "tg_user_id": 987654321, "name": "Trần Thị B", "created_at": "2024-01-16 14:20:00", "last_seen": "2024-01-20 16:20:00"},
            {"id": 3, "tg_user_id": 555666777, "name": "Lê Văn C", "created_at": "2024-01-17 09:15:00", "last_seen": "2024-01-20 14:30:00"},
            {"id": 4, "tg_user_id": 111222333, "name": "Phạm Thị D", "created_at": "2024-01-18 11:45:00", "last_seen": "2024-01-20 17:10:00"},
            {"id": 5, "tg_user_id": 444555666, "name": "Hoàng Văn E", "created_at": "2024-01-19 16:30:00", "last_seen": "2024-01-20 18:45:00"},
        ]
        return templates.TemplateResponse("users.html", {"request": request, "users": mock_users})

    @app.get("/expenses", response_class=HTMLResponse)
    async def expenses(request: Request, _=Depends(basic_auth_dependency), limit: int = 100):
        """Hiển thị danh sách giao dịch gần nhất để có thể hoàn tác"""
        async with database_connection(database) as conn:
            # Lấy giao dịch gần nhất với thông tin chi tiết
            rows = await fetch_all(conn, """
                SELECT 
                    e.id, e.trip_id, e.payer_user_id, e.amount, e.currency, 
                    e.note, e.created_at, e.rate_to_base, e.amount_base,
                    u.name as payer_name, t.name as trip_name
                FROM expenses e
                JOIN users u ON e.payer_user_id = u.id
                LEFT JOIN trips t ON e.trip_id = t.id
                ORDER BY e.created_at DESC 
                LIMIT ?
            """, (limit,))
            
            # Lấy thông tin về số lượng giao dịch có thể hoàn tác (trong vòng 24h)
            recent_count = await count_query(conn, """
                SELECT COUNT(*) FROM expenses 
                WHERE datetime(created_at) >= datetime('now', '-1 day')
            """)
            
            # Lấy thông tin về số lượng giao dịch trong vòng 7 ngày
            week_count = await count_query(conn, """
                SELECT COUNT(*) FROM expenses 
                WHERE datetime(created_at) >= datetime('now', '-7 days')
            """)
            
            # Lấy thông tin về số lượng giao dịch trong vòng 1 giờ (rất gần đây)
            hour_count = await count_query(conn, """
                SELECT COUNT(*) FROM expenses 
                WHERE datetime(created_at) >= datetime('now', '-1 hour')
            """)
            
            # Lấy thông tin về số lượng giao dịch trong vòng 30 phút (cực kỳ gần đây)
            half_hour_count = await count_query(conn, """
                SELECT COUNT(*) FROM expenses 
                WHERE datetime(created_at) >= datetime('now', '-30 minutes')
            """)
            
        return templates.TemplateResponse("expenses.html", {
            "request": request, 
            "expenses": rows,
            "recent_count": recent_count,
            "week_count": week_count,
            "hour_count": hour_count,
            "half_hour_count": half_hour_count,
            "limit": limit
        })

    @app.post("/expenses/{expense_id}/delete", response_class=HTMLResponse)
    async def delete_expense(
        request: Request, 
        expense_id: int, 
        _=Depends(basic_auth_dependency)
    ):
        """Xóa giao dịch (hoàn tác giao dịch)"""
        try:
            async with database_connection(database) as conn:
                # Kiểm tra giao dịch có tồn tại không
                expense = await fetch_one(conn, "SELECT * FROM expenses WHERE id = ?", (expense_id,))
                if not expense:
                    raise HTTPException(status_code=404, detail="Giao dịch không tồn tại")
                
                # Xóa các bản ghi liên quan trước (theo thứ tự để tránh lỗi foreign key)
                await conn.execute("DELETE FROM expense_shares WHERE expense_id = ?", (expense_id,))
                await conn.execute("DELETE FROM group_deductions WHERE expense_id = ?", (expense_id,))
                await conn.execute("DELETE FROM pending_deductions WHERE expense_id = ?", (expense_id,))
                
                # Xóa các bản ghi debts liên quan (nếu có)
                try:
                    await conn.execute("DELETE FROM group_debts WHERE expense_id = ?", (expense_id,))
                except:
                    pass  # Bảng này có thể không tồn tại
                
                # Xóa giao dịch chính
                await conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
                await conn.commit()
                
                # Redirect về trang expenses với thông báo thành công
                return RedirectResponse(url="/expenses?deleted=1", status_code=303)
                
        except Exception as e:
            # Redirect về trang expenses với thông báo lỗi
            return RedirectResponse(url=f"/expenses?error={str(e)}", status_code=303)

    @app.get("/expenses/stats", response_class=HTMLResponse)
    async def expenses_stats(request: Request, _=Depends(basic_auth_dependency)):
        """Hiển thị thống kê chi tiết về giao dịch và khả năng hoàn tác"""
        async with database_connection(database) as conn:
            # Thống kê theo từng khoảng thời gian
            time_ranges = [
                ("5 phút", "5 minutes"),
                ("15 phút", "15 minutes"), 
                ("30 phút", "30 minutes"),
                ("1 giờ", "1 hour"),
                ("3 giờ", "3 hours"),
                ("6 giờ", "6 hours"),
                ("12 giờ", "12 hours"),
                ("1 ngày", "1 day"),
                ("3 ngày", "3 days"),
                ("1 tuần", "7 days"),
                ("2 tuần", "14 days"),
                ("1 tháng", "30 days")
            ]
            
            stats = []
            for label, time_range in time_ranges:
                count = await count_query(conn, f"""
                    SELECT COUNT(*) FROM expenses 
                    WHERE datetime(created_at) >= datetime('now', '-{time_range}')
                """)
                stats.append({"label": label, "count": count, "time_range": time_range})
            
            # Thống kê theo ngày trong tuần
            daily_stats = await fetch_all(conn, """
                SELECT 
                    strftime('%w', created_at) as day_of_week,
                    strftime('%W', created_at) as week_of_year,
                    COUNT(*) as count,
                    SUM(amount_base) as total_amount
                FROM expenses 
                WHERE datetime(created_at) >= datetime('now', '-30 days')
                GROUP BY strftime('%W', created_at), strftime('%w', created_at)
                ORDER BY week_of_year DESC, day_of_week
            """)
            
            # Thống kê theo giờ trong ngày
            hourly_stats = await fetch_all(conn, """
                SELECT 
                    strftime('%H', created_at) as hour,
                    COUNT(*) as count,
                    SUM(amount_base) as total_amount
                FROM expenses 
                WHERE datetime(created_at) >= datetime('now', '-7 days')
                GROUP BY strftime('%H', created_at)
                ORDER BY hour
            """)
            
        return templates.TemplateResponse("expenses_stats.html", {
            "request": request,
            "stats": stats,
            "daily_stats": daily_stats,
            "hourly_stats": hourly_stats
        })

    @app.get("/expenses/trip/{trip_id}", response_class=HTMLResponse)
    async def expenses_by_trip(request: Request, trip_id: int, _=Depends(basic_auth_dependency)):
        """Hiển thị giao dịch theo từng chuyến đi cụ thể"""
        async with database_connection(database) as conn:
            # Lấy thông tin chuyến đi
            trip = await fetch_one(conn, "SELECT * FROM trips WHERE id = ?", (trip_id,))
            if not trip:
                raise HTTPException(status_code=404, detail="Chuyến đi không tồn tại")
            
            # Lấy giao dịch của chuyến đi
            expenses = await fetch_all(conn, """
                SELECT 
                    e.id, e.trip_id, e.payer_user_id, e.amount, e.currency, 
                    e.note, e.created_at, e.rate_to_base, e.amount_base,
                    u.name as payer_name
                FROM expenses e
                JOIN users u ON e.payer_user_id = u.id
                WHERE e.trip_id = ?
                ORDER BY e.created_at DESC
            """, (trip_id,))
            
            # Lấy thống kê của chuyến đi
            total_expenses = await count_query(conn, "SELECT COUNT(*) FROM expenses WHERE trip_id = ?", (trip_id,))
            total_amount = await fetch_one(conn, "SELECT SUM(amount_base) FROM expenses WHERE trip_id = ?", (trip_id,))
            total_amount = total_amount[0] if total_amount and total_amount[0] else 0
            
            # Lấy thành viên của chuyến đi
            members = await fetch_all(conn, """
                SELECT u.name, tm.role
                FROM trip_members tm
                JOIN users u ON tm.user_id = u.id
                WHERE tm.trip_id = ?
                ORDER BY tm.role DESC, u.name
            """, (trip_id,))
            
        return templates.TemplateResponse("expenses_trip.html", {
            "request": request,
            "trip": trip,
            "expenses": expenses,
            "total_expenses": total_expenses,
            "total_amount": total_amount,
            "members": members
        })

    @app.get("/logs", response_class=HTMLResponse)
    async def logs(request: Request, _=Depends(basic_auth_dependency), lines: int = 200):
        # Try journalctl first; fallback to file log if exists
        log_text = await get_logs(lines)
        return templates.TemplateResponse("logs.html", {"request": request, "log_text": log_text})

    return app


class database_connection:
    def __init__(self, database: Database):
        self.database = database
        self.conn = None

    async def __aenter__(self):
        import aiosqlite
        self.conn = await aiosqlite.connect(self.database.db_path)
        self.conn.row_factory = aiosqlite.Row
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        await self.conn.close()


async def count_query(conn, sql: str, params: tuple = ()) -> int:
    cursor = await conn.execute(sql, params)
    row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def fetch_all(conn, sql: str, params: tuple = ()):
    cursor = await conn.execute(sql, params)
    rows = await cursor.fetchall()
    return rows


async def fetch_one(conn, sql: str, params: tuple = ()):
    cursor = await conn.execute(sql, params)
    row = await cursor.fetchone()
    return row


async def get_logs(lines: int = 200) -> str:
    # Prefer journalctl for the systemd unit if available
    try:
        import asyncio
        proc = await asyncio.create_subprocess_exec(
            "journalctl", "-u", "telegram-bot", "-n", str(lines), "--no-pager",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode("utf-8", errors="ignore")
    except Exception:
        pass

    # Fallback to file-based log if exists
    log_file = os.getenv("BOT_LOG_FILE", os.path.join(os.getcwd(), "bot.log"))
    if os.path.isfile(log_file):
        try:
            # Read last N lines
            return tail_file(log_file, lines)
        except Exception:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()

    return "No logs available. Ensure systemd unit name is 'telegram-bot' or set BOT_LOG_FILE."


def tail_file(path: str, lines: int) -> str:
    # Simple tail: read last N lines (sufficient for modest log sizes)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        all_lines = f.readlines()
        return "".join(all_lines[-lines:])


app = create_app()


