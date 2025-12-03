#!/usr/bin/env python3
"""
initialization.py - Ініціалізація: перевірка залежностей, конфігурація та БД

Функції:
    - check_dependencies() - перевіряємо PyYAML, requests, ntplib
    - load_config() - завантажуємо конфіг з YAML або створюємо новий
    - init_database() - ініціалізуємо SQLite БД зі схемою
    - log_to_db() - записуємо лог в БД
"""

import sys
import os
import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================
# КОНФІГУРАЦІЯ ПО ЗАМОВЧУВАННЮ
# ============================================================

DEFAULT_CONFIG = {
    'app': {
        'name': 'VRL Client',
        'version': '0.2.0',
        'timezone': 'Europe/Kiev',
    },
    'decoder': {
        'path': 'C:\\Users\\User\\Downloads\\rtluvd\\', # шлях до директорії з програмою (Windows)
        # 'path': '/Users/user/Downloads/rtluvd/',      # приклад для macOS/Linux
        'app_decoder': 'uvd_rtl.exe',   # назва файлу програми
        'command_args': '/tcp',         # аргументи запуску програми
        'host': '127.0.0.1',            # хост
        'port': 31003,                  # порт TCP
        'connect_timeout': 2,           # сек - таймаут для підключення
        'reconnect_delay': 3,           # сек - затримка перед повторним перепідключенням
        'buffer_overflow_limit': 10000,  # байт - максимальний розмір text_buffer
    },
    'api': {
        'url': 'https://yourdomain/api.php',
        'status_url': 'https://yourdomain/status.php',
        'client_id': 1,
        'secret_key': 'your-secret-key-here',
        'bearer_token': 'your-bearer-token-here',
        'timeout': 30,
        'status_interval': 30,    # сек - запис статусу в БД та відправка на сервер
    },
    'database': {
        'file': 'base.db',
    },
    'cycles': {
        'parser_buffer_interval': 2,   # сек - накопичення пакетів перед записом в БД
        'analyser_interval': 5,        # сек - обробка K1↔K2 пакетів
        'sender_interval': 10,         # сек - відправка на API
        'batch_size': 1000,            # максимум записів за раз
    },
}

# ============================================================
# БАЗА ДАНИХ - СХЕМА
# ============================================================

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS packets_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time TEXT NOT NULL,
    type INTEGER NOT NULL,
    callsign TEXT,
    height INTEGER,
    fuel INTEGER,
    alarm INTEGER DEFAULT 0,
    faithfulness INTEGER,
    sent INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT,
    component TEXT,
    message TEXT,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- ОСНОВНА ІНФОРМАЦІЯ
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- PARSER
    parser_running INTEGER DEFAULT 0,
    parser_connected INTEGER DEFAULT 0,
    parser_packets_total INTEGER DEFAULT 0,
    parser_packets_last_flush INTEGER DEFAULT 0,
    parser_buffer_size INTEGER DEFAULT 0,
    parser_last_error TEXT,
    
    -- ANALYSER
    analyser_running INTEGER DEFAULT 0,
    analyser_last_run DATETIME,
    analyser_packets_processed INTEGER DEFAULT 0,
    analyser_last_error TEXT,
    
    -- SENDER
    sender_running INTEGER DEFAULT 0,
    sender_last_run DATETIME,
    sender_packets_sent INTEGER DEFAULT 0,
    sender_last_error TEXT,
    
    -- PING_HANDLER
    ping_handler_running INTEGER DEFAULT 0,
    ping_handler_last_run DATETIME,
    ping_handler_last_error TEXT,
    
    -- ЗАГАЛЬНІ МЕТРИКИ
    total_packets_in_db INTEGER DEFAULT 0,
    total_logs_in_db INTEGER DEFAULT 0,
    db_size_bytes INTEGER DEFAULT 0,
    
    -- СТАН СИСТЕМИ
    uptime_seconds INTEGER DEFAULT 0,
    memory_usage_mb REAL DEFAULT 0,
    last_error TEXT,
    
    -- ВЕРСІЯ
    app_version TEXT
);
"""


# ============================================================
# ЕТАП 0: ПЕРЕВІРКА ЗАЛЕЖНОСТЕЙ
# ============================================================

REQUIRED_LIBS = {
    'yaml': 'PyYAML',
    'requests': 'requests',
    'psutil': 'psutil',
}
OPTIONAL_LIBS = {
    'ntplib': 'ntplib (для точної синхронізації часу)',
}


def check_dependencies():
    """
    Перевіряємо всі необхідні бібліотеки для проєкту
    
    ПОВЕРТАЄ:
        - True: успіх
        - Завершує програму при критичній помилці
    """
    logger.info("═" * 60)
    logger.info("ЕТАП: ПЕРЕВІРКА ЗАЛЕЖНОСТЕЙ")
    logger.info("═" * 60)
    
    logger.info("\n📦 ОБОВ'ЯЗКОВІ ЗАЛЕЖНОСТІ:")
    missing_required = []
    
    for module, package in REQUIRED_LIBS.items():
        try:
            __import__(module)
            logger.info(f"  ✓ {package}")
        except ImportError:
            logger.error(f"  ✗ {package} - ВІДСУТНІЙ")
            missing_required.append(package)
    
    logger.info("\n📦 ОПЦІОНАЛЬНІ ЗАЛЕЖНОСТІ:")
    for module, package in OPTIONAL_LIBS.items():
        try:
            __import__(module)
            logger.info(f"  ✓ {package}")
        except ImportError:
            logger.warning(f"  ⚠ {package} - відсутній (буде використовуватись HTTP альтернатива)")
    
    if missing_required:
        logger.error(f"\n❌ КРИТИЧНА ПОМИЛКА: Встановіть обов'язкові пакети:")
        logger.error(f"   pip install {' '.join(missing_required)}")
        sys.exit(1)
    
    logger.info("\n✓ Всі обов'язкові залежності встановлені\n")
    return True


# ============================================================
# ЕТАП 2: КОНФІГУРАЦІЯ
# ============================================================

def load_config():
    """
    Завантажуємо конфігурацію з файлу або створюємо нову
    
    ПОВЕРТАЄ:
        - config (dict): конфігурація
        - Завершує програму якщо помилка
    """
    logger.info("═" * 60)
    logger.info("ЕТАП: ЗАВАНТАЖЕННЯ КОНФІГУРАЦІЇ")
    logger.info("═" * 60)
    
    import yaml
    
    config_file = Path(__file__).parent / 'config.yaml'
    
    # Якщо файл відсутній — створюємо еталонний
    if not config_file.exists():
        logger.info(f"  ⚠ config.yaml не знайдена")
        logger.info(f"  → Створюємо еталонну конфігурацію...")
        
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                yaml.dump(DEFAULT_CONFIG, f, allow_unicode=True, default_flow_style=False)
            logger.info(f"  ✓ config.yaml створена за адресою: {config_file}")
            logger.info(f"\n  ⚠ УВАГА: Відредагуйте config.yaml перед повторним запуском!")
            sys.exit(0)
        except Exception as e:
            logger.error(f"  ❌ ПОМИЛКА при створенні config.yaml: {e}\n")
            sys.exit(1)
    
    # Файл існує — завантажуємо
    logger.info(f"  ✓ config.yaml знайдена")
    logger.info(f"  → Завантажуємо...")
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        if config is None:
            raise ValueError("Файл порожній")
        
        # Перевіряємо структуру конфігу
        required_keys = ['app', 'decoder', 'api', 'database', 'cycles']
        missing_keys = [key for key in required_keys if key not in config]
        
        if missing_keys:
            raise ValueError(f"Відсутні обов'язкові ключі: {', '.join(missing_keys)}")
        
        logger.info(f"  ✓ config.yaml завантажена успішно")
        logger.info(f"     App: {config['app']['name']} v{config['app']['version']}")
        logger.info(f"     Decoder: {config['decoder']['host']}:{config['decoder']['port']}")
        logger.info(f"     API: {config['api']['url']}\n")
        
        return config
    
    except Exception as e:
        logger.error(f"  ❌ ПОМИЛКА: {e}\n")
        sys.exit(1)


# ============================================================
# ЕТАП 2: БАЗА ДАНИХ
# ============================================================

def init_database(config):
    """
    Ініціалізуємо БД з файлу base.db
    
    ПОВЕРТАЄ:
        - db_file (str): шлях до БД
        - Завершує програму якщо помилка
    """
    logger.info("═" * 60)
    logger.info("ЕТАП: ІНІЦІАЛІЗАЦІЯ БАЗИ ДАНИХ")
    logger.info("═" * 60)
    
    db_file = Path(__file__).parent / config['database']['file']
    file_exists = db_file.exists()
    
    try:
        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        
        # Перевіряємо, які таблиці вже є
        required_tables = ['packets_raw', 'logs', 'status']
        existing_tables = []
        
        for table in required_tables:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            if cursor.fetchone():
                existing_tables.append(table)
        
        missing_tables = [t for t in required_tables if t not in existing_tables]
        
        if not file_exists:
            logger.info(f"  ⚠ {db_file.name} не знайдена")
            logger.info(f"  → Створюємо нову БД...")
            cursor.executescript(DB_SCHEMA)
            conn.commit()
            logger.info(f"  ✓ БД створена успішно")
            
        elif missing_tables:
            logger.info(f"  ⚠ {db_file.name} знайдена, але неповна")
            logger.info(f"  → Відсутні таблиці: {', '.join(missing_tables)}")
            logger.info(f"  → Додаємо відсутні таблиці...")
            cursor.executescript(DB_SCHEMA)
            conn.commit()
            logger.info(f"  ✓ БД оновлена успішно")
            
        else:
            logger.info(f"  ✓ {db_file.name} знайдена")
            logger.info(f"  ✓ Всі таблиці на місці ({', '.join(existing_tables)})")
            
        conn.close()
        return str(db_file)
        
    except Exception as e:
        logger.error(f"  ❌ ПОМИЛКА при ініціалізації БД: {e}\n")
        sys.exit(1)


# ============================================================
# КОНФІГУРАЦІЯ ДЕКОДЕРА
# ============================================================

def update_decoder_ini(config):
    """
    Оновлюємо файл rtluvd.ini перед запуском декодера
    
    Змінюємо:
        - avr=1 (Встановлюємо режим AVR)
        - lastdir=... (Вказуємо шлях до папки декодера)
    
    ПАРАМЕТРИ:
        - config: конфігурація проекту
    
    ПОВЕРТАЄ:
        - True/False: успіх операції
    """
    logger.info("═" * 60)
    logger.info("ЕТАП: КОНФІГУРАЦІЯ ДЕКОДЕРА")
    logger.info("═" * 60)
    
    try:
        decoder_path = config['decoder']['path']
        decoder_dir = Path(decoder_path)
        
        # Шукаємо rtluvd.ini в папці декодера
        ini_file = decoder_dir / 'rtluvd.ini'
        
        if not ini_file.exists():
            logger.warning(f"  ⚠ Файл не знайдений: {ini_file}")
            logger.warning(f"     Ініціалізація декодера буде пропущена")
            logger.info()
            return False
        
        logger.info(f"  → Оновлюємо rtluvd.ini...")
        
        # Читаємо ini файл
        with open(ini_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Оновлюємо параметри
        updated = False
        
        for i, line in enumerate(lines):
            # Оновлюємо 3k1=1
            if line.strip().startswith('3k1='):
                if not line.strip().endswith('1'):
                    lines[i] = '3k1=1\n'
                    logger.info(f"     • 3k1 → 1")
                    updated = True
            # Оновлюємо 3k2=1
            if line.strip().startswith('3k2='):
                if not line.strip().endswith('1'):
                    lines[i] = '3k2=1\n'
                    logger.info(f"     • 3k2 → 1")
                    updated = True
            # Оновлюємо avr=1
            if line.strip().startswith('avr='):
                if not line.strip().endswith('1'):
                    lines[i] = 'avr=1\n'
                    logger.info(f"     • avr → 1")
                    updated = True
            
            # Оновлюємо lastdir
            elif line.strip().startswith('lastdir='):
                # Перетворюємо шлях у Windows формат (якщо потрібно)
                # rtluvd.ini очікує Windows шлях з backslash
                windows_path = decoder_path.replace('/', '\\')
                if not windows_path.endswith('\\'):
                    windows_path += '\\'
                
                new_line = f'lastdir={windows_path}\n'
                if lines[i] != new_line:
                    lines[i] = new_line
                    logger.info(f"     • lastdir → {windows_path}")
                    updated = True
        
        # Записуємо назад в файл (тільки якщо були зміни)
        if updated:
            with open(ini_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            logger.info(f"  ✓ rtluvd.ini оновлена успішно")
        else:
            logger.info(f"  ✓ rtluvd.ini вже актуальна")
        
        logger.info()
        return True
    
    except Exception as e:
        logger.error(f"  ❌ ПОМИЛКА при оновленні rtluvd.ini: {e}\n")
        return False


# ============================================================
# ЛОГУВАННЯ В БД
# ============================================================

def log_to_db(db_file, level, component, message, details=None):
    """
    Записуємо лог в БД
    
    ПАРАМЕТРИ:
        - db_file: шлях до БД
        - level: 'INFO', 'WARNING', 'ERROR'
        - component: назва компонента ('MAIN', 'DECODER', 'PARSER', тощо)
        - message: основне повідомлення
        - details: додаткові деталі
    """
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO logs (level, component, message, details) VALUES (?, ?, ?, ?)",
            (level, component, message, details)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[LOG_DB] Помилка при запису логу: {e}")
