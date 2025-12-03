#!/usr/bin/env python3
"""
analyser.py - Аналіз та біндинг K1↔K2 пакетів
Зв'язує позивні (K1) з висотою/паливом (K2) в часовому вікні
"""

import asyncio
import sqlite3
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Регулярні вирази для парсингу часу
TIME_WINDOW = 5  # секунди - максимальна різниця між K1 та K2


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


def parse_time(time_str):
    """Парсимо час в форматі YYYY-MM-DD HH:MM:SS"""
    try:
        return datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
    except:
        return None


def get_unmatched_packets(db_file, limit=1000):
    """
    Отримуємо K1 та K2 пакети, які ще не біндені
    (sent = 0, 'callsign' або 'height')
    """
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # K1 пакети (які мають callsign)
        cursor.execute("""
            SELECT id, event_time, callsign, type
            FROM packets_raw
            WHERE sent = 0 AND type = 1 AND callsign IS NOT NULL
            ORDER BY event_time ASC
            LIMIT ?
        """, (limit,))
        
        k1_packets = cursor.fetchall()
        
        # K2 пакети (які мають висоту)
        cursor.execute("""
            SELECT id, event_time, height, fuel, type
            FROM packets_raw
            WHERE sent = 0 AND type = 2 AND height IS NOT NULL
            ORDER BY event_time ASC
            LIMIT ?
        """, (limit,))
        
        k2_packets = cursor.fetchall()
        
        conn.close()
        
        return k1_packets, k2_packets
    
    except Exception as e:
        logger.error(f"Помилка при читанні пакетів: {e}")
        return [], []


def create_flight_track(db_file, k1_id, k1_callsign, k1_time, k2_id, k2_height, k2_fuel, k2_time, time_offset=0.0):
    """
    Створюємо запис flight_track з біндених K1 та K2
    """
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # Розраховуємо правильний час створення
        now = datetime.now()
        if time_offset != 0:
            now = now + timedelta(seconds=time_offset)
        
        # Створюємо flight_track
        cursor.execute("""
            INSERT INTO flight_tracks 
            (k1_packet_id, k2_packet_id, callsign, height, fuel, timestamp, sent)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (k1_id, k2_id, k1_callsign, k2_height, k2_fuel, now.isoformat(), 0))
        
        track_id = cursor.lastrowid
        
        # Позначаємо пакети як біндені (окремо)
        cursor.execute("UPDATE packets_raw SET bound_to_track = ? WHERE id = ?", (track_id, k1_id))
        cursor.execute("UPDATE packets_raw SET bound_to_track = ? WHERE id = ?", (track_id, k2_id))
        
        conn.commit()
        conn.close()
        
        return track_id
    
    except Exception as e:
        logger.error(f"Помилка при створенні flight_track: {e}")
        return None


def match_k1_k2_packets(db_file, k1_packets, k2_packets, time_offset=0.0):
    """
    Біндимо K1 та K2 пакети в часовому вікні (TIME_WINDOW секунд)
    
    Алгоритм:
    1. Для кожного K1 ищемо K2 з тією ж дельтою часу ≤ TIME_WINDOW
    2. Якщо знайшли - створюємо flight_track
    3. Позначаємо як оброблені
    """
    
    matches = []
    
    for k1_id, k1_time, k1_callsign, k1_type in k1_packets:
        k1_dt = parse_time(k1_time)
        if not k1_dt:
            continue
        
        # Ищемо відповідний K2 пакет в часовому вікні
        best_match = None
        min_diff = timedelta(seconds=TIME_WINDOW + 1)
        
        for k2_id, k2_time, k2_height, k2_fuel, k2_type in k2_packets:
            k2_dt = parse_time(k2_time)
            if not k2_dt:
                continue
            
            # Обчислюємо різницю в часі
            diff = abs(k2_dt - k1_dt)
            
            # Якщо в часовому вікні
            if diff <= timedelta(seconds=TIME_WINDOW):
                if diff < min_diff:
                    min_diff = diff
                    best_match = (k2_id, k2_time, k2_height, k2_fuel)
        
        # Якщо знайшли добрий матч
        if best_match:
            k2_id, k2_time, k2_height, k2_fuel = best_match
            
            track_id = create_flight_track(
                db_file, k1_id, k1_callsign, k1_time, 
                k2_id, k2_height, k2_fuel, k2_time,
                time_offset
            )
            
            if track_id:
                matches.append({
                    'track_id': track_id,
                    'callsign': k1_callsign,
                    'height': k2_height,
                    'fuel': k2_fuel,
                    'time_diff': min_diff.total_seconds()
                })
                
                logger.info(f"[ANALYSER] Біндено: {k1_callsign} → {k2_height}m, паливо {k2_fuel}% (Δt={min_diff.total_seconds():.1f}s)")
    
    return matches


def get_flight_tracks_for_sending(db_file, limit=100):
    """
    Отримуємо flight_tracks, які ще не надіслані (sent = 0)
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
        
        tracks = cursor.fetchall()
        conn.close()
        
        return tracks
    
    except Exception as e:
        logger.error(f"Помилка при читанні flight_tracks: {e}")
        return []


async def analyser_loop(config, db_file, app_state):
    """Головний цикл аналізатора"""
    logger.info("[ANALYSER] Запуск аналізатора...")
    log_to_db(db_file, 'INFO', 'ANALYSER', 'Аналізатор запущений')
    
    # Ініціалізуємо стан аналізатора
    app_state.analyser_state['running'] = True
    app_state.analyser_state['last_run'] = None
    app_state.analyser_state['packets_processed'] = 0
    app_state.analyser_state['last_error'] = None
    
    analyser_interval = config['cycles'].get('analyser_interval', 2)
    batch_size = config['cycles'].get('batch_size', 1000)
    
    total_matches = 0
    
    while True:
        try:
            # Отримуємо необроблені пакети
            k1_packets, k2_packets = get_unmatched_packets(db_file, batch_size)
            
            if not k1_packets or not k2_packets:
                await asyncio.sleep(analyser_interval)
                continue
            
            # Біндимо K1↔K2
            matches = match_k1_k2_packets(db_file, k1_packets, k2_packets, app_state.time_offset)
            
            if matches:
                total_matches += len(matches)
                import time
                app_state.analyser_state['last_run'] = int(time.time())
                app_state.analyser_state['packets_processed'] = len(matches)
                app_state.analyser_state['last_error'] = None
                logger.info(f"[ANALYSER] Оброблено: {len(matches)} матчів (всього: {total_matches})")
                log_to_db(db_file, 'INFO', 'ANALYSER', f'Оброблено {len(matches)} матчів', 
                         json.dumps({'matches': len(matches), 'total': total_matches}))
            
            await asyncio.sleep(analyser_interval)
        
        except KeyboardInterrupt:
            app_state.analyser_state['running'] = False
            break
        
        except Exception as e:
            logger.error(f"[ANALYSER] Помилка: {e}")
            app_state.analyser_state['last_error'] = str(e)[:100]
            log_to_db(db_file, 'ERROR', 'ANALYSER', 'Помилка аналізу', str(e))
            await asyncio.sleep(analyser_interval)
    
    app_state.analyser_state['running'] = False
    logger.info("[ANALYSER] Аналізатор зупинений")
    log_to_db(db_file, 'INFO', 'ANALYSER', 'Аналізатор зупинений')
