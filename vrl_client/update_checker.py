#!/usr/bin/env python3
"""
update_checker.py - Перевіра та завантаження оновлень VRL Client

ВАЖЛИВО:
    - Це утиліта ДЛЯ КОРИСТУВАЧІВ (не для розробників)
    - Запускається ВРУЧНУ (не автоматично при старті)
    - Перевіряє тільки exe файл на GitHub Releases
    - Може завантажити новий exe, але НЕ встановлює автоматично

Використання:
    python update_checker.py         # Перевірити оновлення
    python update_checker.py --download   # Завантажити нову версію

СЦЕНАРІЙ ОНОВЛЕННЯ:
    1. Користувач запускає: python update_checker.py
    2. Програма перевіряє GitHub на новішу версію
    3. Якщо є оновлення:
       - Показує що нового
       - Дає посилання на завантаження
       - Пропонує завантажити exe
    4. Користувач завантажує exe
    5. Замінює старий файл новим
    6. Готово! (config.yaml та base.db зберігаються)
"""

import requests
import json
import sys
import os
from pathlib import Path
from packaging import version
import logging

logger = logging.getLogger(__name__)

# ============================================================
# ПАРАМЕТРИ
# ============================================================

GITHUB_OWNER = "Hyrol7"           # Реальний username
GITHUB_REPO = "vrl-client"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_RELEASES = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"

# Локальна версія (синхронізується з vrl.py)
LOCAL_VERSION = "0.1.0"

# Назва exe файлу
EXE_FILENAME = "VRL_Client.exe"
EXE_SIZE_MAX_MB = 150  # Максимальний очікуваний розмір


# ============================================================
# ФУНКЦІЇ
# ============================================================

def get_latest_release():
    """
    Отримуємо інформацію про останній Release на GitHub
    
    ПОВЕРТАЄ:
        - release (dict): інформація про релиз або None
    """
    try:
        response = requests.get(
            f"{GITHUB_API}/releases/latest",
            timeout=10,
            headers={'Accept': 'application/vnd.github.v3+json'}
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print("❌ ПОМИЛКА: Timeout при з'єднанні з GitHub (інтернет повільний)")
        return None
    except requests.exceptions.ConnectionError:
        print("❌ ПОМИЛКА: Не можу під'єднатися до GitHub (можливо немає інтернету)")
        return None
    except Exception as e:
        print(f"❌ ПОМИЛКА при з'єднанні з GitHub: {e}")
        return None


def parse_version(tag):
    """
    Парсимо версію з тега (v1.0.0 → 1.0.0)
    
    ПАРАМЕТРИ:
        - tag: строка з версією (наприклад "v0.1.0")
    
    ПОВЕРТАЄ:
        - version_str (str): версія без 'v'
    """
    return tag.lstrip('v')


def get_exe_download_url(release):
    """
    Отримуємо посилання на exe файл з релізу
    
    ПАРАМЕТРИ:
        - release (dict): інформація про релиз
    
    ПОВЕРТАЄ:
        - (download_url, file_size): посилання та розмір або (None, None)
    """
    for asset in release.get('assets', []):
        if asset['name'] == EXE_FILENAME:
            return asset['browser_download_url'], asset['size']
    return None, None


def download_exe(download_url, output_path):
    """
    Завантажуємо exe файл з GitHub
    
    ПАРАМЕТРИ:
        - download_url (str): посилання на файл
        - output_path (str): шлях де зберегти
    
    ПОВЕРТАЄ:
        - True/False: успіх завантаження
    """
    try:
        print(f"\n📥 Завантаження {output_path.name}...")
        
        response = requests.get(download_url, stream=True, timeout=60)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Показуємо прогрес
                    if total_size:
                        percent = (downloaded / total_size) * 100
                        mb_downloaded = downloaded / (1024 * 1024)
                        mb_total = total_size / (1024 * 1024)
                        print(f"  [{percent:.1f}%] {mb_downloaded:.1f}MB / {mb_total:.1f}MB", end='\r')
        
        print(f"\n✅ Завантажено успішно: {output_path}")
        return True
    
    except Exception as e:
        print(f"\n❌ ПОМИЛКА при завантаженні: {e}")
        if output_path.exists():
            output_path.unlink()
        return False


def check_for_updates(verbose=True):
    """
    Перевіряємо наявність оновлень
    
    ПАРАМЕТРИ:
        - verbose (bool): виводити деталі
    
    ПОВЕРТАЄ:
        - release_info (dict) або None якщо немає оновлення
    """
    if verbose:
        print("🔍 Перевірка оновлень...")
        print(f"   Локальна версія: {LOCAL_VERSION}")
    
    release = get_latest_release()
    
    if not release:
        print("⚠️  Не вдалося перевірити оновлення")
        return None
    
    latest_tag = release.get('tag_name', 'unknown')
    latest_version = parse_version(latest_tag)
    
    if verbose:
        print(f"   Остання версія:  {latest_version}")
    
    # Порівняння версій
    try:
        if version.parse(latest_version) > version.parse(LOCAL_VERSION):
            if verbose:
                print(f"\n✅ ДОСТУПНЕ ОНОВЛЕННЯ: {LOCAL_VERSION} → {latest_version}")
                
                # Показуємо release notes
                body = release.get('body', 'Немає опису')
                print(f"\n📝 Що нового:")
                print(f"   {body[:500]}")
                
                # Інформація про exe
                exe_url, exe_size = get_exe_download_url(release)
                if exe_url:
                    exe_size_mb = exe_size / (1024 * 1024)
                    print(f"\n📥 Файл для завантаження:")
                    print(f"   {EXE_FILENAME} ({exe_size_mb:.1f} MB)")
                    print(f"\n🔗 Посилання:")
                    print(f"   {exe_url}")
                
                print(f"\n🌐 GitHub Release:")
                print(f"   {release['html_url']}")
                
                print(f"\n💡 Як оновити:")
                print(f"   1. Завантажити: python update_checker.py --download")
                print(f"   2. Замінити старий exe на новий")
                print(f"   3. config.yaml та base.db будуть збережені")
            
            return release
        else:
            if verbose:
                print(f"✅ Ви використовуєте останню версію ({LOCAL_VERSION})")
            return None
    
    except Exception as e:
        print(f"❌ ПОМИЛКА при порівнянні версій: {e}")
        return None


def download_latest_exe():
    """
    Завантажуємо останню версію exe
    
    ПОВЕРТАЄ:
        - True/False: успіх
    """
    print("═" * 60)
    print("ЗАВАНТАЖЕННЯ ОНОВЛЕННЯ")
    print("═" * 60)
    print()
    
    release = check_for_updates(verbose=True)
    
    if not release:
        print("\n⚠️  Немає оновлень для завантаження")
        return False
    
    exe_url, exe_size = get_exe_download_url(release)
    
    if not exe_url:
        print(f"\n❌ ПОМИЛКА: Не знайдений файл {EXE_FILENAME} в релізі")
        return False
    
    # Перевіряємо розмір
    exe_size_mb = exe_size / (1024 * 1024)
    if exe_size_mb > EXE_SIZE_MAX_MB:
        print(f"\n❌ ПОМИЛКА: Файл надто великий ({exe_size_mb:.1f} MB > {EXE_SIZE_MAX_MB} MB)")
        return False
    
    # Визначаємо де зберегти
    download_dir = Path(__file__).parent / "downloads"
    download_dir.mkdir(exist_ok=True)
    
    output_path = download_dir / EXE_FILENAME
    
    # Завантажуємо
    success = download_exe(exe_url, output_path)
    
    if success:
        print(f"\n✅ ОНОВЛЕННЯ ГОТОВЕ!")
        print(f"\n📂 Файл збережений: {output_path}")
        print(f"\n🔧 Наступні кроки:")
        print(f"   1. Закрити поточну версію програми (якщо запущена)")
        print(f"   2. Замінити старий exe новим з папки 'downloads'")
        print(f"   3. Запустити нову версію")
        print(f"   4. config.yaml та base.db будуть на місці")
        return True
    
    return False


# ============================================================
# ТОЧКА ВХОДУ
# ============================================================

if __name__ == '__main__':
    print("═" * 60)
    print("VRL CLIENT - ПЕРЕВІРКА ОНОВЛЕНЬ")
    print("═" * 60)
    print()
    
    # Обробка аргументів
    if len(sys.argv) > 1 and sys.argv[1] == '--download':
        # Завантажити нову версію
        success = download_latest_exe()
        sys.exit(0 if success else 1)
    else:
        # Тільки перевірити
        print(f"GitHub: {GITHUB_OWNER}/{GITHUB_REPO}")
        print(f"URL: {GITHUB_RELEASES}")
        print()
        
        has_update = check_for_updates(verbose=True)
        
        print()
        print("═" * 60)
        
        sys.exit(0 if not has_update else 1)

