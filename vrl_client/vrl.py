#!/usr/bin/env python3
"""
vrl.py - Головний файл для запуску VRL Client
Керує: запуском декодера, парсингом, аналізом, відправкою даних

ПОСЛІДОВНІСТЬ ЕТАПІВ:
0. ЕТАП 0: Перевірка залежностей (PyYAML, requests, та ін.)
1. ЕТАП 1: Синхронізація часу з NTP сервером
2. ЕТАП 2: Завантаження конфігурації
3. ЕТАП 3: Ініціалізація бази даних
4. ЕТАП 4: Запуск декодера
5. ЕТАП 5: Очікування TCP підключення до декодера
6. ЕТАП 6: Запуск основних модулів (parser, analyser, sender)
7. ЕТАП 7: Периодична відправка статусу на API сервер (ping)
"""

import sys
import os
import asyncio
import sqlite3
import logging
import subprocess
import signal
from datetime import datetime, timezone, timedelta
from pathlib import Path
import socket
import time
import platform
import json
import hashlib
import hmac

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
# СТАН ПРОГРАМИ
# ============================================================

class AppState:
    """Глобальний стан програми"""
    def __init__(self):
        self.decoder_process = None
        self.db_file = None
        self.config = None
        self.tcp_connected = False
        self.config_loaded = False
        self.db_loaded = False
        self.time_synced = False
        self.time_message = ""
        self.timezone = None
        self.current_timezone_offset = 0
        
        # Статус для ping
        self.status = {
            'version': '1.0.0',
            'timestamp': None,
            'stages': {
                'dependencies': False,
                'time_sync': False,
                'config': False,
                'database': False,
                'decoder': False,
                'tcp_connection': False,
                'modules': False,
            },
            'messages': {},
            'uptime': None,
        }
        self.start_time = datetime.now()

app_state = AppState()


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
    ПОВЕРТАЄ: True або завершує програму при помилці
    """
    logger.info("═" * 60)
    logger.info("ЕТАП 0: ПЕРЕВІРКА ЗАЛЕЖНОСТЕЙ")
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
    app_state.status['stages']['dependencies'] = True
    app_state.status['messages']['dependencies'] = 'OK'
    
    return True


# ============================================================
# ЕТАП 1: СИНХРОНІЗАЦІЯ ЧАСУ
# ============================================================

def get_timezone_offset(timezone_str):
    """Отримуємо offset часового поясу від UTC"""
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
    ПОВЕРТАЄ: (unix_timestamp, is_success)
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
    ПОВЕРТАЄ: (success, message)
    """
    logger.info("═" * 60)
    logger.info("ЕТАП 1: СИНХРОНІЗАЦІЯ ЧАСУ")
    logger.info("═" * 60)
    
    # Отримуємо часовий пояс
    timezone_str = config['app'].get('timezone', 'UTC')
    app_state.timezone = timezone_str
    app_state.current_timezone_offset = get_timezone_offset(timezone_str)
    
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
                        app_state.status['stages']['time_sync'] = True
                        app_state.status['messages']['time_sync'] = 'Synced via w32tm'
                        app_state.time_synced = True
                        app_state.time_message = "Час синхронізований через w32tm"
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
                    app_state.status['stages']['time_sync'] = True
                    app_state.status['messages']['time_sync'] = 'Synced via sntp'
                    app_state.time_synced = True
                    app_state.time_message = "Час синхронізований через sntp"
                    return True, "Час синхронізований через sntp"
                except Exception as e:
                    logger.warning(f"  ⚠ Помилка sntp: {e}")
            
            elif platform.system() == 'Linux':
                logger.info(f"  → Спроба синхронізації на Linux...")
                try:
                    subprocess.run(['timedatectl', 'set-ntp', 'true'], timeout=10, check=True)
                    logger.info(f"  ✓ Час синхронізований успішно через timedatectl")
                    logger.info()
                    app_state.status['stages']['time_sync'] = True
                    app_state.status['messages']['time_sync'] = 'Synced via timedatectl'
                    app_state.time_synced = True
                    app_state.time_message = "Час синхронізований через timedatectl"
                    return True, "Час синхронізований через timedatectl"
                except Exception as e:
                    logger.warning(f"  ⚠ Помилка timedatectl: {e}")
            
            # Якщо автоматична синхронізація не вдалася
            logger.warning(f"  ⚠ Автоматична синхронізація не вдалася")
            logger.warning(f"     Будемо враховувати часовий пояс при записі в БД")
            logger.info()
            app_state.status['stages']['time_sync'] = True
            app_state.status['messages']['time_sync'] = f'Offset: {diff:.1f}s'
            app_state.time_synced = False
            app_state.time_message = f"Часова різниця {diff:.1f}с — враховуємо пояс"
            return False, f"Часова різниця {diff:.1f}с — враховуємо пояс"
        else:
            logger.info(f"  ✓ Час синхронізований (різниця < 5с)")
            logger.info()
            app_state.status['stages']['time_sync'] = True
            app_state.status['messages']['time_sync'] = 'OK'
            app_state.time_synced = True
            app_state.time_message = "Час актуальний"
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
            app_state.status['stages']['time_sync'] = True
            app_state.status['messages']['time_sync'] = f'Offset: {diff:.1f}s'
            app_state.time_synced = False
            app_state.time_message = f"Часова різниця {diff:.1f}с — враховуємо пояс"
            return False, f"Часова різниця {diff:.1f}с — враховуємо пояс"
        else:
            logger.info(f"  ✓ Час синхронізований (різниця < 5с)")
            logger.info()
            app_state.status['stages']['time_sync'] = True
            app_state.status['messages']['time_sync'] = 'OK'
            app_state.time_synced = True
            app_state.time_message = "Час актуальний"
            return True, "Час актуальний"
    
    except Exception as e:
        logger.warning(f"  ⚠ HTTP запит не вдався: {e}")
        logger.warning(f"     Будемо використовувати локальний час")
        logger.warning(f"     ВАЖЛИВО: Переконайтесь, що локальний час встановлений правильно!")
        logger.info()
        app_state.status['stages']['time_sync'] = True
        app_state.status['messages']['time_sync'] = 'Using local time'
        app_state.time_synced = False
        app_state.time_message = "Використовуємо локальний час"
        return False, "Використовуємо локальний час"


# ============================================================
# ЕТАП 2: КОНФІГУРАЦІЯ
# ============================================================

DEFAULT_CONFIG = {
    'app': {
        'name': 'VRL Client',
        'version': '1.0.0',
        'timezone': 'Europe/Kiev',
    },
    'decoder': {
        'executable': '/path/to/uvd_rtl.exe',
        'command_args': '/tcp',
        'host': '127.0.0.1',
        'port': 31003,
        'timeout': 10,
        'reconnect_delay': 5,
    },
    'api': {
        'url': 'https://skybind.pp.ua/vrl_api/ingest.php',
        'status_url': 'https://skybind.pp.ua/vrl_api/status.php',
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
    },
}

def load_config():
    """
    Завантажуємо конфігурацію з файлу або створюємо нову
    ПОВЕРТАЄ: config (dict)
    """
    logger.info("═" * 60)
    logger.info("ЕТАП 2: ЗАВАНТАЖЕННЯ КОНФІГУРАЦІЇ")
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
            logger.info(f"  ⚠ УВАГА: Відредагуйте config.yaml перед повторним запуском!")
            logger.info(f"     Особливо потрібно встановити:")
            logger.info(f"       • decoder.executable")
            logger.info(f"       • api.client_id, api.secret_key, api.bearer_token\n")
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
        
        app_state.status['stages']['config'] = True
        app_state.status['messages']['config'] = 'OK'
        
        return config
    
    except yaml.YAMLError as e:
        logger.error(f"  ❌ ПОМИЛКА синтаксису YAML: {e}")
        logger.error(f"     Перевірте формат файлу config.yaml\n")
        sys.exit(1)
    except Exception as e:
        logger.error(f"  ❌ ПОМИЛКА при завантаженні config.yaml: {e}\n")
        sys.exit(1)


# ============================================================
# ЕТАП 3: БАЗА ДАНИХ
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

def init_database(config):
    """
    Ініціалізуємо БД з файлу base.db
    ПОВЕРТАЄ: db_file (path)
    """
    logger.info("═" * 60)
    logger.info("ЕТАП 3: ІНІЦІАЛІЗАЦІЯ БАЗИ ДАНИХ")
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
            
            app_state.status['stages']['database'] = True
            app_state.status['messages']['database'] = 'Created'
            
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
        
        app_state.status['stages']['database'] = True
        app_state.status['messages']['database'] = 'OK'
        
        return str(db_file)
    
    except sqlite3.DatabaseError as e:
        logger.error(f"  ❌ ПОМИЛКА БД: {e}")
        logger.error(f"     Файл БД може бути пошкоджений\n")
        sys.exit(1)
    except Exception as e:
        logger.error(f"  ❌ ПОМИЛКА при перевірці БД: {e}\n")
        sys.exit(1)


def log_to_db(db_file, level, component, message, details=None):
    """Записуємо лог в БД"""
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


# ============================================================
# ЕТАП 4: ЗАПУСК ДЕКОДЕРА
# ============================================================

def start_decoder(config, db_file):
    """
    Запускаємо програму декодера як підпроцес
    ПОВЕРТАЄ: process (Popen)
    """
    logger.info("═" * 60)
    logger.info("ЕТАП 4: ЗАПУСК ДЕКОДЕРА")
    logger.info("═" * 60)
    
    executable = config['decoder']['executable']
    args = config['decoder']['command_args']
    
    # Перевіряємо наявність виконуваного файлу
    if not os.path.exists(executable):
        logger.error(f"  ❌ ПОМИЛКА: Декодер не знайдений")
        logger.error(f"     Очікуваний шлях: {executable}")
        logger.error(f"     Виправте параметр decoder.executable у config.yaml\n")
        log_to_db(db_file, 'ERROR', 'DECODER', 'Декодер не знайдений', f"Path: {executable}")
        app_state.status['stages']['decoder'] = False
        app_state.status['messages']['decoder'] = f'Not found: {executable}'
        sys.exit(1)
    
    try:
        logger.info(f"  → Запускаємо: {executable} {args}")
        
        process = subprocess.Popen(
            [executable, args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
        )
        
        logger.info(f"  ✓ Декодер запущений")
        logger.info(f"     PID: {process.pid}\n")
        
        log_to_db(db_file, 'INFO', 'DECODER', 'Декодер запущений', f"PID: {process.pid}")
        app_state.status['stages']['decoder'] = True
        app_state.status['messages']['decoder'] = f'Running (PID: {process.pid})'
        
        return process
    
    except Exception as e:
        logger.error(f"  ❌ ПОМИЛКА при запуску декодера: {e}\n")
        log_to_db(db_file, 'ERROR', 'DECODER', 'Помилка запуску', str(e))
        app_state.status['stages']['decoder'] = False
        app_state.status['messages']['decoder'] = str(e)
        sys.exit(1)


# ============================================================
# ЕТАП 5: ПЕРЕВІРКА TCP-КОНЕКТУ
# ============================================================

async def wait_for_decoder_connection(config, db_file):
    """
    Чекаємо доступу TCP-порту декодера
    ПОВЕРТАЄ: True або завершує програму
    """
    logger.info("═" * 60)
    logger.info("ЕТАП 5: ОЧІКУВАННЯ ПІДКЛЮЧЕННЯ ДО ДЕКОДЕРА")
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
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            
            if result == 0:
                logger.info(f"  ✓ TCP підключення встановлено ({host}:{port})")
                logger.info(f"     Декодер готовий до роботи\n")
                
                log_to_db(db_file, 'INFO', 'DECODER', 'TCP підключення встановлено', f"{host}:{port}")
                
                app_state.tcp_connected = True
                app_state.status['stages']['tcp_connection'] = True
                app_state.status['messages']['tcp_connection'] = f'Connected to {host}:{port}'
                return True
            
            else:
                logger.warning(f"  ⚠ Декодер недоступний, чекаємо {reconnect_delay}с...")
                await asyncio.sleep(reconnect_delay)
        
        except Exception as e:
            logger.warning(f"  ⚠ Помилка перевірки: {e}, чекаємо {reconnect_delay}с...")
            await asyncio.sleep(reconnect_delay)
    
    # Перевищили максимум спроб
    logger.error(f"  ❌ ПОМИЛКА: Не вдалося підключитися до декодера після {max_attempts} спроб")
    logger.error(f"     Перевірте:")
    logger.error(f"       1. Чи декодер запущений?")
    logger.error(f"       2. Чи він слухає на {host}:{port}?")
    logger.error(f"       3. Правильні параметри у config.yaml?\n")
    
    log_to_db(db_file, 'ERROR', 'DECODER', 'TCP підключення не встановлено', f"Max attempts exceeded")
    app_state.status['stages']['tcp_connection'] = False
    app_state.status['messages']['tcp_connection'] = 'Connection failed'
    
    return False


# ============================================================
# ЕТАП 6: ЗАПУСК ОСНОВНИХ МОДУЛІВ
# ============================================================

async def check_modules_exist():
    """Перевіряємо наявність основних модулів"""
    logger.info("═" * 60)
    logger.info("ЕТАП 6: ПЕРЕВІРКА ОСНОВНИХ МОДУЛІВ")
    logger.info("═" * 60)
    
    required_files = ['parser.py', 'analyser.py', 'sender.py']
    base_dir = Path(__file__).parent
    
    all_exist = True
    for file in required_files:
        file_path = base_dir / file
        if file_path.exists():
            logger.info(f"  ✓ {file}")
        else:
            logger.warning(f"  ⚠ {file} - не знайдений (буде запущений пізніше)")
            all_exist = False
    
    logger.info()
    app_state.status['stages']['modules'] = all_exist
    app_state.status['messages']['modules'] = 'OK' if all_exist else 'Partial'
    
    return all_exist


# ============================================================
# ЕТАП 7: ПЕРИОДИЧНИЙ PING НА API
# ============================================================

def generate_status_ping(config):
    """
    Генеруємо статус для відправки на API сервер
    ПОВЕРТАЄ: dict зі статусом
    """
    uptime = (datetime.now() - app_state.start_time).total_seconds()
    
    ping_data = {
        'client_id': config['api']['client_id'],
        'version': app_state.status['version'],
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'uptime_seconds': uptime,
        'stages': app_state.status['stages'],
        'messages': app_state.status['messages'],
        'decoder': {
            'tcp_host': config['decoder']['host'],
            'tcp_port': config['decoder']['port'],
            'connected': app_state.tcp_connected,
        },
        'database': {
            'file': Path(app_state.db_file).name if app_state.db_file else None,
        },
        'system': {
            'platform': platform.system(),
            'python_version': platform.python_version(),
        },
    }
    
    return ping_data


def send_status_ping(config, db_file):
    """
    Відправляємо статус на API сервер (ping)
    """
    try:
        import requests
        
        ping_data = generate_status_ping(config)
        
        # Генеруємо HMAC сигнатуру
        payload_str = json.dumps(ping_data, sort_keys=True)
        signature = hmac.new(
            config['api']['secret_key'].encode(),
            payload_str.encode(),
            hashlib.sha256
        ).hexdigest()
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {config['api']['bearer_token']}",
            'X-Signature': signature,
        }
        
        response = requests.post(
            config['api'].get('status_url', config['api']['url']),
            json=ping_data,
            headers=headers,
            timeout=config['api']['timeout']
        )
        
        if response.status_code in [200, 201]:
            logger.debug(f"✓ Статус надіслано на API: {response.status_code}")
            log_to_db(db_file, 'INFO', 'PING', 'Статус надіслано', f"Status: {response.status_code}")
            return True
        else:
            logger.warning(f"⚠ API відповіді: {response.status_code}")
            log_to_db(db_file, 'WARNING', 'PING', 'Неочікувана відповідь API', f"Status: {response.status_code}")
            return False
    
    except Exception as e:
        logger.debug(f"⚠ Помилка при відправці ping: {e}")
        return False


async def ping_loop(config, db_file):
    """
    Периодично відправляємо статус на API сервер
    ПОВЕРТАЄ: нікоди (infinite loop)
    """
    ping_interval = config['api'].get('ping_interval', 30)
    
    logger.info(f"🔄 Ping loop запущений (інтервал: {ping_interval}с)")
    
    while True:
        try:
            await asyncio.sleep(ping_interval)
            send_status_ping(config, db_file)
        except Exception as e:
            logger.debug(f"⚠ Помилка в ping loop: {e}")


# ============================================================
# ОБРОБНИК СИГНАЛІВ
# ============================================================

def signal_handler(sig, frame):
    """Обробник SIGINT для коректного завершення"""
    logger.info("\n" + "═" * 60)
    logger.info("ЗАВЕРШЕННЯ ПРОГРАМИ")
    logger.info("═" * 60)
    logger.info("[!] Сигнал переривання отримано...")
    
    if app_state.decoder_process:
        try:
            logger.info("  → Зупиняємо декодер...")
            if sys.platform == 'win32':
                os.kill(app_state.decoder_process.pid, signal.SIGTERM)
            else:
                app_state.decoder_process.terminate()
            logger.info("  ✓ Декодер зупинений")
        except Exception as e:
            logger.error(f"  ⚠ Помилка при зупинку декодера: {e}")
    
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
    Основна функція з послідовною ініціалізацією
    
    ПОСЛІДОВНІСТЬ ЕТАПІВ:
    0. Перевірка залежностей
    1. Синхронізація часу
    2. Завантаження конфігурації
    3. Ініціалізація БД
    4. Запуск декодера
    5. Очікування TCP підключення
    6. Перевірка основних модулів
    7. Запуск ping loop
    """
    
    signal.signal(signal.SIGINT, signal_handler)
    
    logger.info("\n")
    
    # ЕТАП 0: Перевірка залежностей
    if not check_dependencies():
        sys.exit(1)
    
    # ЕТАП 2: Завантаження конфігурації (потрібна для ЕТАПУ 1)
    config = load_config()
    app_state.config = config
    app_state.config_loaded = True
    
    # ЕТАП 1: Синхронізація часу (враховує часовий пояс з конфіги)
    time_synced, time_message = sync_system_time(config)
    
    # ЕТАП 3: Ініціалізація БД
    db_file = init_database(config)
    app_state.db_file = db_file
    app_state.db_loaded = True
    
    log_to_db(db_file, 'INFO', 'MAIN', 'Програма запущена', f"Version: {config['app']['version']}")
    
    # ЕТАП 4: Запуск декодера
    decoder_process = start_decoder(config, db_file)
    app_state.decoder_process = decoder_process
    
    # ЕТАП 5: Очікування TCP підключення
    connected = await wait_for_decoder_connection(config, db_file)
    
    if not connected:
        logger.error("❌ Не вдалося підключитися до декодера")
        log_to_db(db_file, 'ERROR', 'MAIN', 'Не вдалося підключитися до декодера', None)
        
        if decoder_process:
            try:
                if sys.platform == 'win32':
                    os.kill(decoder_process.pid, signal.SIGTERM)
                else:
                    decoder_process.terminate()
            except:
                pass
        
        sys.exit(1)
    
    # ЕТАП 6: Перевірка модулів
    await check_modules_exist()
    
    # ============================================================
    # ГОТОВО: Всі перевірки пройдені
    # ============================================================
    
    logger.info("═" * 60)
    logger.info("✅ ІНІЦІАЛІЗАЦІЯ ЗАВЕРШЕНА УСПІШНО")
    logger.info("═" * 60)
    logger.info(f"  • Конфігурація: {config['app']['name']} v{config['app']['version']}")
    logger.info(f"  • БД: {db_file}")
    logger.info(f"  • Декодер: {config['decoder']['host']}:{config['decoder']['port']} (TCP)")
    logger.info(f"  • API: {config['api']['url']}")
    logger.info()
    logger.info("ℹ️  СТАТУС ЕТАПІВ:")
    logger.info(f"  ✓ Залежності:      {app_state.status['messages'].get('dependencies', '?')}")
    logger.info(f"  {'✓' if app_state.status['stages']['time_sync'] else '⚠'} Синхронізація часу: {app_state.time_message}")
    logger.info(f"  ✓ Конфігурація:    {app_state.status['messages'].get('config', '?')}")
    logger.info(f"  ✓ БД:              {app_state.status['messages'].get('database', '?')}")
    logger.info(f"  ✓ Декодер:         {app_state.status['messages'].get('decoder', '?')}")
    logger.info(f"  ✓ TCP підключення: {app_state.status['messages'].get('tcp_connection', '?')}")
    logger.info(f"  {'✓' if app_state.status['stages']['modules'] else '⚠'} Модулі: {app_state.status['messages'].get('modules', '?')}")
    logger.info()
    logger.info("📝 ГОТОВІ ДО ЗАПУСКУ:")
    logger.info("  • parser.py — TCP парсер (залежить від TCP підключення)")
    logger.info("  • analyser.py — обробник даних (залежить від config + db)")
    logger.info("  • sender.py — відправник на API (залежить від config + db)")
    logger.info()
    logger.info("🔄 ФОНОВАНІ ПРОЦЕСИ:")
    logger.info(f"  • Ping loop (інтервал: {config['api'].get('ping_interval', 30)}с)")
    logger.info()
    logger.info("Для завершення натисніть: Ctrl+C")
    logger.info("═" * 60 + "\n")
    
    # ============================================================
    # ЕТАП 7: Запуск ping loop
    # ============================================================
    
    # Запускаємо ping loop в фоні
    ping_task = asyncio.create_task(ping_loop(config, db_file))
    
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
