#!/usr/bin/env python3
"""
status_manager.py - Управління статусом системи

Функції:
    - update_status() - записує статус в таблицю status
    - get_latest_status() - читає останній статус
    - format_status_json() - формує JSON для API
"""

import sqlite3
import logging
from datetime import datetime, timedelta
import os
import psutil

logger = logging.getLogger(__name__)


def update_status(db_file, status_data, time_offset=0.0):
    """
    Записуємо статус в таблицю status
    
    ПАРАМЕТРИ:
        - db_file: шлях до БД
        - status_data: dict з даними статусу
        - time_offset: зміщення часу в секундах
    """
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # Додаємо правильний timestamp з урахуванням offset
        now = datetime.now()
        if time_offset != 0:
            now = now + timedelta(seconds=time_offset)
            
        # Копіюємо словник, щоб не змінювати оригінал
        data_to_insert = status_data.copy()
        data_to_insert['timestamp'] = now.strftime('%Y-%m-%d %H:%M:%S')
        
        # Інтерполюємо значення, перетворюючи bool в int (0/1)
        insert_data = []
        for key, value in data_to_insert.items():
            if isinstance(value, bool):
                insert_data.append((key, 1 if value else 0))
            else:
                insert_data.append((key, value))
        
        # Динамічно створюємо SQL запит
        columns = [item[0] for item in insert_data]
        placeholders = ','.join(['?' for _ in insert_data])
        values = [item[1] for item in insert_data]
        
        sql = f"""INSERT INTO status ({','.join(columns)}) VALUES ({placeholders})"""
        
        cursor.execute(sql, values)
        conn.commit()
        conn.close()
        
        return True
    
    except Exception as e:
        logger.error(f"[STATUS_MANAGER] Помилка при записі статусу: {e}")
        return False


def get_latest_status(db_file):
    """
    Читаємо останній запис статусу з БД
    
    ПОВЕРТАЄ:
        - dict: останній статус або None
    """
    try:
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM status ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    except Exception as e:
        logger.error(f"[STATUS_MANAGER] Помилка при читанні статусу: {e}")
        return None


def get_system_metrics(db_file):
    """
    Збираємо системні метрики
    
    ПОВЕРТАЄ:
        - dict: {uptime_seconds, memory_usage_mb, db_size_bytes, total_packets, total_logs}
    """
    try:
        # Uptime - замість цього будемо передавати з vrl.py
        # (тут ми не знаємо коли запустилась програма)
        
        # Memory
        try:
            process = psutil.Process(os.getpid())
            memory_mb = process.memory_info().rss / 1024 / 1024
        except:
            memory_mb = 0
        
        # DB size
        try:
            db_size = os.path.getsize(db_file)
        except:
            db_size = 0
        
        # Counts
        try:
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM packets_raw")
            total_packets = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM logs")
            total_logs = cursor.fetchone()[0]
            
            conn.close()
        except:
            total_packets = 0
            total_logs = 0
        
        return {
            'memory_usage_mb': memory_mb,
            'db_size_bytes': db_size,
            'total_packets_in_db': total_packets,
            'total_logs_in_db': total_logs,
        }
    
    except Exception as e:
        logger.error(f"[STATUS_MANAGER] Помилка при збиранні метрик: {e}")
        return {}


def collect_full_status(app_state):
    """
    Збираємо повний статус програми з app_state та системних метрик
    
    ПАРАМЕТРИ:
        - app_state: глобальний об'єкт стану
    
    ПОВЕРТАЄ:
        - dict: повний словник статусу для запису в БД та відправки
    """
    try:
        # Збираємо системні метрики
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
        
        return status_data
    except Exception as e:
        logger.error(f"[STATUS_MANAGER] Помилка при збиранні повного статусу: {e}")
        return {}


def format_status_json(status_record):
    """
    Формуємо JSON статус для API
    
    ПАРАМЕТРИ:
        - status_record: dict з БД
    
    ПОВЕРТАЄ:
        - dict: структурований JSON
    """
    if not status_record:
        return {}
    
    return {
        'timestamp': status_record.get('timestamp'),
        'parser': {
            'running': bool(status_record.get('parser_running')),
            'connected': bool(status_record.get('parser_connected')),
            'packets_total': status_record.get('parser_packets_total'),
            'packets_last_flush': status_record.get('parser_packets_last_flush'),
            'buffer_size': status_record.get('parser_buffer_size'),
            'last_error': status_record.get('parser_last_error'),
        },
        'analyser': {
            'running': bool(status_record.get('analyser_running')),
            'last_run': status_record.get('analyser_last_run'),
            'packets_processed': status_record.get('analyser_packets_processed'),
            'last_error': status_record.get('analyser_last_error'),
        },
        'sender': {
            'running': bool(status_record.get('sender_running')),
            'last_run': status_record.get('sender_last_run'),
            'packets_sent': status_record.get('sender_packets_sent'),
            'last_error': status_record.get('sender_last_error'),
        },
        'ping_handler': {
            'running': bool(status_record.get('ping_handler_running')),
            'last_run': status_record.get('ping_handler_last_run'),
            'last_error': status_record.get('ping_handler_last_error'),
        },
        'system': {
            'uptime_seconds': status_record.get('uptime_seconds'),
            'memory_usage_mb': status_record.get('memory_usage_mb'),
            'db_size_bytes': status_record.get('db_size_bytes'),
            'total_packets_in_db': status_record.get('total_packets_in_db'),
            'total_logs_in_db': status_record.get('total_logs_in_db'),
        },
        'version': status_record.get('app_version'),
    }
