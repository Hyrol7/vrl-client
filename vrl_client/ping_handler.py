#!/usr/bin/env python3
"""
ping_handler.py - Периодичний ping на API сервер для передачі статусу

Функції:
    - generate_status_ping() - генеруємо JSON статусу
    - send_status_ping() - відправляємо статус на API
    - ping_loop() - нескінченний цикл періодичних пінгів
"""

import asyncio
import json
import logging
import platform
import hashlib
import hmac
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================
# СТАТУС ПРОГРАМИ
# ============================================================

class PingStatus:
    """Клас для управління статусом для ping'ів"""
    
    def __init__(self, config):
        self.config = config
        self.start_time = datetime.now()
        self.stages = {
            'dependencies': False,
            'time_sync': False,
            'config': False,
            'database': False,
            'decoder': False,
            'tcp_connection': False,
            'parser': False,
            'analyser': False,
            'sender': False,
        }
        self.messages = {}
        self.tcp_connected = False
    
    def to_dict(self):
        """Конвертуємо статус в словник"""
        uptime = (datetime.now() - self.start_time).total_seconds()
        
        return {
            'client_id': self.config['api']['client_id'],
            'version': self.config['app']['version'],
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'uptime_seconds': uptime,
            'stages': self.stages,
            'messages': self.messages,
            'decoder': {
                'tcp_host': self.config['decoder']['host'],
                'tcp_port': self.config['decoder']['port'],
                'connected': self.tcp_connected,
            },
            'database': {
                'file': Path(self.config['database']['file']).name,
            },
            'system': {
                'platform': platform.system(),
                'python_version': platform.python_version(),
            },
        }


# ============================================================
# ГЕНЕРАЦІЯ ТА ВІДПРАВКА PING
# ============================================================

def generate_status_ping(ping_status):
    """
    Генеруємо JSON статусу для відправки на API
    
    ПАРАМЕТРИ:
        - ping_status: об'єкт PingStatus
    
    ПОВЕРТАЄ:
        - ping_data (dict): JSON статус
    """
    return ping_status.to_dict()


def send_status_ping(ping_status, db_file):
    """
    Відправляємо статус на API сервер (ping)
    
    ПАРАМЕТРИ:
        - ping_status: об'єкт PingStatus
        - db_file: шлях до БД (для логування)
    
    ПОВЕРТАЄ:
        - True/False: успіх відправки
    """
    try:
        import requests
        
        config = ping_status.config
        ping_data = generate_status_ping(ping_status)
        
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
            
            from initialization import log_to_db
            log_to_db(db_file, 'INFO', 'PING', 'Статус надіслано', f"Status: {response.status_code}")
            return True
        else:
            logger.warning(f"⚠ API відповіді: {response.status_code}")
            
            from initialization import log_to_db
            log_to_db(db_file, 'WARNING', 'PING', 'Неочікувана відповідь API', f"Status: {response.status_code}")
            return False
    
    except Exception as e:
        logger.debug(f"⚠ Помилка при відправці ping: {e}")
        return False


async def ping_loop(ping_status, db_file):
    """
    Периодично відправляємо статус на API сервер (нескінченний цикл)
    
    ПАРАМЕТРИ:
        - ping_status: об'єкт PingStatus
        - db_file: шлях до БД (для логування)
    
    ПОВЕРТАЄ:
        - Нікогда (нескінченний цикл, поки програма працює)
    """
    ping_interval = ping_status.config['api'].get('ping_interval', 30)
    
    logger.info(f"🔄 Ping loop запущений (інтервал: {ping_interval}с)")
    
    while True:
        try:
            await asyncio.sleep(ping_interval)
            send_status_ping(ping_status, db_file)
        except Exception as e:
            logger.debug(f"⚠ Помилка в ping loop: {e}")
