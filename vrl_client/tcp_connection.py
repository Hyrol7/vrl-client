#!/usr/bin/env python3
"""
tcp_connection.py - Перевірка та управління TCP підключенням до декодера

Функції:
    - wait_for_decoder_connection() - чекаємо доступу TCP-порту декодера
    - check_tcp_port() - перевіряємо наявність TCP-порту
"""

import asyncio
import socket
import logging

logger = logging.getLogger(__name__)


# ============================================================
# TCP ПІДКЛЮЧЕННЯ
# ============================================================

def check_tcp_port(host, port, timeout=5):
    """
    Перевіряємо наявність TCP-порту
    
    ПАРАМЕТРИ:
        - host: адреса хоста
        - port: номер порту
        - timeout: timeout для підключення
    
    ПОВЕРТАЄ:
        - True/False: успіх підключення
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


async def wait_for_decoder_connection(config, db_file):
    """
    Чекаємо доступу TCP-порту декодера
    
    ПАРАМЕТРИ:
        - config: конфігурація проекту
        - db_file: шлях до БД (для логування)
    
    ПОВЕРТАЄ:
        - True: успіх підключення
        - False: помилка (і вихід з програми)
    """
    logger.info("═" * 60)
    logger.info("ЕТАП 4: ОЧІКУВАННЯ ПІДКЛЮЧЕННЯ ДО ДЕКОДЕРА")
    logger.info("═" * 60)
    
    host = config['decoder']['host']
    port = config['decoder']['port']
    timeout = config['decoder']['timeout']
    reconnect_delay = config['decoder']['reconnect_delay']
    
    max_attempts = 10
    attempt = 0
    
    while attempt < max_attempts:
        attempt += 1
        logger.info(f"  → Спроба {attempt}/{max_attempts}: підключення до {host}:{port}...")
        
        if check_tcp_port(host, port, timeout):
            logger.info(f"  ✓ TCP підключення встановлено ({host}:{port})")
            logger.info(f"     Декодер готовий до роботи\n")
            
            from initialization import log_to_db
            log_to_db(db_file, 'INFO', 'TCP', 'TCP підключення встановлено', f"{host}:{port}")
            
            return True
        
        else:
            logger.warning(f"  ⚠ Декодер недоступний, чекаємо {reconnect_delay}с...")
            await asyncio.sleep(reconnect_delay)
    
    # Перевищили максимум спроб
    logger.error(f"  ❌ ПОМИЛКА: Не вдалося підключитися до декодера після {max_attempts} спроб")
    logger.error(f"     Перевірте:")
    logger.error(f"       1. Чи декодер запущений?")
    logger.error(f"       2. Чи він слухає на {host}:{port}?")
    logger.error(f"       3. Правильні параметри у config.yaml?\n")
    
    from initialization import log_to_db
    log_to_db(db_file, 'ERROR', 'TCP', 'TCP підключення не встановлено', f"Max attempts exceeded")
    
    return False
