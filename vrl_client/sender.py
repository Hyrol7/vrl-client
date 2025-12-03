#!/usr/bin/env python3
"""
sender.py - Відправка пакетів на API сервер
Управління розсиланням даних з обробкою помилок та повторних спроб.
Працює з таблицею packets та використовує UUID для ідентифікації.
"""

import asyncio
import sqlite3
import json
import logging
import hmac
import hashlib
import base64
import time
from datetime import datetime
from typing import List, Dict, Optional

import requests

logger = logging.getLogger(__name__)


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
        logger.error(f"Помилка при запису логу: {e}")


def generate_hmac_signature(data: str, secret_key: str) -> str:
    """
    Генеруємо HMAC-SHA256 підпис для API запиту
    """
    try:
        signature = hmac.new(
            secret_key.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature).decode('utf-8')
    except Exception as e:
        logger.error(f"Помилка при генерації підпису: {e}")
        return None


def get_pending_packets(db_file, limit: int = 100) -> List[Dict]:
    """
    Отримуємо пакети, які потрібно надіслати (sent = 0 або sent = 2)
    sent = 0 -> Create
    sent = 2 -> Update
    """
    try:
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT uuid, event_time, type, callsign, height, fuel, alarm, faithfulness, sent
            FROM packets
            WHERE sent IN (0, 2)
            ORDER BY created_at ASC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        packets = []
        for row in rows:
            packets.append(dict(row))
        
        return packets
    
    except Exception as e:
        logger.error(f"Помилка при читанні пакетів: {e}")
        return []


def mark_packets_as_synced(db_file, uuids: List[str]) -> bool:
    """
    Позначаємо пакети як синхронізовані (sent = 1)
    """
    if not uuids:
        return True
        
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # SQLite має ліміт на кількість змінних, тому розбиваємо на чанки якщо треба
        # Але для BATCH_SIZE=100 це не проблема
        placeholders = ','.join(['?'] * len(uuids))
        query = f"UPDATE packets SET sent = 1, updated_at = CURRENT_TIMESTAMP WHERE uuid IN ({placeholders})"
        
        cursor.execute(query, uuids)
        
        conn.commit()
        conn.close()
        
        return True
    
    except Exception as e:
        logger.error(f"Помилка при оновленні статусу пакетів: {e}")
        return False


async def send_packets_to_api(config: Dict, db_file: str, packets: List[Dict]) -> bool:
    """
    Відправляємо batch пакетів на API з HMAC підписом
    
    API Endpoint: POST /api/packets
    Payload:
    {
        "client_id": "...",
        "create": [ ... ],
        "update": [ ... ]
    }
    """
    
    if not packets:
        return True
    
    try:
        # Розділяємо на create та update
        create_list = []
        update_list = []
        
        for p in packets:
            packet_data = {
                'uuid': p['uuid'],
                'event_time': p['event_time'],
                'type': p['type'],
                'callsign': p['callsign'],
                'height': p['height'],
                'fuel': p['fuel'],
                'alarm': p['alarm'],
                'faithfulness': p['faithfulness']
            }
            
            if p['sent'] == 0:
                create_list.append(packet_data)
            elif p['sent'] == 2:
                update_list.append(packet_data)
        
        # Підготовка payload
        payload = {
            'client_id': config['api']['client_id'],
            'create': create_list,
            'update': update_list
        }
        
        # Сериалізуємо в JSON для підпису
        payload_json = json.dumps(payload, separators=(',', ':'), sort_keys=True)
        
        # Генеруємо HMAC підпис
        signature = generate_hmac_signature(
            payload_json,
            config['api']['secret_key']
        )
        
        if not signature:
            logger.error("[SENDER] Не вдалося створити підпис")
            return False
        
        # Готуємо заголовки
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {config['api']['bearer_token']}",
            'X-Signature': signature
        }
        
        # Відправляємо запит
        url = f"{config['api']['url']}/api/packets" # Припускаємо новий endpoint
        
        logger.info(f"[SENDER] Відправка: Create={len(create_list)}, Update={len(update_list)} на {url}")
        
        # Використовуємо requests в async контексті
        loop = asyncio.get_event_loop()
        timeout = config['api'].get('timeout', 30)
        
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(
                url,
                data=payload_json,
                headers=headers,
                timeout=timeout
            )
        )
        
        # Перевіряємо статус відповіді
        if response.status_code == 200:
            logger.info(f"[SENDER] ✓ Успішно синхронізовано {len(packets)} пакетів")
            
            # Позначаємо як надіслані
            uuids = [p['uuid'] for p in packets]
            mark_packets_as_synced(db_file, uuids)
            
            log_to_db(db_file, 'INFO', 'SENDER', f'Синхронізовано {len(packets)} пакетів',
                     json.dumps({'create': len(create_list), 'update': len(update_list)}))
            
            return True
        
        else:
            logger.warning(f"[SENDER] ✗ Помилка API: {response.status_code} - {response.text}")
            
            log_to_db(db_file, 'WARNING', 'SENDER', f'API помилка {response.status_code}',
                     response.text[:500])
            
            return False
    
    except requests.ConnectionError as e:
        logger.warning(f"[SENDER] Помилка з'єднання (інтернет недоступний): {type(e).__name__}")
        log_to_db(db_file, 'WARNING', 'SENDER', 'Помилка з\'єднання', f"Інтернет недоступний")
        return False
    
    except requests.Timeout as e:
        logger.warning(f"[SENDER] Timeout при з'єднанні з API")
        log_to_db(db_file, 'WARNING', 'SENDER', 'Timeout', f"Сервер не відповідає")
        return False
    
    except Exception as e:
        logger.warning(f"[SENDER] Непередбачена помилка: {e}")
        log_to_db(db_file, 'WARNING', 'SENDER', 'Помилка відправки', str(e)[:200])
        return False


async def sender_loop(config: Dict, db_file: str, app_state):
    """
    Головний цикл sender
    
    При помилці не падає в аварію, а чекає наступного циклу.
    Дані залишаються в БД до успішної відправки.
    
    Логіка:
    1. Отримуємо batch пакетів з sent IN (0, 2)
    2. Спробуємо надіслати на API
    3. При успіху позначаємо sent = 1
    4. При помилці (інтернет, timeout, API) залишаємо статус як є та продовжуємо
    5. Чекаємо наступного циклу
    """
    
    logger.info("[SENDER] Запуск sender...")
    log_to_db(db_file, 'INFO', 'SENDER', 'Sender запущений')
    
    # Ініціалізуємо стан sender
    app_state.sender_state['running'] = True
    app_state.sender_state['last_run'] = None
    app_state.sender_state['packets_sent'] = 0
    app_state.sender_state['last_error'] = None
    
    sender_interval = config['cycles'].get('sender_interval', 3)
    batch_size = config['cycles'].get('batch_size', 100)
    
    total_sent = 0
    failed_count = 0
    
    while True:
        try:
            # Отримуємо pending пакети
            packets = get_pending_packets(db_file, batch_size)
            
            if not packets:
                await asyncio.sleep(sender_interval)
                continue
            
            # Спробуємо надіслати batch
            success = await send_packets_to_api(config, db_file, packets)
            
            if success:
                total_sent += len(packets)
                failed_count = 0  # Скидаємо лічильник при успіху
                app_state.sender_state['last_run'] = int(time.time())
                app_state.sender_state['packets_sent'] = len(packets)
                app_state.sender_state['last_error'] = None
                logger.info(f"[SENDER] Статистика: всього синхронізовано {total_sent} пакетів")
                await asyncio.sleep(sender_interval)
            else:
                failed_count += 1
                app_state.sender_state['last_error'] = 'Помилка при відправці'
                if failed_count % 5 == 0:  # Логуємо кожні 5 невдач
                    logger.warning(f"[SENDER] {failed_count} неудалих спроб — дані збережені в БД")
                
                # При помилці чекаємо retry_delay
                retry_delay = config['api'].get('retry_delay', 5)
                await asyncio.sleep(retry_delay)
        
        except KeyboardInterrupt:
            app_state.sender_state['running'] = False
            logger.info("[SENDER] Цикл зупинений")
            break
        
        except Exception as e:
            logger.error(f"[SENDER] Критична помилка в циклі: {e}")
            app_state.sender_state['last_error'] = str(e)[:100]
            log_to_db(db_file, 'ERROR', 'SENDER', 'Критична помилка циклу', str(e)[:200])
            await asyncio.sleep(sender_interval)
    
    app_state.sender_state['running'] = False
    logger.info("[SENDER] Sender зупинений")
    log_to_db(db_file, 'INFO', 'SENDER', 'Sender зупинений')
