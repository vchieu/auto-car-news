import schedule
import time
import os
import sys
import argparse
import logging
from datetime import datetime
from scraper import fetch_latest_news, mark_urls_as_seen
from analyzer import generate_analysis_post
from fb_poster import post_to_facebook
from config_loader import load_config

# ============================================================
# ĐƯỜNG DẪN TUYỆT ĐỐI
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'logs')

# ============================================================
# CẤU HÌNH LOGGING
# ============================================================
os.makedirs(LOG_DIR, exist_ok=True)

log_format = '%(asctime)s | %(levelname)-8s | %(message)s'
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(LOG_DIR, f'app_{datetime.now().strftime("%Y%m%d")}.log'),
            encoding='utf-8'
        )
    ]
)
logger = logging.getLogger(__name__)


def job():
    """
    Hàm chính thực hiện toàn bộ quy trình: cào tin -> phân tích AI -> đăng Facebook.
    """
    separator = '=' * 60
    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    logger.info(separator)
    logger.info(f"Bắt đầu quy trình lúc {start_time}")
    logger.info(separator)

    # 0. Load config for provider info
    config = load_config()
    ai_provider = config.get('ai_provider', 'gemini').upper()

    # 1. Cào tin từ các nguồn RSS (chỉ lấy tin MỚI chưa đọc)
    logger.info("Đang cào tin từ các nguồn RSS...")
    articles = fetch_latest_news()
    
    if not articles:
        logger.info("Không có tin MỚI nào để xử lý. Kết thúc.")
        return False
    
    logger.info(f"Tìm thấy {len(articles)} bài viết mới để xử lý.")

    # 2. Phân tích bằng AI (provider được chọn động từ config.json)
    logger.info(f"Đang phân tích nội dung bằng {ai_provider} AI...")
    post_content = generate_analysis_post(articles)

    if not post_content:
        logger.error("AI không tạo được nội dung. Bỏ qua lần này.")
        return False
    
    logger.info("Phân tích AI hoàn tất.")

    # 3. Đăng lên Facebook
    logger.info("Đang đăng bài lên Facebook Fanpage...")
    success = post_to_facebook(post_content)

    # 4. Chỉ lưu seen_urls SAU KHI toàn bộ quy trình thành công
    #    Nếu AI hoặc Facebook lỗi, các URL sẽ KHÔNG bị đánh dấu đã đọc,
    #    đảm bảo bot sẽ thử lại ở lần chạy tiếp theo.
    if success:
        mark_urls_as_seen(articles)
        logger.info("Hoàn thành quy trình thành công!")
    else:
        logger.warning("Quy trình kết thúc nhưng có lỗi khi đăng bài. Các URL chưa được đánh dấu đã đọc.")

    return success


def run_once():
    """
    Chạy job() đúng một lần rồi thoát.
    Phù hợp khi dùng Cronjob hoặc Task Scheduler.
    """
    logger.info("=" * 60)
    logger.info("AUTO CAR NEWS BOT - CHẾ ĐỘ MỘT LẦN")
    logger.info("=" * 60)
    logger.info(f"Thư mục làm việc: {BASE_DIR}")
    logger.info("=" * 60)
    
    try:
        job()
    except Exception as e:
        logger.exception(f"Lỗi không mong muốn: {e}")
        sys.exit(1)


def run_daemon(run_time):
    """
    Chạy liên tục với vòng lặp schedule.
    Phù hợp khi chạy trực tiếp trên máy cá nhân.
    """
    logger.info("=" * 60)
    logger.info("AUTO CAR NEWS BOT - CHẾ ĐỘ LIÊN TỤC")
    logger.info("=" * 60)
    logger.info(f"Đã hẹn giờ đăng bài lúc {run_time} hàng ngày.")
    logger.info(f"Thư mục làm việc: {BASE_DIR}")
    logger.info(f"Log file: {os.path.join(LOG_DIR, 'app_YYYYMMDD.log')}")
    logger.info("=" * 60)

    # Lập lịch định kỳ hàng ngày
    schedule.every().day.at(run_time).do(job)

    logger.info("Hệ thống đang chờ đến giờ đăng bài...")
    
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Auto Car News Bot')
    parser.add_argument(
        '--daemon', '-d',
        action='store_true',
        help='Chạy liên tục với vòng lặp schedule (mặc định: chạy một lần rồi thoát)'
    )
    args = parser.parse_args()

    config = load_config()
    run_time = config['settings']['run_time']

    if args.daemon:
        # Chạy liên tục (chế độ cũ - while True)
        run_daemon(run_time)
    else:
        # Chạy một lần rồi thoát (phù hợp với Cronjob/Task Scheduler)
        run_once()
