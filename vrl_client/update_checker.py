#!/usr/bin/env python3
"""
update_checker.py - Перевіра оновлень VRL Client

Використання:
    python update_checker.py
    
Функції:
    - Перевіряє останню версію на GitHub
    - Порівнює з локальною версією
    - Показує посилання на завантаження
"""

import requests
import json
from pathlib import Path
from packaging import version
import sys

# GitHub API параметри
GITHUB_OWNER = "YOUR_USERNAME"      # Замініть на ваш username
GITHUB_REPO = "vrl-client"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"

# Локальна версія
LOCAL_VERSION = "0.1.0"


def get_latest_release():
    """Отримуємо інформацію про останній Release на GitHub"""
    try:
        response = requests.get(
            f"{GITHUB_API}/releases/latest",
            timeout=5
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Помилка при з'єднанні з GitHub: {e}")
        return None


def parse_version(tag):
    """Парсимо версію з тега (v1.0.0 → 1.0.0)"""
    return tag.lstrip('v')


def check_for_updates():
    """Перевіряємо наявність оновлень"""
    print("🔍 Перевірка оновлень...")
    print(f"   Локальна версія: {LOCAL_VERSION}")
    
    release = get_latest_release()
    
    if not release:
        print("⚠️  Не вдалося перевірити оновлення")
        return False
    
    latest_tag = release.get('tag_name', 'unknown')
    latest_version = parse_version(latest_tag)
    
    print(f"   Останна версія:  {latest_version}")
    
    # Порівняння версій
    try:
        if version.parse(latest_version) > version.parse(LOCAL_VERSION):
            print(f"\n✅ ДОСТУПНЕ ОНОВЛЕННЯ: {LOCAL_VERSION} → {latest_version}")
            print(f"\n📝 Що нового:")
            
            # Показуємо release notes
            body = release.get('body', 'Немає опису')
            print(f"   {body[:500]}")
            
            # Посилання на завантаження
            print(f"\n📥 Завантажити:")
            for asset in release.get('assets', []):
                if asset['name'].endswith('.exe'):
                    print(f"   {asset['browser_download_url']}")
            
            print(f"\n🌐 Або перейти на GitHub:")
            print(f"   {release['html_url']}")
            
            return True
        else:
            print(f"✅ Ви використовуєте останню версію ({LOCAL_VERSION})")
            return False
    
    except Exception as e:
        print(f"❌ Помилка при порівнянні версій: {e}")
        return False


if __name__ == '__main__':
    print("═" * 60)
    print("VRL CLIENT - ПЕРЕВІРКА ОНОВЛЕНЬ")
    print("═" * 60)
    print()
    
    has_update = check_for_updates()
    
    print()
    print("═" * 60)
    
    sys.exit(0 if not has_update else 1)
