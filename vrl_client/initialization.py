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
        'version': '0.1.0',
        'timezone': 'Europe/Kiev',
    },
    'decoder': {
        'path': 'C:\\Users\\User\\Downloads\\rtluvd\\',
        'app_decoder': 'uvd_rtl.exe',
        'command_args': '/tcp',
        'host': '127.0.0.1',
        'port': 31003,
        'timeout': 10,
        'reconnect_delay': 5,
    },
    'api': {
        'url': 'https://yourdomain/api.php',
        'status_url': 'https://yourdomain/status.php',
        'client_id': 1,
        'secret_key': 'your-secret-key-here',
        'bearer_token': 'your-bearer-token-here',
        'timeout': 30,
        'ping_interval': 30,
    },
    'database': {
        'file': 'base.db',
    },
    'cycles': {
        'parser_interval': 0.1,    # сек
        'analyser_interval': 5,    # сек
        'sender_interval': 10,     # сек
        'connectivity_check': 5,   # сек
        'ntp_sync_interval': 3600, # 1 час
        'batch_size': 1000,        # максимум записів за раз
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
"""


# ============================================================
# ЕТАП 0: ПЕРЕВІРКА ЗАЛЕЖНОСТЕЙ
# ============================================================

REQUIRED_LIBS = {
    'yaml': 'PyYAML',
    'requests': 'requests',
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
    
    # Якщо файл БД відсутній
    if not db_file.exists():
        logger.info(f"  ⚠ {db_file.name} не знайдена")
        logger.info(f"  → Створюємо нову БД...")
        
        try:
            conn = sqlite3.connect(str(db_file))
            cursor = conn.cursor()
            cursor.executescript(DB_SCHEMA)
            conn.commit()
            conn.close()
            
            logger.info(f"  ✓ БД створена: {db_file}")
            logger.info(f"     Таблиці: packets_raw, logs\n")
            
            return str(db_file)
        
        except Exception as e:
            logger.error(f"  ❌ ПОМИЛКА при створенні БД: {e}\n")
            sys.exit(1)
    
    # Файл існує — перевіряємо структуру
    logger.info(f"  ✓ {db_file.name} знайдена")
    logger.info(f"  → Перевіряємо структуру...")
    
    try:
        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='packets_raw'")
        packets_table = cursor.fetchone()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='logs'")
        logs_table = cursor.fetchone()
        
        if not packets_table or not logs_table:
            raise ValueError("Структура БД пошкоджена (відсутні необхідні таблиці)")
        
        conn.close()
        
        logger.info(f"  ✓ Структура БД перевірена")
        logger.info(f"     Таблиці: packets_raw, logs")
        logger.info(f"     Файл: {db_file}\n")
        
        return str(db_file)
    
    except Exception as e:
        logger.error(f"  ❌ ПОМИЛКА: {e}\n")
        sys.exit(1)


# ============================================================
# ЛОГУВАННЯ В БД
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
            logger.warning(f"  ⚠ Файл не знайдена: {ini_file}")
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
