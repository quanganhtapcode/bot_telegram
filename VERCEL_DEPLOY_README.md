# 🚀 Deploy Admin Panel lên Vercel

## 📋 Yêu cầu

- Tài khoản [Vercel](https://vercel.com) (miễn phí)
- Domain `telegram.quanganh.org` (đã có sẵn)
- Repository GitHub đã push code

## 🔧 Các bước thực hiện

### 1. Chuẩn bị Repository

Đảm bảo repository có các file sau:
- `vercel_app.py` - Entry point cho Vercel
- `vercel.json` - Cấu hình Vercel
- `admin/requirements.txt` - Dependencies cho admin panel
- `runtime.txt` - Phiên bản Python

### 2. Deploy lên Vercel

1. **Đăng nhập Vercel**: Truy cập [vercel.com](https://vercel.com) và đăng nhập

2. **Import Project**: 
   - Click "New Project"
   - Chọn "Import Git Repository"
   - Chọn repository `quanganhtapcode/bot_telegram`

3. **Cấu hình Project**:
   - **Framework Preset**: Other
   - **Root Directory**: `./` (để lại trống)
   - **Build Command**: `pip install -r admin/requirements.txt`
   - **Output Directory**: `.`
   - **Install Command**: `pip install -r admin/requirements.txt`

4. **Environment Variables** (nếu cần):
   ```
   ADMIN_WEB_USER=admin
   ADMIN_WEB_PASS=your-secure-password
   DATABASE_PATH=./bot.db
   ```

5. **Deploy**: Click "Deploy"

### 3. Cấu hình Domain

1. **Thêm Domain**:
   - Vào Project Settings > Domains
   - Thêm domain: `telegram.quanganh.org`

2. **Cấu hình DNS**:
   - Thêm CNAME record:
     ```
     Type: CNAME
     Name: telegram
     Value: cname.vercel-dns.com
     ```

### 4. Kiểm tra hoạt động

Sau khi deploy thành công, truy cập:
- **Admin Panel**: `https://telegram.quanganh.org`
- **Dashboard**: `https://telegram.quanganh.org/`
- **Quản lý giao dịch**: `https://telegram.quanganh.org/expenses`
- **Thống kê**: `https://telegram.quanganh.org/expenses/stats`

## 🔒 Bảo mật

- **Authentication**: Sử dụng Basic Auth với username/password
- **HTTPS**: Vercel tự động cung cấp SSL certificate
- **Rate Limiting**: Vercel có sẵn rate limiting

## 📱 Tính năng Admin Panel

✅ **Dashboard**: Thống kê tổng quan
✅ **Quản lý Users**: Xem danh sách người dùng
✅ **Quản lý Giao dịch**: Xem và hoàn tác giao dịch
✅ **Thống kê chi tiết**: Phân tích theo thời gian
✅ **Logs**: Xem log hệ thống

## 🆘 Troubleshooting

### Lỗi thường gặp:

1. **Import Error**: Kiểm tra `PYTHONPATH` trong `vercel.json`
2. **Module not found**: Đảm bảo `requirements.txt` có đầy đủ dependencies
3. **Database Error**: Kiểm tra đường dẫn database trong environment variables

### Logs:
- Xem logs trong Vercel Dashboard > Functions
- Kiểm tra build logs nếu có lỗi

## 🔄 Auto-deploy

Vercel sẽ tự động deploy mỗi khi bạn push code lên GitHub repository.

---

**Lưu ý**: Đảm bảo database file (`bot.db`) được backup và có thể truy cập từ Vercel nếu cần.
