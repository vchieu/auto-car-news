import json
import os
import logging
import requests
from google import genai
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from config_loader import load_config

# Configure logger for this module
logger = logging.getLogger(__name__)

# ============================================================
# ĐƯỜNG DẪN TUYỆT ĐỐI
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def truncate_summary(text, max_length=300):
    """
    Truncate text to maximum length while preserving complete words.

    Args:
        text: Text to truncate
        max_length: Maximum character length

    Returns:
        str: Truncated text with ellipsis if needed
    """
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    # Truncate to max_length and add ellipsis
    truncated = text[:max_length]
    # Try to cut at word boundary
    last_space = truncated.rfind(' ')
    if last_space > max_length * 0.8:  # If we can find a word boundary in last 20%
        truncated = truncated[:last_space]
    return truncated + "..."


# Retry CHỈ các lỗi tạm thời (connection/timeout).
# Không retry các lỗi vĩnh viễn như 4xx, invalid API key, etc.
# Sử dụng keyword matching để bắt lỗi từ cả requests, httpx, openai, google-genai.
def _is_transient_error(e):
    """Check if exception is a transient network/timeout error that should be retried."""
    # Bắt các lỗi của requests (cho OpenAI proxy nếu có wrapper)
    if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True
    # HTTP 5xx Server Errors - transient
    if isinstance(e, requests.exceptions.HTTPError):
        if e.response is not None:
            status_code = e.response.status_code
            if 500 <= status_code < 600:
                return True
    # Bắt các lỗi mạng phổ biến (httpx, openai, google-genai)
    error_str = str(e).lower()
    transient_keywords = ["connection", "timeout", "timed out", "503", "502", "504", "rate limit", "429"]
    if any(keyword in error_str for keyword in transient_keywords):
        return True
    return False


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(_is_transient_error),
    reraise=True
)
def _call_openai_api(client, model_name, prompt):
    """
    Call OpenAI API with retry mechanism.

    Args:
        client: OpenAI client instance
        model_name: Model name to use
        prompt: Prompt to send to API

    Returns:
        str: API response text
    """
    logger.info(f"🤖 Đang sử dụng OpenAI Proxy (Model: {model_name})...")

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "Bạn là một nhà phân tích thị trường ô tô chuyên nghiệp."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        content = response.choices[0].message.content or ""
        return content.strip()
    except Exception as e:
        if _is_transient_error(e):
            logger.warning(f"Lỗi kết nối tạm thời OpenAI API (sẽ retry): {e}")
        else:
            logger.error(f"Lỗi không mong đợi từ OpenAI API: {e}")
        raise


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(_is_transient_error),
    reraise=True
)
def _call_gemini_api(client, model_name, prompt):
    """
    Call Gemini API with retry mechanism.

    Args:
        client: Gemini client instance
        model_name: Model name to use
        prompt: Prompt to send to API

    Returns:
        str: API response text
    """
    logger.info(f"🤖 Đang sử dụng Gemini API (Model: {model_name})...")

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        # google-genai SDK mới ném ValueError khi response bị safety
        # block chặn, thay vì trả về None. Bọc trong try-except.
        try:
            text = response.text or ""
        except ValueError as e:
            # Enhancement C: Log chi tiết finish_reason để người vận hành
            # biết lý do bài viết bị bỏ qua do vi phạm safety guidelines
            finish_reason = "UNKNOWN"
            finish_details = ""
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                finish_reason = getattr(candidate, 'finish_reason', 'UNKNOWN')
                # Lấy thêm thông tin safety ratings nếu có
                if hasattr(candidate, 'safety_ratings'):
                    ratings = [str(r) for r in candidate.safety_ratings]
                    finish_details = f" | Safety Ratings: {', '.join(ratings)}"
            logger.warning(
                f"Gemini response bị chặn bởi Safety Filter! "
                f"finish_reason={finish_reason}{finish_details}. Error: {e}"
            )
            text = ""
        return text.strip()
    except Exception as e:
        if _is_transient_error(e):
            logger.warning(f"Lỗi kết nối tạm thời Gemini API (sẽ retry): {e}")
        else:
            logger.error(f"Lỗi không mong đợi từ Gemini API: {e}")
        raise


def generate_analysis_post(articles):
    """
    Gửi danh sách bài báo sang AI (Gemini hoặc OpenAI-compatible Proxy) 
    để viết bài đăng Facebook phân tích tổng hợp.

    Args:
        articles: List of article dictionaries

    Returns:
        str: Generated post content or None on failure
    """
    config = load_config()

    if not articles:
        logger.warning("Không có bài viết nào để phân tích.")
        return None

    # Apply max articles limit
    max_articles = config['settings'].get('max_articles_per_analysis', 15)
    if len(articles) > max_articles:
        logger.info(f"Giới hạn {len(articles)} bài viết xuống còn {max_articles} bài để phân tích.")
        articles = articles[:max_articles]

    # Apply summary truncation
    max_summary_length = config['settings'].get('max_summary_length', 300)

    # Chuẩn bị dữ liệu đầu vào cho AI
    context = ""
    for idx, item in enumerate(articles, 1):
        truncated_summary = truncate_summary(item['summary'], max_summary_length)
        context += (
            f"{idx}. [{item['source']}] {item['title']}\n"
            f"   Tóm tắt: {truncated_summary}\n"
            f"   Link: {item['link']}\n\n"
        )

    prompt = f"""
    Bạn là một chuyên gia phân tích thị trường ô tô Việt Nam với hơn 10 năm kinh nghiệm.
    Dưới đây là các tin tức ô tô mới nhất trong ngày:

    {context}

    Hãy viết 1 bài đăng Facebook hoàn chỉnh (khoảng 350-500 từ) phân tích tổng hợp các xu hướng/điểm tin nổi bật trên.

    Yêu cầu bắt buộc:
    1. Tiêu đề thu hút, có chứa icon/emoji phù hợp với chủ đề ô tô.
    2. Bố cục gồm:
       - Tóm tắt xu hướng chung (1-2 câu mở đầu).
       - 3 Điểm tin/Phân tích quan trọng nhất (viết theo dạng bullet point với emoji).
       - Lời kết/Góc nhìn chuyên gia.
    3. Cuối bài chèn các Hashtag liên quan đến ô tô, thị trường xe Việt Nam.
    4. Giữ giọng văn khách quan, chuyên nghiệp nhưng sinh động, dễ đọc.
    5. Sử dụng tiếng Việt, không dùng ký tự đặc biệt lạ.
    """

    provider = config.get('ai_provider', 'gemini').lower()

    # Improvement 2: Đọc ai_timeout từ config, mặc định 30 giây
    ai_timeout = config['settings'].get('ai_timeout', 30)

    try:
        if provider == 'openai':
            openai_cfg = config.get('openai', {})
            api_key = openai_cfg.get('api_key')
            base_url = openai_cfg.get('base_url')
            model_name = openai_cfg.get('model', 'gpt-4o-mini')

            # Hard timeout để tránh socket blocking vô thời hạn
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,  # Trỏ tới proxy server của bạn
                timeout=float(ai_timeout)
            )

            return _call_openai_api(client, model_name, prompt)

        elif provider == 'gemini':
            gemini_cfg = config.get('gemini', {})
            # Tự động hỗ trợ cả cấu hình cũ lẫn mới
            api_key = gemini_cfg.get('api_key') or config.get('gemini_api_key')
            model_name = gemini_cfg.get('model', 'gemini-2.5-flash')

            # Hard timeout để tránh socket blocking vô thời hạn
            client = genai.Client(
                api_key=api_key,
                http_options={"timeout": float(ai_timeout)}
            )
            return _call_gemini_api(client, model_name, prompt)

        else:
            logger.error(f"ai_provider '{provider}' không hợp lệ trong config.json (chỉ chọn 'openai' hoặc 'gemini').")
            return None

    except Exception as e:
        logger.error(f"Lỗi khi gọi AI API ({provider}): {e}")
        return None


if __name__ == "__main__":
    from scraper import fetch_latest_news
    articles = fetch_latest_news()
    post_text = generate_analysis_post(articles)
    logger.info("\n--- NỘI DUNG AI TẠO ---")
    logger.info(post_text)
