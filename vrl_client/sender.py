#!/usr/bin/env python3
"""
sender.py - Відправка flight_tracks на API сервер
Управління розсиланням даних з обробкою помилок та повторних спроб
"""

import asyncio
import sqlite3
import json
import logging
import hmac
import hashlib
import base64
from datetime import datetime
from typing import List, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# Максимум записів за один запит
BATCH_SIZE = 100
# Максимум спроб відправки
MAX_RETRIES = 3
# Інтервал між спробами (секунди)
RETRY_DELAY = 5


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


def get_pending_tracks(db_file, limit: int = BATCH_SIZE) -> List[Dict]:
    """
    Отримуємо flight_tracks, які потрібно надіслати (sent = 0)
    """
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, callsign, height, fuel, timestamp
            FROM flight_tracks
            WHERE sent = 0
            ORDER BY timestamp ASC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        tracks = []
        for row_id, callsign, height, fuel, timestamp in rows:
            tracks.append({
                'track_id': row_id,
                'callsign': callsign,
                'height': height,
                'fuel': fuel,
                'timestamp': timestamp
            })
        
        return tracks
    
    except Exception as e:
        logger.error(f"Помилка при читанні tracks: {e}")
        return []


def mark_tracks_as_sent(db_file, track_ids: List[int]) -> bool:
    """
    Позначаємо tracks як надіслані (sent = 1)
    """
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        for track_id in track_ids:
            cursor.execute(
                "UPDATE flight_tracks SET sent = 1, sent_at = ? WHERE id = ?",
                (datetime.now().isoformat(), track_id)
            )
        
        conn.commit()
        conn.close()
        
        return True
    
    except Exception as e:
        logger.error(f"Помилка при позначенні tracks: {e}")
        return False


def mark_tracks_as_failed(db_file, track_ids: List[int], error_msg: str) -> bool:
    """
    Позначаємо tracks як помилка (sent = -1, error)
    """
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        for track_id in track_ids:
            cursor.execute(
                "UPDATE flight_tracks SET sent = -1, error = ? WHERE id = ?",
                (error_msg, track_id)
            )
        
        conn.commit()
        conn.close()
        
        return True
    
    except Exception as e:
        logger.error(f"Помилка при позначенні помилок: {e}")
        return False


async def send_tracks_to_api(config: Dict, db_file: str, tracks: List[Dict]) -> bool:
    """
    Відправляємо batch flight_tracks на API з HMAC підписом
    
    API Endpoint: POST /api/tracks
    Payload:
    {
        "client_id": "...",
        "tracks": [
            {"callsign": "...", "height": ..., "fuel": ..., "timestamp": "..."},
            ...
        ]
    }
    """
    
    if not tracks:
        return True
    
    try:
        # Підготовка payload
        payload = {
            'client_id': config['api']['client_id'],
            'tracks': [
                {
                    'callsign': track['callsign'],
                    'height': track['height'],
                    'fuel': track['fuel'],
                    'timestamp': track['timestamp']
                }
                for track in tracks
            ]
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
        url = f"{config['api']['url']}/api/tracks"
        
        logger.info(f"[SENDER] Відправка {len(tracks)} tracks на {url}")
        
        # Використовуємо requests в async контексті
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(
                url,
                data=payload_json,
                headers=headers,
                timeout=10
            )
        )
        
        # Перевіряємо статус відповіді
        if response.status_code == 200:
            logger.info(f"[SENDER] ✓ Успішно надіслано {len(tracks)} tracks")
            
            # Позначаємо як надіслані
            track_ids = [track['track_id'] for track in tracks]
            mark_tracks_as_sent(db_file, track_ids)
            
            log_to_db(db_file, 'INFO', 'SENDER', f'Надіслано {len(tracks)} tracks',
                     json.dumps({'count': len(tracks)}))
            
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


async def sender_loop(config: Dict, db_file: str):
    """
    Головний цикл sender
    
    При помилці не падає в аварію, а чекає наступного циклу.
    Дані залишаються в БД до успішної відправки.
    
    Логіка:
    1. Отримуємо batch пакетів з sent = 0
    2. Спробуємо надіслати на API
    3. При успіху позначаємо sent = 1
    4. При помилці (інтернет, timeout, API) залишаємо sent = 0 та продовжуємо
    5. Чекаємо наступного циклу
    """
    
    logger.info("[SENDER] Запуск sender...")
    log_to_db(db_file, 'INFO', 'SENDER', 'Sender запущений')
    
    sender_interval = config['cycles'].get('sender_interval', 3)
    batch_size = config['cycles'].get('batch_size', BATCH_SIZE)
    
    total_sent = 0
    failed_count = 0
    
    while True:
        try:
            # Отримуємо pending пакети
            tracks = get_pending_tracks(db_file, batch_size)
            
            if not tracks:
                await asyncio.sleep(sender_interval)
                continue
            
            # Спробуємо надіслати batch
            success = await send_tracks_to_api(config, db_file, tracks)
            
            if success:
                total_sent += len(tracks)
                failed_count = 0  # Скидаємо лічильник при успіху
                logger.info(f"[SENDER] Статистика: всього надіслано {total_sent} tracks")
            else:
                failed_count += 1
                if failed_count % 5 == 0:  # Логуємо кожні 5 невдач
                    logger.warning(f"[SENDER] {failed_count} неудалих спроб — дані збережені в БД")
            
            await asyncio.sleep(sender_interval)
        
        except KeyboardInterrupt:
            logger.info("[SENDER] Цикл зупинений")
            break
        
        except Exception as e:
            logger.error(f"[SENDER] Критична помилка в циклі: {e}")
            log_to_db(db_file, 'ERROR', 'SENDER', 'Критична помилка циклу', str(e)[:200])
            await asyncio.sleep(sender_interval)
    
    logger.info("[SENDER] Sender зупинений")
    log_to_db(db_file, 'INFO', 'SENDER', 'Sender зупинений')
