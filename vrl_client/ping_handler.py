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
    
    def to_dict(self, time_offset=0):
        """Конвертуємо статус в словник"""
        uptime = (datetime.now() - self.start_time).total_seconds()
        
        from datetime import timedelta
        current_utc = datetime.utcnow() + timedelta(seconds=time_offset)
        
        return {
            'client_id': self.config['api']['client_id'],
            'version': self.config['app']['version'],
            'timestamp': current_utc.isoformat() + 'Z',
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

def generate_status_ping(ping_status, time_offset=0):
    """
    Генеруємо JSON статусу для відправки на API
    
    ПАРАМЕТРИ:
        - ping_status: об'єкт PingStatus
        - time_offset: зміщення часу в секундах
    
    ПОВЕРТАЄ:
        - ping_data (dict): JSON статус
    """
    return ping_status.to_dict(time_offset)


def send_full_status(status_data, config, db_file):
    """
    Відправляємо повний статус на API сервер
    
    ПАРАМЕТРИ:
        - status_data: dict з повним статусом
        - config: конфігурація
        - db_file: шлях до БД (для логування)
    
    ПОВЕРТАЄ:
        - True/False: успіх відправки
    """
    try:
        import requests
        
        # Генеруємо HMAC сигнатуру
        payload_str = json.dumps(status_data, sort_keys=True)
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
            json=status_data,
            headers=headers,
            timeout=config['api']['timeout']
        )
        
        if response.status_code in [200, 201]:
            logger.debug(f"✓ Статус надіслано на API: {response.status_code}")
            return True
        else:
            logger.warning(f"⚠ API відповіді: {response.status_code}")
            
            from initialization import log_to_db
            log_to_db(db_file, 'WARNING', 'PING', 'Неочікувана відповідь API', f"Status: {response.status_code}")
            return False
    
    except requests.ConnectionError as e:
        logger.warning(f"⚠ PING: Помилка з'єднання (інтернет недоступний): {type(e).__name__}")
        return False
    except requests.Timeout as e:
        logger.warning(f"⚠ PING: Timeout при з'єднанні з API")
        return False
    except Exception as e:
        logger.warning(f"⚠ PING: Непередбачена помилка: {e}")
        return False



