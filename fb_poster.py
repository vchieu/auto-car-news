import json
import os
import logging
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from config_loader import load_config, get_facebook_api_version

# Configure logger for this module
logger = logging.getLogger(__name__)

# ============================================================
# ĐƯỜNG DẪN TUYỆT ĐỐI - Giải quyết Vấn đề 2
# ============================================================
# Đảm bảo hoạt động đúng khi chạy từ Cron/Task Scheduler/GitHub Actions
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
def post_to_facebook(message):
    """
    Gửi bài viết lên Facebook Fanpage thông qua Facebook Graph API.
    Includes retry mechanism with exponential backoff.
    
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
    
    payload = {
        'message': message,
        'access_token': access_token
    }

    try:
        response = requests.post(url, data=payload, timeout=15)
        
        # Kiểm tra HTTP Status Code trước khi parse JSON
        if response.status_code != 200:
            logger.error(f"Lỗi HTTP {response.status_code}: {response.text}")
            # Re-raise to trigger retry
            raise requests.exceptions.HTTPError(f"HTTP {response.status_code}: {response.text}")
        
        result = response.json()

        # Kiểm tra mã lỗi từ Facebook Graph API
        if "id" in result:
            logger.info(f"Đăng bài thành công! Post ID: {result['id']}")
            return True
        else:
            # Facebook trả về error object
            error_msg = result.get('error', {}).get('message', 'Unknown error')
            error_code = result.get('error', {}).get('code', 'N/A')
            logger.error(f"Đăng bài thất bại! Code: {error_code} - Message: {error_msg}")
            # Re-raise to trigger retry
            raise Exception(f"Facebook API Error {error_code}: {error_msg}")

    except requests.exceptions.Timeout:
        logger.error("Lỗi timeout khi gọi Facebook API (15s).")
        raise
    except requests.exceptions.ConnectionError:
        logger.error("Lỗi kết nối mạng khi gọi Facebook API.")
        raise
    except requests.exceptions.RequestException as e:
        logger.error(f"Lỗi requests: {e}")
        raise
    except ValueError as e:
        logger.error(f"Lỗi parse JSON response: {e}")
        raise
    except Exception as e:
        logger.error(f"Lỗi không xác định khi đăng bài: {e}")
        raise


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
