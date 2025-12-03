#!/usr/bin/env python3
"""
decoder.py - Запуск та управління декодером

Функції:
    - start_decoder() - запускаємо декодер як підпроцес
    - stop_decoder() - зупиняємо декодер
"""

import sys
import os
import time
import signal
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================
# ЗАПУСК ДЕКОДЕРА
# ============================================================

def start_decoder(config, db_file):
    """
    Запускаємо програму декодера як підпроцес
    
    ПАРАМЕТРИ:
        - config: конфігурація проекту
        - db_file: шлях до БД (для логування помилок)
    
    ПОВЕРТАЄ:
        - process (Popen): об'єкт підпроцесу
        - Завершує програму якщо помилка
    """
    logger.info("═" * 60)
    logger.info("ЕТАП: ЗАПУСК ДЕКОДЕРА")
    logger.info("═" * 60)
    
    executable = os.path.join(config['decoder']['path'], config['decoder']['app_decoder'])
    args = config['decoder']['command_args']
    
    # Перевіряємо наявність виконуваного файлу
    if not os.path.exists(executable):
        logger.error(f"  ❌ ПОМИЛКА: Декодер не знайдений")
        logger.error(f"     Очікуваний шлях: {executable}")
        logger.error(f"     Виправте параметр decoder.executable у config.yaml\n")
        
        from initialization import log_to_db
        log_to_db(db_file, 'ERROR', 'DECODER', 'Декодер не знайдений', f"Path: {executable}")
        sys.exit(1)
    
    try:
        logger.info(f"  → Запускаємо: {executable} {args}")
        
        # Парсимо аргументи в список (якщо потрібно)
        args_list = args.split() if isinstance(args, str) else args
        
        process = subprocess.Popen(
            [executable] + args_list,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
        )
        
        logger.info(f"  ✓ Декодер запущений")
        logger.info(f"     PID: {process.pid}")
        
        # Чекаємо 2 секунди, щоб переконатися, що процес не впав відразу
        time.sleep(2)
        
        if process.poll() is not None:
            # Процес завершився майже відразу - це помилка
            raise RuntimeError(f"Декодер завершив роботу відразу після запуску (код {process.returncode})")
            
        logger.info(f"     Статус: Працює стабільно\n")
        
        from initialization import log_to_db
        log_to_db(db_file, 'INFO', 'DECODER', 'Декодер запущений', f"PID: {process.pid}")
        
        return process
    
    except Exception as e:
        logger.error(f"  ❌ ПОМИЛКА при запуску декодера: {e}\n")
        
        from initialization import log_to_db
        log_to_db(db_file, 'ERROR', 'DECODER', 'Помилка запуску', str(e))
        sys.exit(1)


def stop_decoder(decoder_process):
    """
    Зупиняємо декодер коректно
    
    ПАРАМЕТРИ:
        - decoder_process: об'єкт підпроцесу
    
    ПОВЕРТАЄ:
        - None
    """
    if not decoder_process:
        return
    
    try:
        logger.info("  → Зупиняємо декодер...")
        
        if sys.platform == 'win32':
            os.kill(decoder_process.pid, signal.SIGTERM)
        else:
            decoder_process.terminate()
        
        # Чекаємо завершення
        decoder_process.wait(timeout=5)
        
        logger.info("  ✓ Декодер зупинений")
    
    except subprocess.TimeoutExpired:
        logger.warning("  ⚠ Декодер не відповідає, примусово завершуємо...")
        decoder_process.kill()
    
    except Exception as e:
        logger.error(f"  ⚠ Помилка при зупинку декодера: {e}")
