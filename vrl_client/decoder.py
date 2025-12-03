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
import psutil
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================
# ЗАПУСК ДЕКОДЕРА
# ============================================================

def kill_existing_decoders(process_name):
    """
    Знаходимо та завершуємо всі процеси з вказаним ім'ям
    
    ПАРАМЕТРИ:
        - process_name: ім'я виконуваного файлу (наприклад 'uvd_rtl.exe')
    """
    logger.info(f"  → Перевірка запущених процесів '{process_name}'...")
    killed_count = 0
    
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == process_name.lower():
                logger.warning(f"     Знайдено старий процес (PID: {proc.info['pid']}). Завершуємо...")
                proc.terminate()
                killed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
            
    if killed_count > 0:
        logger.info(f"     Очікуємо завершення {killed_count} процесів...")
        # Даємо час на коректне завершення
        gone, alive = psutil.wait_procs([p for p in psutil.process_iter() if p.name().lower() == process_name.lower()], timeout=3)
        
        for p in alive:
            logger.warning(f"     Процес {p.pid} не завершився, вбиваємо примусово (KILL)...")
            p.kill()
            
        logger.info(f"  ✓ Всі старі копії декодера зупинені")
    else:
        logger.info(f"  ✓ Старих копій не знайдено")


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
    
    app_decoder = config['decoder']['app_decoder']
    executable = os.path.join(config['decoder']['path'], app_decoder)
    args = config['decoder']['command_args']
    
    # КРОК 1: Вбиваємо старі процеси
    try:
        kill_existing_decoders(app_decoder)
    except Exception as e:
        logger.warning(f"  ⚠ Помилка при очистці процесів: {e}")
    
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
