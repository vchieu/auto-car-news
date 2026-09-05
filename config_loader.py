"""
Centralized Configuration Loader Module

This module provides centralized configuration management with validation
for the auto-car-news project. It handles loading, validation, and provides
fallback defaults for optional settings.

Author: Auto Car News Bot
"""

import json
import os
import sys

# Base directory for all file paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')


def load_config():
    """
    Load and validate configuration from config.json.
    
    Validates required sections: rss_sources, facebook, settings
    Validates facebook has page_id and access_token
    Provides fallback defaults for settings
    
    Returns:
        dict: Validated configuration dictionary
        
    Raises:
        SystemExit: If config file is missing or invalid
    """
    # Check if config file exists
    if not os.path.exists(CONFIG_PATH):
        print(f"❌ Lỗi: Không tìm thấy file config.json tại: {CONFIG_PATH}")
        print("📝 Vui lòng sao chép config.example.json thành config.json và cấu hình các giá trị cần thiết.")
        sys.exit(1)
    
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Lỗi: File config.json không hợp lệ (JSON decode error): {e}")
        print("📝 Vui lòng kiểm tra cú pháp JSON trong config.json.")
        sys.exit(1)
    except IOError as e:
        print(f"❌ Lỗi: Không thể đọc file config.json: {e}")
        sys.exit(1)
    
    # Validate required sections
    required_sections = ['rss_sources', 'facebook', 'settings']
    for section in required_sections:
        if section not in config:
            print(f"❌ Lỗi: Thiếu section bắt buộc '{section}' trong config.json")
            sys.exit(1)
    
    # Validate facebook section has required fields
    facebook_required = ['page_id', 'access_token']
    for field in facebook_required:
        if field not in config['facebook']:
            print(f"❌ Lỗi: Thiếu trường '{field}' trong section 'facebook'")
            sys.exit(1)
        if not config['facebook'][field] or config['facebook'][field] == f'YOUR_{field.upper()}':
            print(f"⚠️ Cảnh báo: Trường '{field}' trong 'facebook' chưa được cấu hình.")
    
    # Provide fallback defaults for settings
    settings_defaults = {
        'max_articles_per_source': 10,
        'run_time': '08:00',
        'max_summary_length': 300,
        'max_articles_per_analysis': 15
    }
    
    for key, default_value in settings_defaults.items():
        if key not in config['settings']:
            config['settings'][key] = default_value
    
    # Provide fallback defaults for facebook api_version
    if 'api_version' not in config['facebook']:
        config['facebook']['api_version'] = 'v19.0'
    
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
    except SystemExit:
        return 'v19.0'  # Default fallback


if __name__ == "__main__":
    # Test configuration loading
    print("🔧 Kiểm tra config_loader.py...")
    try:
        config = load_config()
        print("✅ Config loaded successfully!")
        print(f"📡 Số nguồn RSS: {len(config['rss_sources'])}")
        print(f"🤖 AI Provider: {config.get('ai_provider', 'gemini')}")
        print(f"📘 Facebook API Version: {config['facebook'].get('api_version', 'v19.0')}")
    except SystemExit:
        print("❌ Config loading failed.")
