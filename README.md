# Hướng dẫn sử dụng Auto Car News

## Giới thiệu

Dự án này tự động thu thập tin tức ô tô từ nhiều nguồn RSS, phân tích nội dung bằng AI (Gemini hoặc OpenAI-compatible Proxy), và đăng bài lên Facebook Fanpage một cách định kỳ.

## Cấu trúc thư mục

```
auto-car-news/
├── config.json          # Cấu hình thực tế (không commit, đã có trong .gitignore)
├── config.example.json  # Template cấu hình (copy sang config.json và điền API key)
├── seen_urls.json       # File lưu trữ URL đã đăng (dict {"url": timestamp}, tự động tạo)
├── requirements.txt     # Thư viện Python cần cài đặt
├── main.py              # File điều khiển chính & lập lịch
├── config_loader.py     # Module quản lý cấu hình tập trung
├── scraper.py           # Module 1: Cào tin từ RSS
├── analyzer.py          # Module 2: Phân tích bằng AI và tạo bài đăng
├── fb_poster.py         # Module 3: Đăng bài lên Facebook
├── logs/                # Thư mục chứa file log (tự động tạo)
└── README.md            # Hướng dẫn này
```

## Các thư viện mới

- **filelock**: Chống race condition khi nhiều process truy cập `seen_urls.json` cùng lúc
- **tenacity**: Retry mechanism với exponential backoff cho các lỗi tạm thời từ AI và Facebook API

## Cách thiết lập môi trường

### 1. Tạo môi trường ảo

Mở Terminal/Command Prompt tại thư mục `auto-car-news`:

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate
```

### 2. Cài đặt thư viện

```bash
pip install -r requirements.txt
```

## Cách chạy project

### Chạy thử (một lần) - Khuyến nghị cho Cronjob/Task Scheduler

```bash
python main.py
```

Project sẽ:
1. Cào tin từ các nguồn RSS đã cấu hình
2. Gửi tin sang AI (Gemini hoặc OpenAI Proxy, tùy config) để phân tích
3. Đăng bài lên Facebook Fanpage
4. Thoát ngay sau khi hoàn thành

### Chạy liên tục (trên máy cá nhân)

Nếu muốn chạy liên tục 24/7 với vòng lặp trong Python:

```bash
python main.py --daemon
# hoặc
python main.py -d
```

> ⚠️ **Lưu ý**: Chế độ này phù hợp khi bật máy cá nhân. Trên VPS/Server Linux, nên dùng Cronjob thay vì chạy liên tục.

### Chạy với Cronjob (Linux/VPS)

#### Bước 1: Copy file cấu hình mẫu

```bash
cp config.example.json config.json
# Sau đó chỉnh sửa config.json với API key thực tế của bạn
```

#### Bước 2: Tạo Cronjob

```bash
crontab -e
```

Thêm dòng sau (chạy lúc 08:00 mỗi ngày):

```cron
0 8 * * * cd /path/to/auto-car-news && /usr/bin/python3 main.py >> /path/to/auto-car-news/logs/cron.log 2>&1
```

#### Bước 3: Kiểm tra log

```bash
# Xem log hiện tại
cat logs/app.log

# Xem log cũ đã xoay theo ngày (ví dụ ngày 01/01/2024)
cat logs/app.log.20240101
```

### Chạy với Task Scheduler (Windows)

1. Mở Task Scheduler → Create Basic Task
2. Đặt tên: `Auto Car News Bot`
3. Trigger: Daily, 08:00
4. Action: Start a program
   - Program: `python`
   - Arguments: `main.py`
   - Start in: `C:\path\to\auto-car-news`

### Xem log

File log được lưu tự động trong thư mục `logs/`:

```bash
# Xem log hiện tại
cat logs/app.log

# Xem log cũ đã xoay theo ngày (ví dụ ngày 01/01/2024)
cat logs/app.log.20240101

# Theo dõi log real-time
tail -f logs/app.log
```

Log gồm các cấp độ: `INFO`, `WARNING`, `ERROR`, `CRITICAL`

## Cấu hình (config.json)

File `config.json` là "trung tâm điều khiển". Bạn chỉ cần sửa file này mà không cần chạm vào code.

### Các trường chính:

- **rss_sources**: Mảng các nguồn RSS (name, url)
- **ai_provider**: `"openai"` hoặc `"gemini"` — chọn nhà cung cấp AI nào để phân tích
- **openai**: api_key, base_url (URL proxy OpenAI-compatible, phải kết thúc bằng `/v1`), model
- **gemini**: api_key, model
- **facebook**: page_id, access_token, **api_version** (mặc định: `"v19.0"`)
- **settings**: max_articles_per_source, run_time

### Chuyển đổi giữa Gemini và OpenAI Proxy

Chỉ cần thay đổi giá trị `ai_provider` trong `config.json`:

```json
// Dùng OpenAI-compatible Proxy (ví dụ: OpenRouter, vLLM, llama.cpp server):
"ai_provider": "openai",
"openai": {
  "api_key": "YOUR_OPENAI_OR_PROXY_KEY",
  "base_url": "https://your-proxy-domain.com/v1",
  "model": "gpt-4o-mini"
}

// Hoặc dùng Gemini:
"ai_provider": "gemini",
"gemini": {
  "api_key": "YOUR_GEMINI_API_KEY",
  "model": "gemini-2.5-flash"
}
```

### Thêm nguồn RSS mới

```json
{
  "name": "Tên báo",
  "url": "https://example.com/rss"
}
```

### Thay đổi giờ đăng bài

```json
"run_time": "19:30"
```

## Các module

### 1. config_loader.py (Mới)

Module quản lý cấu hình tập trung:
- **`load_config()`**: Đọc và validate `config.json`, trả về dictionary cấu hình
- **`get_facebook_api_version()`**: Trả về phiên bản Facebook Graph API (mặc định: `"v19.0"`)

Tất cả các module khác đều import từ `config_loader` thay vì tự đọc JSON.

### 2. scraper.py

Chức năng:
- Đọc cấu hình từ `config_loader`
- Truy cập các URL RSS
- Trả về danh sách bài báo (tiêu đề, tóm tắt, link)
- **Race Condition Prevention**: Sử dụng `filelock` để tránh xung đột khi nhiều process truy cập `seen_urls.json`
- **Time-based Cleanup**: Tự động xóa URL cũ hơn 60 ngày thay vì giới hạn số lượng

### 3. analyzer.py

Chức năng:
- Gửi tin sang AI (Gemini hoặc OpenAI Proxy, tùy config)
- Nhận bài đăng Facebook đã được phân tích
- Bao gồm: tiêu đề, tóm tắt xu hướng, 3 điểm tin quan trọng, hashtag
- **Token Limits**: 
  - Tóm tắt bài viết bị cắt ngắn tối đa **300 ký tự** mỗi bài
  - Giới hạn tối đa **15 bài viết** mỗi lần gọi AI
- **Retry Mechanism**: Tự động thử lại 3 lần với exponential backoff khi gặp lỗi tạm thời

### 4. fb_poster.py

Chức năng:
- Gửi bài đăng lên Facebook Fanpage
- Sử dụng Facebook Graph API với **phiên bản động** từ config (mặc định `v19.0`)
- **Retry Mechanism**: Tự động thử lại 3 lần với exponential backoff khi gặp lỗi mạng

### 5. main.py

Chức năng:
- Điều phối toàn bộ quy trình
- Hỗ trợ 2 chế độ: một lần (phù hợp Cronjob) và liên tục (--daemon)
- Ghi log ra file `logs/app.log` với **xoay tự động lúc nửa đêm**, giữ 30 ngày
- Chạy thử ngay lập tức

## Mechanism chi tiết

### Race Condition Prevention (scraper.py)

Khi chạy nhiều instance (ví dụ: daemon + cronjob), `seen_urls.json` có thể bị xung đột. Giải pháp:

1. Sử dụng `filelock.FileLock("seen_urls.json.lock")` để khóa file trước khi đọc/ghi
2. `seen_urls.json` lưu dưới dạng dict `{"url": timestamp}` thay vì set đơn giản
3. Timestamp cho phép cleanup theo thời gian thay vì giới hạn số lượng

### Retry Mechanism (analyzer.py, fb_poster.py)

Sử dụng `tenacity` decorator với:
- **3 attempts** (1 lần đầu + 2 lần retry)
- **Exponential backoff**: Chờ lâu hơn giữa mỗi lần thử
- **Chỉ retry lỗi tạm thời**: Lỗi mạng, timeout, server bận
- **Propagate lỗi vĩnh viễn**: Invalid API key, 4xx errors sẽ không retry

### Token/Payload Limits (analyzer.py)

Để tránh token blow-up và giữ prompt size predictable:
- Mỗi tóm tắt bài viết bị cắt ngắn tối đa **300 ký tự**
- Tối đa **15 bài viết** được gửi trong một lần gọi AI

## Hướng dẫn lấy Facebook Token

### Lấy Page ID

1. Truy cập Fanpage → Giới thiệu (About)
2. Tìm "Page ID"

### Lấy Long-lived Access Token

1. Truy cập [Facebook Developers Explorer](https://developers.facebook.com/tools/explorer/)
2. Chọn App và Page
3. Thêm quyền:
   - `pages_read_engagement`
   - `pages_manage_posts`
4. Tạo token → Đổi thành Long-lived token
5. Dán page_id và access_token vào `config.json`

## Các lưu ý khi sử dụng

1. **API Key**: Thay các placeholder (YOUR_*) bằng key thực tế trong config.json
2. **OpenAI Proxy URL**: Trường `base_url` trong `openai` phải kết thúc bằng `/v1` (ví dụ: `https://openrouter.ai/api/v1`, `https://your-vllm-server.com/v1`)
3. **Token Facebook**: Token có hạn sử dụng, cần cập nhật định kỳ
4. **Lỗi cào tin**: Nếu có lỗi khi cào tin, kiểm tra URL RSS
5. **Tốc độ**: Project chạy mỗi phút một lần để kiểm tra lịch
6. **Automatic Retry**: Nếu bước AI hoặc Facebook lỗi tạm thời, hệ thống sẽ tự động thử lại với exponential backoff (tối đa 3 lần)
7. **URL Cleanup**: `seen_urls.json` tự động xóa URL cũ hơn 60 ngày để giữ file nhỏ gọn
8. **Cronjob**: Dùng `python main.py` (không có tham số) cho Cronjob/Task Scheduler. File log giúp debug dễ dàng khi không có terminal
9. **Daemon mode**: Dùng `python main.py --daemon` để chạy liên tục với vòng lặp trong Python
10. **Race Condition**: Nếu chạy nhiều instance cùng lúc, hệ thống sẽ tự động khóa file `seen_urls.json` để tránh xung đột
11. **Log Rotation**: File log `logs/app.log` tự động xoay lúc nửa đêm mỗi ngày, giữ 30 ngày gần nhất

## Hỗ trợ

Nếu gặp vấn đề, kiểm tra:
- config.json có đầy đủ thông tin không
- Các API key còn hạn sử dụng không
- Internet kết nối được không
- File log trong thư mục `logs/` để xem chi tiết lỗi
