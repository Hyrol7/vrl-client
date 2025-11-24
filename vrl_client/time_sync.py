#!/usr/bin/env python3
"""
time_sync.py - Синхронізація та налаштування часу

Функції:
    - get_timezone_offset() - отримуємо offset часового поясу
    - get_ntp_time() - час з NTP сервера
    - sync_system_time() - синхронізуємо системний час з врахуванням часового поясу
"""

import sys
import subprocess
import logging
import platform
import json
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================
# СИНХРОНІЗАЦІЯ ЧАСУ
# ============================================================

def get_timezone_offset(timezone_str):
    """
    Отримуємо offset часового поясу від UTC
    
    ПАРАМЕТРИ:
        - timezone_str: назва часового поясу (наприклад 'Europe/Kiev')
    
    ПОВЕРТАЄ:
        - offset: різниця від UTC в секундах
    """
    try:
        import pytz
        tz = pytz.timezone(timezone_str)
        now = datetime.now(tz)
        offset = now.utcoffset().total_seconds()
        return offset
    except Exception:
        # Альтернативний спосіб без pytz
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(timezone_str)
            now = datetime.now(tz)
            offset = now.utcoffset().total_seconds()
            return offset
        except Exception:
            logger.warning(f"  ⚠ Не вдалося визначити часовий пояс: {timezone_str}")
            return 0


def get_ntp_time(ntp_server='pool.ntp.org'):
    """
    Отримуємо точний час з NTP сервера
    
    ПАРАМЕТРИ:
        - ntp_server: адреса NTP сервера
    
    ПОВЕРТАЄ:
        - (unix_timestamp, is_success): час та статус
    """
    try:
        import ntplib
    except ImportError:
        return None, False
    
    try:
        client = ntplib.NTPClient()
        response = client.request(ntp_server, version=3, timeout=5)
        return response.tx_time, True
    except Exception:
        return None, False


def sync_system_time(config):
    """
    Синхронізуємо системний час з NTP сервером
    Враховуємо часовий пояс з конфіги
    
    ПАРАМЕТРИ:
        - config: конфігурація проекту
    
    ПОВЕРТАЄ:
        - (success, message): успіх та повідомлення про стан
    """
    logger.info("═" * 60)
    logger.info("ЕТАП: СИНХРОНІЗАЦІЯ ЧАСУ")
    logger.info("═" * 60)
    
    # Отримуємо часовий пояс
    timezone_str = config['app'].get('timezone', 'UTC')
    current_timezone_offset = get_timezone_offset(timezone_str)
    
    local_time = datetime.now()
    logger.info(f"  Локальний час:  {local_time.isoformat()}")
    logger.info(f"  Часовий пояс:   {timezone_str}\n")
    
    # Спробуємо отримати час з Інтернету кількома способами
    
    # Спосіб 1: NTP (якщо встановлено ntplib)
    ntp_time, ntp_ok = get_ntp_time()
    if ntp_ok and ntp_time:
        ntp_datetime = datetime.utcfromtimestamp(ntp_time)
        logger.info(f"  NTP час (UTC):  {ntp_datetime.isoformat()}")
        
        diff = abs((ntp_datetime - local_time).total_seconds())
        
        if diff > 5:
            logger.warning(f"  ⚠ Різниця: {diff:.1f} сек")
            
            if platform.system() == 'Windows':
                logger.info(f"  → Спроба синхронізації на Windows...")
                try:
                    result = subprocess.run(
                        ['w32tm', '/resync', '/force'],
                        capture_output=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        logger.info(f"  ✓ Час синхронізований успішно через w32tm")
                        logger.info()
                        return True, "Час синхронізований через w32tm"
                    else:
                        logger.warning(f"  ⚠ w32tm не удалося виконати")
                except Exception as e:
                    logger.warning(f"  ⚠ Помилка w32tm: {e}")
            
            elif platform.system() == 'Darwin':  # macOS
                logger.info(f"  → Спроба синхронізації на macOS...")
                try:
                    subprocess.run(['sntp', '-sS', 'pool.ntp.org'], timeout=10, check=True)
                    logger.info(f"  ✓ Час синхронізований успішно через sntp")
                    logger.info()
                    return True, "Час синхронізований через sntp"
                except Exception as e:
                    logger.warning(f"  ⚠ Помилка sntp: {e}")
            
            elif platform.system() == 'Linux':
                logger.info(f"  → Спроба синхронізації на Linux...")
                try:
                    subprocess.run(['timedatectl', 'set-ntp', 'true'], timeout=10, check=True)
                    logger.info(f"  ✓ Час синхронізований успішно через timedatectl")
                    logger.info()
                    return True, "Час синхронізований через timedatectl"
                except Exception as e:
                    logger.warning(f"  ⚠ Помилка timedatectl: {e}")
            
            # Якщо автоматична синхронізація не вдалася
            logger.warning(f"  ⚠ Автоматична синхронізація не вдалася")
            logger.warning(f"     Будемо враховувати часовий пояс при записі в БД")
            logger.info()
            return False, f"Часова різниця {diff:.1f}с — враховуємо пояс"
        else:
            logger.info(f"  ✓ Час синхронізований (різниця < 5с)")
            logger.info()
            return True, "Час актуальний"
    
    # Спосіб 2: HTTP запит на worldtimeapi
    logger.warning(f"  ⚠ NTP недоступен, пробуємо HTTP запит...")
    
    try:
        import urllib.request
        response = urllib.request.urlopen('http://worldtimeapi.org/api/timezone/Etc/UTC', timeout=5)
        data = json.loads(response.read())
        
        http_datetime = datetime.fromisoformat(data['datetime'].replace('Z', '+00:00'))
        logger.info(f"  HTTP час (UTC): {http_datetime.isoformat()}")
        
        diff = abs((http_datetime - local_time).total_seconds())
        
        if diff > 5:
            logger.warning(f"  ⚠ Різниця: {diff:.1f} сек — враховуємо пояс при записі")
            logger.info()
            return False, f"Часова різниця {diff:.1f}с — враховуємо пояс"
        else:
            logger.info(f"  ✓ Час синхронізований (різниця < 5с)")
            logger.info()
            return True, "Час актуальний"
    
    except Exception as e:
        logger.warning(f"  ⚠ HTTP запит не вдався: {e}")
        logger.warning(f"     Будемо використовувати локальний час")
        logger.warning(f"     ВАЖЛИВО: Переконайтесь, що локальний час встановлений правильно!")
        logger.info()
        return False, "Використовуємо локальний час"
