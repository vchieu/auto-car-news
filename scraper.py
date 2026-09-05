import feedparser
import json
import os
import time
import calendar
import logging
import filelock
import requests
from bs4 import BeautifulSoup
from config_loader import load_config

# Configure logger for this module
logger = logging.getLogger(__name__)

# Giả lập User-Agent trình duyệt để tránh bị các báo/Cloudflare chặn request
feedparser.USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEEN_URLS_PATH = os.path.join(BASE_DIR, 'seen_urls.json')
SEEN_URLS_LOCK_PATH = os.path.join(BASE_DIR, 'seen_urls.json.lock')


def clean_html(raw_html):
    """
    Sử dụng BeautifulSoup để làm sạch HTML và lấy text thuần túy.
    """
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(separator=' ')
    return ' '.join(text.split()).strip()


def _read_seen_urls_unlocked():
    """
    Internal helper: Đọc file seen_urls.json KHÔNG lấy lock.
    CHỈ sử dụng bên trong một block đã có FileLock khác.
    """
    seen_urls = {}
    if not os.path.exists(SEEN_URLS_PATH):
        return seen_urls
    try:
        with open(SEEN_URLS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Support both old format (list) and new format (dict)
            if isinstance(data, list):
                # Convert old list format to new dict format
                current_time = time.time()
                seen_urls = {url: current_time for url in data}
            elif isinstance(data, dict):
                seen_urls = data
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Không thể đọc seen_urls.json, tạo mới: {e}")
        seen_urls = {}
    return seen_urls


def load_seen_urls():
    """
    Load seen URLs from seen_urls.json as a dictionary with timestamps.

    Returns:
        dict: Dictionary with URL as key and timestamp as value

    Raises:
        RuntimeError: If cannot acquire file lock within timeout.
                     Raising (instead of silently returning {}) prevents
                     the bot from re-posting old articles.
    """
    lock = filelock.FileLock(SEEN_URLS_LOCK_PATH, timeout=10)

    try:
        with lock:
            return _read_seen_urls_unlocked()
    except filelock.Timeout:
        logger.error("Timeout khi lock seen_urls.json để đọc")
        # Bug 3 fix: Raise thay vì return {} để tránh đăng lặp lại toàn bộ bài cũ
        raise RuntimeError("Không thể khóa file seen_urls.json để đọc dữ liệu")


def save_seen_urls(new_articles_map, max_limit=1000):
    """
    Atomically merge and persist seen_urls dictionary.

    Toàn bộ quy trình Read - Merge - Cleanup - Write nằm trọn trong 1 FileLock
    để chống Race Condition khi nhiều tiến trình (daemon + cronjob) chạy đồng thời.

    Args:
        new_articles_map: dict {url: timestamp} của các URL mới cần merge.
        max_limit: Maximum number of URLs to keep (default: 1000).
    """
    lock = filelock.FileLock(SEEN_URLS_LOCK_PATH, timeout=10)
    current_time = time.time()
    cleanup_days = 60
    cleanup_seconds = cleanup_days * 24 * 3600

    try:
        with lock:
            # Bug 2 fix: Đọc lại dữ liệu mới nhất NGAY TRONG LOCK
            # rồi merge với dữ liệu mới, sau đó mới ghi đè file.
            # Điều này ngăn chặn việc tiến trình B ghi đè mất dữ liệu
            # mà tiến trình A vừa đánh dấu trước đó.
            seen_urls = _read_seen_urls_unlocked()

            # Merge dữ liệu mới vào dict hiện tại
            if new_articles_map:
                seen_urls.update(new_articles_map)

            # Cleanup: Remove URLs older than 60 days (with isinstance check for data safety)
            cleaned_urls = {
                url: timestamp for url, timestamp in seen_urls.items()
                if isinstance(timestamp, (int, float)) and (current_time - timestamp) <= cleanup_seconds
            }

            removed_count = len(seen_urls) - len(cleaned_urls)
            if removed_count > 0:
                logger.info(f"Đã dọn dẹp {removed_count} URL cũ (quá {cleanup_days} ngày)")

            # Limit the number of URLs
            urls_list = list(cleaned_urls.keys())
            if len(urls_list) > max_limit:
                # Keep the most recent URLs
                sorted_urls = sorted(cleaned_urls.items(), key=lambda x: x[1], reverse=True)
                cleaned_urls = dict(sorted_urls[:max_limit])
                logger.info(f"Đã giới hạn danh sách URL xuống {max_limit} mục gần nhất")

            with open(SEEN_URLS_PATH, 'w', encoding='utf-8') as f:
                json.dump(cleaned_urls, f, ensure_ascii=False, indent=2)

    except filelock.Timeout:
        logger.error("Timeout khi lock seen_urls.json để ghi")
        raise RuntimeError("Không thể khóa file seen_urls.json để ghi dữ liệu")
    except IOError as e:
        logger.error(f"Lỗi khi ghi seen_urls.json: {e}")
        raise


def fetch_latest_news():
    """
    Fetch latest news from RSS sources, filtering out already-seen URLs
    and articles older than 48 hours.

    Returns:
        list: List of article dictionaries
    """
    config = load_config()
    # Bug 3 fix: Nếu không đọc được seen_urls, sẽ raise RuntimeError
    # để main.py xử lý (không spam lại toàn bộ bài cũ).
    seen_urls = load_seen_urls()
    all_articles = []
    max_items = config['settings']['max_articles_per_source']
    new_urls_found = set()

    # Giới hạn thời gian: chỉ lấy tin trong vòng 48 giờ gần nhất (48 * 3600 giây)
    max_age_seconds = 48 * 3600
    current_time = time.time()

    logger.info(f"Đã có {len(seen_urls)} bài viết đã xử lý trước đó.")

    for source in config['rss_sources']:
        try:
            # Issue 1.1 fix: Use requests.get() with timeout to prevent indefinite hang
            # when RSS source is slow or unresponsive. feedparser.parse() alone
            # uses Python's default socket timeout which can block forever.
            try:
                resp = requests.get(
                    source['url'],
                    headers={'User-Agent': feedparser.USER_AGENT},
                    timeout=15
                )
                resp.raise_for_status()
                feed = feedparser.parse(resp.content)
            except requests.exceptions.Timeout:
                logger.error(f"Timeout (15s) khi tải RSS từ {source['name']}: {source['url']}")
                continue
            except requests.exceptions.ConnectionError as e:
                logger.error(f"Lỗi kết nối khi tải RSS từ {source['name']}: {e}")
                continue
            except requests.exceptions.HTTPError as e:
                logger.error(f"Lỗi HTTP khi tải RSS từ {source['name']}: {e}")
                continue
            
            count = 0

            for entry in feed.entries:
                if count >= max_items:
                    break

                # BUG 4 FIX: Truy xuất thuộc tính an toàn bằng getattr
                # (fallback sang guid nếu thiếu link). Nếu entry thiếu
                # cả link và guid, chỉ bỏ qua entry đó thay vì crash toàn bộ.
                link = getattr(entry, 'link', None) or getattr(entry, 'guid', None)
                if not link:
                    logger.warning(f"Bỏ qua 1 bài viết thiếu thuộc tính link/guid trong nguồn {source['name']}")
                    continue

                # 1. Kiểm tra nếu URL đã xử lý trước đó HOẶC đã có trong danh sách mới cào của đợt này
                if link in seen_urls or link in new_urls_found:
                    continue

                # 2. Kiểm tra ngày đăng (nếu nguồn RSS có cung cấp)
                published_parsed = getattr(entry, 'published_parsed', None) or getattr(entry, 'updated_parsed', None)
                if published_parsed:
                    # Bug 1 fix: feedparser trả về struct_time theo UTC.
                    # Dùng calendar.timegm() thay cho time.mktime() để tránh
                    # bị lệch múi giờ máy chủ (ví dụ UTC+7 tại VN).
                    entry_timestamp = calendar.timegm(published_parsed)
                    if (current_time - entry_timestamp) > max_age_seconds:
                        continue  # Bỏ qua bài viết quá cũ

                # Lọc sạch thẻ HTML khỏi summary
                summary_raw = getattr(entry, 'summary', '')
                cleaned_summary = clean_html(summary_raw)

                all_articles.append({
                    'source': source['name'],
                    'title': entry.title,
                    'summary': cleaned_summary,
                    'link': link
                })

                new_urls_found.add(link)
                count += 1

        except Exception as e:
            logger.error(f"Lỗi khi cào tin từ {source['name']}: {e}")

    logger.info(f"Tìm thấy {len(new_urls_found)} bài viết mới để xử lý.")
    return all_articles


def mark_urls_as_seen(articles):
    """
    Mark article URLs as seen by storing them with timestamps.
    Should be called only after successful Facebook posting.

    Chú ý: Hàm này KHÔNG đọc/ghi toàn bộ seen_urls nữa. Thay vào đó, nó chỉ
    merge các URL mới vào file thông qua save_seen_urls() - vốn đã thực hiện
    toàn bộ Read-Modify-Write bên trong một FileLock duy nhất, loại bỏ hoàn
    toàn race condition giữa nhiều tiến trình.

    Args:
        articles: List of article dictionaries with 'link' keys
    """
    if not articles:
        return

    new_articles_map = {}
    current_time = time.time()
    for item in articles:
        if isinstance(item, dict) and 'link' in item:
            new_articles_map[item['link']] = current_time

    if not new_articles_map:
        return

    try:
        save_seen_urls(new_articles_map)
        logger.info(f"Đã đánh dấu {len(new_articles_map)} URL là đã xử lý trong seen_urls.json.")
    except Exception as e:
        logger.error(f"Không thể đánh dấu URL đã xử lý: {e}")
        raise


def reset_seen_urls():
    """
    Reset the seen URLs file (delete it).
    """
    lock = filelock.FileLock(SEEN_URLS_LOCK_PATH, timeout=10)

    try:
        with lock:
            if os.path.exists(SEEN_URLS_PATH):
                os.remove(SEEN_URLS_PATH)
                logger.info("Đã reset danh sách bài viết đã xử lý.")
            else:
                logger.info("Không có file seen_urls.json để reset.")
    except filelock.Timeout:
        logger.error("Timeout khi lock seen_urls.json để reset")
    except IOError as e:
        logger.error(f"Lỗi khi reset seen_urls.json: {e}")


if __name__ == "__main__":
    news = fetch_latest_news()
    logger.info(f"Đã cào được {len(news)} bài báo mới.")
    for item in news:
        logger.info(f"  - [{item['source']}] {item['title']}")
