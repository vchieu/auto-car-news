"""
Centralized Configuration Loader Module

This module provides centralized configuration management with validation
for the auto-car-news project. It handles loading, validation, and provides
fallback defaults for optional settings.

Author: Auto Car News Bot
"""

import json
import os
import logging

# Configure logger for this module
logger = logging.getLogger(__name__)

# Base directory for all file paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')


# Improvement 1: Custom Exception thay vì gọi sys.exit(1) trực tiếp
# Giúp cho việc viết Unit Test và tái sử dụng hàm trong module khác dễ dàng.
# Cấp gọi chính (main.py) sẽ chịu trách nhiệm exit ứng dụng.
class ConfigurationError(Exception):
    """Raised when configuration is missing or invalid."""
    pass


def load_config():
    """
    Load and validate configuration from config.json or environment variables.
    
    Hỗ trợ đầy đủ cho Docker/Kubernetes/Cloud PaaS:
    - Nếu KHÔNG có file config.json → khởi tạo dict rỗng và dùng Env Vars.
    - Nếu có file config.json → đọc file, sau đó Env Vars sẽ override.
    
    Validates required sections: rss_sources, facebook, settings
    Validates facebook has page_id and access_token
    Provides fallback defaults for settings
    
    Returns:
        dict: Validated configuration dictionary
        
    Raises:
        ConfigurationError: If config is missing required sections or fields.
    """
    # BUG 1 FIX: Thứ tự xử lý: JSON → Env Vars → Defaults → Validate
    # 1. Đọc file JSON hoặc khởi tạo dict rỗng
    if not os.path.exists(CONFIG_PATH):
        logger.warning(f"Không thấy file config.json tại {CONFIG_PATH}. Sử dụng biến môi trường.")
        config = {"rss_sources": [], "facebook": {}, "settings": {}}
    else:
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"File config.json không hợp lệ: {e}")
            raise ConfigurationError(f"File config.json không hợp lệ: {e}") from e
        except IOError as e:
            logger.error(f"Không thể đọc file config.json: {e}")
            raise ConfigurationError(f"Không thể đọc file config.json: {e}") from e

    # 2. ĐỌC BIẾN MÔI TRƯỜNG TRƯỚC (Ưu tiên cao nhất)
    if os.environ.get("GEMINI_API_KEY"):
        config.setdefault('gemini', {})['api_key'] = os.environ.get("GEMINI_API_KEY")
        logger.info("GEMINI_API_KEY loaded from environment variable.")

    if os.environ.get("OPENAI_API_KEY"):
        config.setdefault('openai', {})['api_key'] = os.environ.get("OPENAI_API_KEY")
        logger.info("OPENAI_API_KEY loaded from environment variable.")

    if os.environ.get("FB_ACCESS_TOKEN"):
        config.setdefault('facebook', {})['access_token'] = os.environ.get("FB_ACCESS_TOKEN")
        logger.info("FB_ACCESS_TOKEN loaded from environment variable.")

    if os.environ.get("FB_PAGE_ID"):
        config.setdefault('facebook', {})['page_id'] = os.environ.get("FB_PAGE_ID")
        logger.info("FB_PAGE_ID loaded from environment variable.")

    # 3. GÁN DEFAULT VALUES
    settings_defaults = {
        'max_articles_per_source': 10,
        'run_time': '08:00',
        'max_summary_length': 300,
        'max_articles_per_analysis': 15,
        'ai_timeout': 30
    }
    for key, default_value in settings_defaults.items():
        if key not in config['settings']:
            config['settings'][key] = default_value

    if 'api_version' not in config['facebook']:
        config['facebook']['api_version'] = 'v19.0'

    # 4. VALIDATE (Sau khi đã nạp đủ dữ liệu từ Env Vars)
    required_sections = ['rss_sources', 'facebook', 'settings']
    for section in required_sections:
        if section not in config:
            raise ConfigurationError(f"Thiếu section bắt buộc '{section}' trong config.json/Env Vars")

    facebook_required = ['page_id', 'access_token']
    for field in facebook_required:
        if field not in config['facebook']:
            raise ConfigurationError(f"Thiếu trường '{field}' trong section 'facebook'")
        if not config['facebook'][field] or config['facebook'][field] == f'YOUR_{field.upper()}':
            logger.warning(f"Trường '{field}' trong 'facebook' chưa được cấu hình hợp lệ.")

    return config


def get_facebook_api_version():
    """
    Get the Facebook Graph API version from config.
    
    Returns:
        str: Facebook API version (e.g., 'v19.0')
    """
    try:
        config = load_config()
        return config['facebook'].get('api_version', 'v19.0')
    except ConfigurationError:
        return 'v19.0'  # Default fallback


if __name__ == "__main__":
    # Test configuration loading
    logger.info("🔧 Kiểm tra config_loader.py...")
    try:
        config = load_config()
        logger.info("✅ Config loaded successfully!")
        logger.info(f"📡 Số nguồn RSS: {len(config['rss_sources'])}")
        logger.info(f"🤖 AI Provider: {config.get('ai_provider', 'gemini')}")
        logger.info(f"📘 Facebook API Version: {config['facebook'].get('api_version', 'v19.0')}")
    except ConfigurationError as e:
        logger.error(f"❌ Config loading failed: {e}")
