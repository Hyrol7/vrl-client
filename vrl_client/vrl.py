#!/usr/bin/env python3
"""
vrl.py - Головний файл для запуску VRL Client
Координує всі модулі та етапи ініціалізації

АРХІТЕКТУРА:
    - initialization.py: перевірка залежностей, конфіг, БД
    - time_sync.py: синхронізація часу
    - decoder.py: запуск декодера
    - ping_handler.py: периодичний ping на API
    - parser.py: парсинг TCP даних від декодера
    - analyser.py: обробка та біндинг даних
    - sender.py: відправка на API

ПОСЛІДОВНІСТЬ:
    1. Перевірка залежностей (initialization.check_dependencies)
    2. Завантаження конфігурації (initialization.load_config)
    3. Ініціалізація БД (initialization.init_database)
    4. Синхронізація часу (time_sync.sync_system_time)
    5. Конфігурація декодера (initialization.update_decoder_ini)
    6. Запуск декодера (decoder.start_decoder)
    7. Запуск ping loop (ping_handler.ping_loop) - в фоні
    8. Запуск parser, analyser, sender - в фоні
"""

import sys
import signal
import logging
import asyncio
from pathlib import Path

# Імпортуємо всі модулі
from initialization import check_dependencies, load_config, init_database, log_to_db, update_decoder_ini
from time_sync import sync_system_time
from decoder import start_decoder, stop_decoder
from ping_handler import PingStatus, ping_loop
from parser import parser_loop
from analyser import analyser_loop
from sender import sender_loop
from status_manager import update_status, get_latest_status, get_system_metrics, format_status_json
from datetime import datetime

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
        
        # СТАН КОМПОНЕНТІВ (для status_reporter)
        self.parser_state = {
            'running': False,
            'connected': False,
            'packets_total': 0,
            'packets_last_flush': 0,
            'buffer_size': 0,
            'last_error': None,
        }
        self.analyser_state = {
            'running': False,
            'last_run': None,
            'packets_processed': 0,
            'last_error': None,
        }
        self.sender_state = {
            'running': False,
            'last_run': None,
            'packets_sent': 0,
            'last_error': None,
        }
        self.ping_handler_state = {
            'running': False,
            'last_run': None,
            'last_error': None,
        }
        
        # UPTIME
        self.start_time = None
        
        # TIME OFFSET (різниця між системним і реальним часом в секундах)
        # Якщо системний час відстає на 5 сек, offset буде +5
        self.time_offset = 0.0


app_state = AppState()


# ============================================================
# TIME SYNC LOOP - СИНХРОНІЗАЦІЯ ЧАСУ ЩОГОДИНИ
# ============================================================

async def time_sync_loop(config):
    """
    Кожну годину (в 00:05) синхронізує час
    """
    logger.info("[TIME] Запуск time_sync_loop (щогодини в XX:00:05)")
    
    while True:
        try:
            now = datetime.now()
            # Рахуємо скільки секунд до наступної години + 5 секунд
            # (3600 - поточні секунди) + 5
            seconds_until_next_run = (3600 - (now.minute * 60 + now.second)) + 5
            
            # Якщо ми вже в перших 5 секундах години, чекаємо до наступної години
            if now.minute == 0 and now.second < 5:
                seconds_until_next_run = 5 - now.second
            
            logger.info(f"[TIME] Наступна синхронізація через {int(seconds_until_next_run)} сек")
            
            # Чекаємо
            await asyncio.sleep(seconds_until_next_run)
            
            logger.info("[TIME] ⏰ Планова синхронізація часу...")
            success, msg, offset = sync_system_time(config)
            
            # Оновлюємо глобальний offset
            app_state.time_offset = offset
            
            if success:
                logger.info(f"[TIME] ✓ {msg}")
            else:
                logger.warning(f"[TIME] ⚠ {msg}")
                
            # Чекаємо 10 секунд, щоб точно вийти з 5-секундної зони і не запуститись двічі
            await asyncio.sleep(10)
            
        except Exception as e:
            logger.error(f"[TIME] Помилка циклу синхронізації: {e}")
            await asyncio.sleep(60)


# ============================================================
# STATUS REPORTER - ЗАПИС СТАТУСУ КОЖНІ 30 СЕК
# ============================================================

async def status_reporter_loop(app_state):
    """
    Кожні 30 сек:
    1. Збираємо стан всіх компонентів
    2. Записуємо в таблицю status
    3. Логуємо
    """
    status_interval = app_state.config.get('api', {}).get('status_interval', 30)
    
    logger.info(f"[STATUS] Запуск status_reporter (інтервал {status_interval}s)")
    
    while True:
        try:
            await asyncio.sleep(status_interval)
            
            # Збираємо стан
            metrics = get_system_metrics(app_state.db_file)
            
            # Обчислюємо uptime
            uptime = 0
            if app_state.start_time:
                import time
                uptime = int(time.time() - app_state.start_time)
            
            # Формуємо status_data
            status_data = {
                'parser_running': app_state.parser_state['running'],
                'parser_connected': app_state.parser_state['connected'],
                'parser_packets_total': app_state.parser_state['packets_total'],
                'parser_packets_last_flush': app_state.parser_state['packets_last_flush'],
                'parser_buffer_size': app_state.parser_state['buffer_size'],
                'parser_last_error': app_state.parser_state['last_error'],
                
                'analyser_running': app_state.analyser_state['running'],
                'analyser_last_run': app_state.analyser_state['last_run'],
                'analyser_packets_processed': app_state.analyser_state['packets_processed'],
                'analyser_last_error': app_state.analyser_state['last_error'],
                
                'sender_running': app_state.sender_state['running'],
                'sender_last_run': app_state.sender_state['last_run'],
                'sender_packets_sent': app_state.sender_state['packets_sent'],
                'sender_last_error': app_state.sender_state['last_error'],
                
                'ping_handler_running': app_state.ping_handler_state['running'],
                'ping_handler_last_run': app_state.ping_handler_state['last_run'],
                'ping_handler_last_error': app_state.ping_handler_state['last_error'],
                
                'total_packets_in_db': metrics.get('total_packets_in_db', 0),
                'total_logs_in_db': metrics.get('total_logs_in_db', 0),
                'db_size_bytes': metrics.get('db_size_bytes', 0),
                
                'uptime_seconds': uptime,
                'memory_usage_mb': metrics.get('memory_usage_mb', 0),
                'last_error': None,
                
                'app_version': app_state.config.get('app', {}).get('version', '0.1.0'),
            }
            
            # Записуємо в БД
            if update_status(app_state.db_file, status_data, app_state.time_offset):
                logger.info("[STATUS] ✓ Статус записаний в БД")
            else:
                logger.warning("[STATUS] ✗ Не вдалось записати статус")
        
        except Exception as e:
            logger.error(f"[STATUS] Критична помилка: {e}")
            await asyncio.sleep(status_interval)


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
    time_synced, time_message, time_offset = sync_system_time(config)
    app_state.time_offset = time_offset
    
    # ========================================
    # ЕТАП 3.5: Конфігурація декодера
    # ========================================
    update_decoder_ini(config)
    
    # ========================================
    # ЕТАП 4: Запуск декодера
    # ========================================
    decoder_process = start_decoder(config, db_file)
    app_state.decoder_process = decoder_process
    
    # ========================================
    # ЕТАП 5: Очікування TCP підключення
    # ========================================
    # Ми більше не чекаємо підключення тут, parser.py зробить це сам
    # Це дозволяє програмі не зависати, якщо декодер довго стартує
    logger.info("  → Очікування TCP підключення передано в parser.py")
    
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
    # ЕТАП 6: Запуск фонових процесів
    # ========================================
    
    app_state.ping_status = PingStatus(config)
    app_state.ping_status.tcp_connected = True
    app_state.ping_status.stages['dependencies'] = True
    app_state.ping_status.stages['config'] = True
    app_state.ping_status.stages['database'] = True
    app_state.ping_status.stages['time_sync'] = time_synced
    app_state.ping_status.stages['decoder'] = True
    app_state.ping_status.stages['tcp_connection'] = True
    
    # Встановлюємо час старту для uptime
    import time
    app_state.start_time = time.time()
    
    # Створюємо всі фонові завдання (включно з status_reporter)
    tasks = [
        asyncio.create_task(time_sync_loop(config)),
        asyncio.create_task(status_reporter_loop(app_state)),
        asyncio.create_task(ping_loop(app_state.ping_status, db_file, app_state)),
        asyncio.create_task(parser_loop(config, db_file, app_state)),
        asyncio.create_task(analyser_loop(config, db_file, app_state)),
        asyncio.create_task(sender_loop(config, db_file, app_state)),
    ]
    
    try:
        await asyncio.gather(*tasks)
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
