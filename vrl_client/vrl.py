#!/usr/bin/env python3
"""
vrl.py - Головний файл для запуску VRL Client
Координує всі модулі та етапи ініціалізації

АРХІТЕКТУРА:
    - initialization.py: перевірка залежностей, конфіг, БД
    - time_sync.py: синхронізація часу
    - decoder.py: запуск декодера
    - tcp_connection.py: перевірка TCP підключення
    - ping_handler.py: периодичний ping на API
    - parser.py: парсинг TCP даних від декодера
    - analyser.py: обробка та біндинг даних
    - sender.py: відправка на API

ПОСЛІДОВНІСТЬ:
    1. Перевірка залежностей (initialization.check_dependencies)
    2. Завантаження конфігурації (initialization.load_config)
    3. Ініціалізація БД (initialization.init_database)
    4. Синхронізація часу (time_sync.sync_system_time)
    5. Запуск декодера (decoder.start_decoder)
    6. Очікування TCP підключення (tcp_connection.wait_for_decoder_connection)
    7. Запуск ping loop (ping_handler.ping_loop) - в фоні
    8. Запуск parser, analyser, sender - в фоні
"""

import sys
import signal
import logging
import asyncio
from pathlib import Path

# Імпортуємо всі модулі
from initialization import check_dependencies, load_config, init_database, log_to_db
from time_sync import sync_system_time
from decoder import start_decoder, stop_decoder
from tcp_connection import wait_for_decoder_connection
from ping_handler import PingStatus, ping_loop

# ============================================================
# ЛОГУВАННЯ
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# ГЛОБАЛЬНИЙ СТАН
# ============================================================

class AppState:
    """Глобальний стан програми"""
    def __init__(self):
        self.decoder_process = None
        self.db_file = None
        self.config = None
        self.ping_status = None


app_state = AppState()


# ============================================================
# ОБРОБНИК СИГНАЛІВ
# ============================================================

def signal_handler(sig, frame):
    """Обробник SIGINT для коректного завершення"""
    logger.info("\n" + "═" * 60)
    logger.info("ЗАВЕРШЕННЯ ПРОГРАМИ")
    logger.info("═" * 60)
    logger.info("[!] Сигнал переривання отримано...")
    
    # Зупиняємо декодер
    if app_state.decoder_process:
        stop_decoder(app_state.decoder_process)
    
    # Записуємо лог в БД
    if app_state.db_file:
        try:
            log_to_db(app_state.db_file, 'INFO', 'MAIN', 'Програма завершена користувачем', None)
        except:
            pass
    
    logger.info("\n✓ Програма корректно завершена")
    sys.exit(0)


# ============================================================
# ОСНОВНА ФУНКЦІЯ
# ============================================================

async def main():
    """
    Основна функція з послідовною ініціалізацією всіх модулів
    
    ПОСЛІДОВНІСТЬ ЕТАПІВ:
    0. Перевірка залежностей
    1. Завантаження конфігурації
    2. Ініціалізація БД
    3. Синхронізація часу
    4. Запуск декодера
    5. Очікування TCP підключення
    6. Запуск ping loop (фоні)
    7. Готовність до запуску parser, analyser, sender
    """
    
    # Обробник SIGINT
    signal.signal(signal.SIGINT, signal_handler)
    
    logger.info("\n")
    
    # ========================================
    # ЕТАП 0: Перевірка залежностей
    # ========================================
    if not check_dependencies():
        sys.exit(1)
    
    # ========================================
    # ЕТАП 1: Завантаження конфігурації
    # ========================================
    config = load_config()
    app_state.config = config
    
    # ========================================
    # ЕТАП 2: Ініціалізація БД
    # ========================================
    db_file = init_database(config)
    app_state.db_file = db_file
    
    log_to_db(db_file, 'INFO', 'MAIN', 'Програма запущена', f"Version: {config['app']['version']}")
    
    # ========================================
    # ЕТАП 3: Синхронізація часу
    # ========================================
    time_synced, time_message = sync_system_time(config)
    
    # ========================================
    # ЕТАП 4: Запуск декодера
    # ========================================
    decoder_process = start_decoder(config, db_file)
    app_state.decoder_process = decoder_process
    
    # ========================================
    # ЕТАП 5: Очікування TCP підключення
    # ========================================
    connected = await wait_for_decoder_connection(config, db_file)
    
    if not connected:
        logger.error("❌ Не вдалося підключитися до декодера")
        log_to_db(db_file, 'ERROR', 'MAIN', 'Не вдалося підключитися до декодера', None)
        
        stop_decoder(decoder_process)
        sys.exit(1)
    
    # ========================================
    # ГОТОВО: Всі етапи завершені
    # ========================================
    
    logger.info("═" * 60)
    logger.info("✅ ІНІЦІАЛІЗАЦІЯ ЗАВЕРШЕНА УСПІШНО")
    logger.info("═" * 60)
    logger.info(f"  • Версія: {config['app']['name']} v{config['app']['version']}")
    logger.info(f"  • БД: {db_file}")
    logger.info(f"  • Декодер: {config['decoder']['host']}:{config['decoder']['port']} (TCP)")
    logger.info(f"  • API: {config['api']['url']}")
    logger.info()
    logger.info("ℹ️  СТАТУС:")
    logger.info(f"  ✓ Залежності: OK")
    logger.info(f"  {'✓' if time_synced else '⚠'} Час: {time_message}")
    logger.info(f"  ✓ Конфігурація: OK")
    logger.info(f"  ✓ БД: OK")
    logger.info(f"  ✓ Декодер: Running")
    logger.info(f"  ✓ TCP підключення: Connected")
    logger.info()
    logger.info("📝 НАСТУПНІ КОМПОНЕНТИ:")
    logger.info("  • parser.py — читає TCP дані від декодера")
    logger.info("  • analyser.py — обробляє та біндить дані (K1↔K2)")
    logger.info("  • sender.py — відправляє на API сервер")
    logger.info()
    logger.info("🔄 ФОНОВІ ПРОЦЕСИ:")
    logger.info(f"  • Ping loop (інтервал: {config['api'].get('ping_interval', 30)}с)")
    logger.info()
    logger.info("Для завершення натисніть: Ctrl+C")
    logger.info("═" * 60 + "\n")
    
    # ========================================
    # ЕТАП 6: Запуск ping loop (фоні)
    # ========================================
    
    app_state.ping_status = PingStatus(config)
    app_state.ping_status.tcp_connected = True
    app_state.ping_status.stages['dependencies'] = True
    app_state.ping_status.stages['config'] = True
    app_state.ping_status.stages['database'] = True
    app_state.ping_status.stages['time_sync'] = time_synced
    app_state.ping_status.stages['decoder'] = True
    app_state.ping_status.stages['tcp_connection'] = True
    
    # Запускаємо ping loop в фоні
    ping_task = asyncio.create_task(ping_loop(app_state.ping_status, db_file))
    
    try:
        await ping_task
    except KeyboardInterrupt:
        pass


# ============================================================
# ТОЧКА ВХОДУ
# ============================================================

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n[!] Програма завершена користувачем")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n❌ КРИТИЧНА ПОМИЛКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
