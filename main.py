import schedule
import time
import os
import sys
import argparse
import logging
import logging.handlers
from datetime import datetime
from scraper import fetch_latest_news, mark_urls_as_seen
from analyzer import generate_analysis_post
from fb_poster import post_to_facebook
from config_loader import load_config, ConfigurationError

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
date_format = '%Y-%m-%d %H:%M:%S'

# Issue 3 fix: Thay FileHandler bằng TimedRotatingFileHandler
# - when='midnight': Xoay file log vào lúc nửa đêm mỗi ngày
# - backupCount=30: Giữ lại 30 ngày log gần nhất (tự động xóa cũ hơn)
# - Sửa lỗi: Trước đây dùng FileHandler với datetime.now() được gọi ngay
#   khi import module, nên daemon chạy nhiều ngày sẽ ghi tất cả vào
#   file log của ngày đầu tiên khởi chạy.
file_handler = logging.handlers.TimedRotatingFileHandler(
    os.path.join(LOG_DIR, 'app.log'),
    when='midnight',
    interval=1,
    backupCount=30,
    encoding='utf-8'
)
# Đặt suffix theo ngày để dễ phân biệt
file_handler.suffix = '%Y%m%d'

logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    datefmt=date_format,
    handlers=[
        logging.StreamHandler(sys.stdout),
        file_handler
    ]
)
logger = logging.getLogger(__name__)


def job():
    """
    Hàm chính thực hiện toàn bộ quy trình: cào tin -> phân tích AI -> đăng Facebook.
    
    Issue 1.2 fix: Bọc toàn bộ thân hàm trong try...except tổng quát.
    Đảm bảo cho dù có lỗi gì xảy ra ở 1 lượt chạy (ví dụ RuntimeError từ filelock
    khi hết timeout, hoặc exception từ schedule library), Daemon vẫn sống để
    đợi lượt hẹn giờ tiếp theo thay vì bị crash.
    """
    try:
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

        # BUG 3 FIX: Khi AI trả về None hoặc chuỗi rỗng do Safety Block,
        # đánh dấu các URL hiện tại là đã xử lý để giải phóng hàng chờ,
        # giúp bot tiếp tục cào tin mới ở lượt chạy sau.
        if not post_content:
            logger.error("AI không tạo được nội dung (Safety Block hoặc API Error). Đánh dấu bỏ qua các bài viết này để tránh kẹt hệ thống.")
            # Bắt buộc đánh dấu seen để lần sau cào tin mới, tránh lặp vô tận
            mark_urls_as_seen(articles)
            return False

        logger.info("Phân tích AI hoàn tất.")

        # 3. Đăng lên Facebook (bọc try...except để tránh crash app khi post fail)
        logger.info("Đang đăng bài lên Facebook Fanpage...")
        try:
            success = post_to_facebook(post_content)
        except Exception as e:
            logger.error(f"Đăng bài lên Facebook thất bại sau nhiều lần thử: {e}")
            success = False

        # 4. Chỉ lưu seen_urls SAU KHI toàn bộ quy trình thành công
        #    Nếu AI hoặc Facebook lỗi, các URL sẽ KHÔNG bị đánh dấu đã đọc,
        #    đảm bảo bot sẽ thử lại ở lần chạy tiếp theo.
        if success:
            mark_urls_as_seen(articles)
            logger.info("Hoàn thành quy trình thành công!")
        else:
            logger.warning("Quy trình kết thúc nhưng có lỗi khi đăng bài. Các URL chưa được đánh dấu đã đọc.")

        return success
    except Exception as e:
        # Issue 1.2 fix: Bắt mọi exception không mong muốn trong job()
        # để Daemon process không bị crash và tiếp tục chạy.
        logger.exception(f"Lỗi không xử lý được trong lượt chạy job: {e}")
        return False


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
    except ConfigurationError as e:
        logger.error(f"Lỗi cấu hình: {e}")
        sys.exit(1)
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
    logger.info(f"Log file: {os.path.join(LOG_DIR, 'app.log')} (xoay lúc nửa đêm mỗi ngày, giữ 30 ngày)")
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
