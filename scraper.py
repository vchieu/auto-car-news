import feedparser
import json
import os
import time
import logging
import filelock
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


def load_seen_urls():
    """
    Load seen URLs from seen_urls.json as a dictionary with timestamps.
    
    Returns:
        dict: Dictionary with URL as key and timestamp as value
    """
    seen_urls = {}
    lock = filelock.FileLock(SEEN_URLS_LOCK_PATH, timeout=10)
    
    try:
        with lock:
            if os.path.exists(SEEN_URLS_PATH):
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
                    return {}
    except filelock.Timeout:
        logger.error("Timeout khi lock seen_urls.json để đọc")
        return {}
    
    return seen_urls


def save_seen_urls(seen_urls, max_limit=1000):
    """
    Save seen URLs dictionary to seen_urls.json with timestamps.
    Includes cleanup logic to remove URLs older than 60 days.
    
    Args:
        seen_urls: Dictionary with URL as key and timestamp as value
        max_limit: Maximum number of URLs to keep (default: 1000)
    """
    lock = filelock.FileLock(SEEN_URLS_LOCK_PATH, timeout=10)
    current_time = time.time()
    cleanup_days = 60
    cleanup_seconds = cleanup_days * 24 * 3600
    
    try:
        with lock:
            # Cleanup: Remove URLs older than 60 days
            cleaned_urls = {
                url: timestamp for url, timestamp in seen_urls.items()
                if (current_time - timestamp) <= cleanup_seconds
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
    except IOError as e:
        logger.error(f"Lỗi khi ghi seen_urls.json: {e}")


def fetch_latest_news():
    """
    Fetch latest news from RSS sources, filtering out already-seen URLs
    and articles older than 48 hours.
    
    Returns:
        list: List of article dictionaries
    """
    config = load_config()
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
            feed = feedparser.parse(source['url'])
            count = 0

            for entry in feed.entries:
                if count >= max_items:
                    break

                link = entry.link

                # 1. Kiểm tra nếu URL đã từng xử lý
                if link in seen_urls:
                    continue

                # 2. Kiểm tra ngày đăng (nếu nguồn RSS có cung cấp)
                published_parsed = getattr(entry, 'published_parsed', None) or getattr(entry, 'updated_parsed', None)
                if published_parsed:
                    entry_timestamp = time.mktime(published_parsed)
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
    
    Args:
        articles: List of article dictionaries with 'link' keys
    """
    if not articles:
        return

    seen_urls = load_seen_urls()
    current_time = time.time()
    
    for item in articles:
        if isinstance(item, dict) and 'link' in item:
            seen_urls[item['link']] = current_time

    save_seen_urls(seen_urls)
    logger.info(f"Đã đánh dấu {len(articles)} URL là đã xử lý trong seen_urls.json.")


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
