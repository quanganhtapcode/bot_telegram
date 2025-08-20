import os
import base64
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import asyncio
from datetime import datetime
from decimal import Decimal

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
    db_path = os.getenv("DATABASE_PATH", "bot.db")
    database = Database(db_path)

    @app.get("/health", response_class=PlainTextResponse)
    async def health():
        return "ok"

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        # Avoid 404 noise in browser console
        return Response(status_code=204)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, _=Depends(basic_auth_dependency)):
        # Basic stats
        async with database_connection(database) as conn:
            users_count = await count_query(conn, "SELECT COUNT(*) FROM users")
            trips_count = await count_query(conn, "SELECT COUNT(*) FROM trips")
            expenses_count = await count_query(conn, "SELECT COUNT(*) FROM expenses")

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "users_count": users_count,
                "trips_count": trips_count,
                "expenses_count": expenses_count,
                "now": datetime.now(),
            },
        )

    @app.get("/users", response_class=HTMLResponse)
    async def users(request: Request, _=Depends(basic_auth_dependency)):
        async with database_connection(database) as conn:
            rows = await fetch_all(conn, "SELECT id, tg_user_id, name, created_at, last_seen FROM users ORDER BY created_at DESC LIMIT 200")
        return templates.TemplateResponse("users.html", {"request": request, "users": rows})

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


