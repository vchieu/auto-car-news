import json
import os
import re
import logging
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config_loader import load_config, get_facebook_api_version

# Configure logger for this module
logger = logging.getLogger(__name__)

# ============================================================
# ĐƯỜNG DẪN TUYỆT ĐỐI - Giải quyết Vấn đề 2
# ============================================================
# Đảm bảo hoạt động đúng khi chạy từ Cron/Task Scheduler/GitHub Actions
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def clean_markdown_for_facebook(text: str) -> str:
    """
    Loại bỏ các ký tự Markdown không được Facebook Fanpage hỗ trợ.

    Facebook không render cú pháp Markdown (**, *, #, `...) mà sẽ hiển thị
    nguyên văn các ký tự đặc biệt này. Hàm này strip các ký tự đó nhưng
    vẫn giữ nguyên nội dung văn bản bên trong.

    Args:
        text: Chuỗi văn bản có thể chứa Markdown từ AI.

    Returns:
        str: Chuỗi đã được làm sạch, an toàn để gửi lên Facebook.
    """
    if not text:
        return ""

    # BUG 2 FIX: Chuyển đổi bullet list markdown "- " hoặc "* " thành "• " TRƯỚC BẤT KỲ REGEX NÀO KHÁC
    text = re.sub(r'^[\-\*]\s+', '• ', text, flags=re.MULTILINE)

    # Bỏ bôi đậm **text** -> text
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)

    # Bỏ in nghiêng *text* (KHÔNG cho phép khớp qua dấu xuống dòng \n bằng [^\*\n]+)
    text = re.sub(r'(?<!\*)\*([^\*\n]+)\*(?!\*)', r'\1', text)

    # Bỏ tiêu đề Markdown: ### Header / ## Header / # Header -> Header
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)

    # Bỏ gạch ngang dùng làm heading separator (---)
    text = re.sub(r'^---+$\n?', '', text, flags=re.MULTILINE)

    # Bỏ inline code & code block fences
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'```[^\n]*\n?', '', text)
    text = re.sub(r'```', '', text)

    # Bỏ link markdown [text](url) -> text (url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', text)

    return text.strip()


# Issue 1 fix: Retry CHỈ các lỗi kết nối tạm thời (ConnectionError, Timeout).
# KHÔNG retry các lỗi vĩnh viễn như 4xx (invalid token), bad request, etc.
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout
    )),
    reraise=True
)
def post_to_facebook(message):
    """
    Gửi bài viết lên Facebook Fanpage thông qua Facebook Graph API.
    Includes retry mechanism with exponential backoff (only for transient errors).

    Args:
        message (str): Nội dung bài đăng cần đăng lên Facebook.

    Returns:
        bool: True nếu đăng thành công, False nếu thất bại.
    """
    config = load_config()

    page_id = config['facebook']['page_id']
    access_token = config['facebook']['access_token']

    # Use centralized API version from config
    api_version = get_facebook_api_version()
    url = f"https://graph.facebook.com/{api_version}/{page_id}/feed"

    logger.info(f"Đang đăng bài lên Facebook API {api_version}...")

    # Enhancement A: Loại bỏ Markdown không hỗ trợ trên Facebook
    cleaned_message = clean_markdown_for_facebook(message)
    payload = {
        'message': cleaned_message,
        'access_token': access_token
    }

    # Issue 2 fix: Tách phần raise HTTPError ra khỏi luồng parse JSON.
    # Parse JSON trước để có thể đọc error message chi tiết từ Facebook
    # Graph API, dù status_code có phải 200 hay không.
    response = None
    try:
        response = requests.post(url, data=payload, timeout=15)
    except requests.exceptions.Timeout:
        logger.error("Lỗi timeout khi gọi Facebook API (15s).")
        raise  # Sẽ được retry bởi decorator
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Lỗi kết nối mạng khi gọi Facebook API: {e}")
        raise  # Sẽ được retry bởi decorator
    except requests.exceptions.RequestException as e:
        logger.error(f"Lỗi requests không xác định: {e}")
        raise

    # Issue 2 fix: Parse JSON trước để lấy error message từ Facebook
    # bất kể status_code là gì. Trước đây, code raise HTTPError ngay khi
    # status_code != 200 làm cho nhánh else phân tích `result.get('error')`
    # không bao giờ chạy được.
    result = {}
    try:
        result = response.json()
    except ValueError as e:
        logger.warning(f"Không thể parse JSON response từ Facebook: {e}")
        # Tiếp tục xử lý với dict rỗng bên dưới

    if response.status_code == 200 and "id" in result:
        logger.info(f"Đăng bài thành công! Post ID: {result['id']}")
        return True

    # Lấy thông tin lỗi chi tiết từ Facebook Graph API
    error_obj = result.get('error', {}) if isinstance(result, dict) else {}
    error_msg = error_obj.get('message', response.text if response is not None else 'No response')
    error_code = error_obj.get('code', response.status_code if response is not None else 'N/A')

    # Phân loại lỗi: 5xx là lỗi server tạm thời -> retry; 4xx là lỗi vĩnh viễn -> không retry
    if response is not None and 500 <= response.status_code < 600:
        logger.warning(f"Facebook server error {response.status_code}: {error_msg}. Sẽ retry...")
        raise requests.exceptions.ConnectionError(
            f"Facebook server error {response.status_code}: {error_msg}"
        )

    # Lỗi 4xx hoặc không có response id -> Raise Exception (KHÔNG retry)
    logger.error(f"Đăng bài thất bại! Code: {error_code} - Message: {error_msg}")
    raise Exception(f"Facebook API Error {error_code}: {error_msg}")


if __name__ == "__main__":
    # Test posting
    test_message = "Đây là tin nhắn test từ Auto Car News Bot"
    try:
        result = post_to_facebook(test_message)
        if result:
            logger.info("Test đăng bài thành công!")
        else:
            logger.error("Test đăng bài thất bại.")
    except Exception as e:
        logger.error(f"Test đăng bài lỗi: {e}")
