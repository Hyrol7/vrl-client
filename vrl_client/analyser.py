#!/usr/bin/env python3
"""
analyser.py - Аналіз та кореляція пакетів
Реалізує логіку розрахунку faithfulness та прив'язки K2 до K1.
"""

import asyncio
import sqlite3
import json
import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

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

def get_db_connection(db_file):
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn

# ============================================================
# ЕТАП 1: АНАЛІЗ K1 (Frequency Analysis)
# ============================================================

def analyze_k1_packets(db_file: str) -> int:
    """
    Аналізує частоту пакетів K1 за останні 30 секунд.
    Оновлює faithfulness та sent статус.
    Повертає кількість оновлених записів.
    """
    updated_count = 0
    try:
        conn = get_db_connection(db_file)
        cursor = conn.cursor()
        
        # Часове вікно: останні 30 секунд
        now = datetime.now()
        window_start = now - timedelta(seconds=30)
        
        # Отримуємо статистику по callsign
        # type=1 (K1), sent=1 (Synced)
        cursor.execute("""
            SELECT callsign, COUNT(*) as count
            FROM packets
            WHERE type = 1 
              AND sent = 1 
              AND created_at >= ?
            GROUP BY callsign
        """, (window_start,))
        
        stats = cursor.fetchall()
        
        for row in stats:
            callsign = row['callsign']
            count = row['count']
            
            new_faithfulness = None
            
            # Логіка розрахунку faithfulness
            if count < 2:
                new_faithfulness = 30
            elif 2 <= count < 5:
                # Гістерезис: не змінюємо
                continue
            elif 5 <= count < 10:
                new_faithfulness = 75
            elif 10 <= count < 20:
                new_faithfulness = 90
            elif count >= 20:
                new_faithfulness = 100
            
            if new_faithfulness is not None:
                # Оновлюємо записи, якщо faithfulness змінився
                # sent=1 -> sent=2 (Ready to Update)
                cursor.execute("""
                    UPDATE packets
                    SET faithfulness = ?, sent = 2, updated_at = CURRENT_TIMESTAMP
                    WHERE type = 1 
                      AND sent = 1 
                      AND callsign = ? 
                      AND faithfulness != ?
                      AND created_at >= ?
                """, (new_faithfulness, callsign, new_faithfulness, window_start))
                
                updated_count += cursor.rowcount
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"[ANALYSER] Помилка в K1 аналізі: {e}")
    
    return updated_count

# ============================================================
# ЕТАП 2: АНАЛІЗ K2 (Time Correlation)
# ============================================================

def load_context_packets(conn, window_seconds=120) -> List[Dict]:
    """Завантажує всі пакети за останні N секунд для контексту"""
    now = datetime.now()
    start_time = now - timedelta(seconds=window_seconds)
    
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, uuid, type, callsign, event_time, faithfulness, sent
        FROM packets
        WHERE created_at >= ?
        ORDER BY event_time ASC
    """, (start_time,))
    
    return [dict(row) for row in cursor.fetchall()]

def parse_event_time(time_str: str) -> float:
    """Перетворює рядок часу в timestamp"""
    try:
        # Спробуємо різні формати, якщо треба. Поки що стандартний ISO
        dt = datetime.fromisoformat(time_str)
        return dt.timestamp()
    except ValueError:
        # Fallback для форматів без T або інших
        try:
            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f")
            return dt.timestamp()
        except:
            try:
                dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                return dt.timestamp()
            except:
                return 0.0

def analyze_k2_packets(db_file: str) -> int:
    """
    Аналізує пакети K2, прив'язує до K1 та оновлює faithfulness.
    Повертає кількість оновлених записів.
    """
    updated_count = 0
    try:
        conn = get_db_connection(db_file)
        
        # 1. Завантажуємо контекст (всі пакети за 120с)
        context_packets = load_context_packets(conn)
        
        # Підготовка даних для швидкого пошуку
        k1_packets = []
        k2_targets = []
        
        now_ts = datetime.now().timestamp()
        
        # Фільтруємо пакети
        for p in context_packets:
            p['ts'] = parse_event_time(p['event_time'])
            
            if p['type'] == 1 and p['callsign']:
                k1_packets.append(p)
            
            elif p['type'] == 2:
                # Цільові K2: sent IN (-1, 1) та вік 20-100с
                age = now_ts - p['ts'] # Приблизний вік відносно event_time (або created_at)
                # Але краще використовувати created_at для віку обробки, 
                # проте в контексті у нас є тільки event_time. 
                # Припустимо, що event_time близький до реального часу.
                # Для точності краще брати created_at з БД, але тут спростимо.
                
                # В SQL запиті нижче ми виберемо ID цільових пакетів точніше
                pass

        # Вибираємо цільові K2 пакети з БД, щоб точно дотриматись часових рамок обробки
        cursor = conn.cursor()
        target_window_start = datetime.now() - timedelta(seconds=100)
        target_window_end = datetime.now() - timedelta(seconds=20)
        
        cursor.execute("""
            SELECT id, uuid, callsign, faithfulness, sent, event_time
            FROM packets
            WHERE type = 2 
              AND sent IN (-1, 1)
              AND created_at BETWEEN ? AND ?
        """, (target_window_start, target_window_end))
        
        targets = [dict(row) for row in cursor.fetchall()]
        
        updates = [] # Список (sql, params)
        
        for k2 in targets:
            k2_ts = parse_event_time(k2['event_time'])
            current_faithfulness = k2['faithfulness'] if k2['faithfulness'] else 0
            current_callsign = k2['callsign']
            
            # Розраховуємо faithfulness з нуля для ідемпотентності
            # Базове значення 0, додаємо бонуси за умови
            calculated_faithfulness = 0
            new_callsign = current_callsign
            
            # --- А. Глобальна перевірка (+/- 20с) ---
            nearby_k1_callsigns = set()
            for k1 in k1_packets:
                if abs(k1['ts'] - k2_ts) <= 20.0:
                    nearby_k1_callsigns.add(k1['callsign'])
            
            if len(nearby_k1_callsigns) == 1:
                calculated_faithfulness += 20
            
            # --- Б. Перевірка по часу (Proximity) ---
            closest_k1 = None
            min_diff = 100.0
            
            # Шукаємо найближчий K1
            candidates_in_window = []
            
            for k1 in k1_packets:
                diff = abs(k1['ts'] - k2_ts)
                
                # Ігноруємо конфліктуючі callsign
                if current_callsign and k1['callsign'] != current_callsign:
                    continue
                
                if diff <= 2.0:
                    candidates_in_window.append((diff, k1))
                    if diff < min_diff:
                        min_diff = diff
                        closest_k1 = k1
            
            # Перевірка на колізії у вікні 2с
            unique_candidates = set(c[1]['callsign'] for c in candidates_in_window)
            
            if len(unique_candidates) == 1 and closest_k1:
                # Єдиний кандидат
                if min_diff <= 1.0:
                    calculated_faithfulness += 50
                    new_callsign = closest_k1['callsign']
                elif 1.0 < min_diff <= 2.0:
                    calculated_faithfulness += 20
                    new_callsign = closest_k1['callsign']
            
            # --- В. Фіналізація ---
            final_faithfulness = min(calculated_faithfulness, 100)
            
            # Визначаємо новий статус
            new_sent = k2['sent']
            if k2['sent'] == -1:
                new_sent = 0 # Ready to Create
            elif k2['sent'] == 1:
                new_sent = 2 # Ready to Update
            
            # Якщо дані змінилися - додаємо в оновлення
            if final_faithfulness != current_faithfulness or new_callsign != current_callsign or new_sent != k2['sent']:
                updates.append((
                    final_faithfulness, 
                    new_callsign, 
                    new_sent, 
                    k2['uuid']
                ))
        
        # Виконуємо оновлення
        if updates:
            cursor.executemany("""
                UPDATE packets
                SET faithfulness = ?, callsign = ?, sent = ?, updated_at = CURRENT_TIMESTAMP
                WHERE uuid = ?
            """, updates)
            updated_count = len(updates)
            conn.commit()
        
        conn.close()
        
    except Exception as e:
        logger.error(f"[ANALYSER] Помилка в K2 аналізі: {e}")
        
    return updated_count

# ============================================================
# ГОЛОВНИЙ ЦИКЛ
# ============================================================

async def analyser_loop(config, db_file, app_state):
    """Головний цикл аналізатора"""
    logger.info("[ANALYSER] Запуск аналізатора...")
    log_to_db(db_file, 'INFO', 'ANALYSER', 'Аналізатор запущений')
    
    app_state.analyser_state['running'] = True
    
    analyser_interval = config['cycles'].get('analyser_interval', 5)
    
    while True:
        try:
            start_time = time.time()
            
            # Етап 1: K1
            k1_updates = analyze_k1_packets(db_file)
            
            # Етап 2: K2
            k2_updates = analyze_k2_packets(db_file)
            
            total_updates = k1_updates + k2_updates
            
            if total_updates > 0:
                logger.info(f"[ANALYSER] Оновлено: K1={k1_updates}, K2={k2_updates}")
                app_state.analyser_state['last_run'] = int(time.time())
                app_state.analyser_state['packets_processed'] += total_updates
            
            # Розрахунок часу сну, щоб тримати ритм
            elapsed = time.time() - start_time
            sleep_time = max(0.1, analyser_interval - elapsed)
            
            await asyncio.sleep(sleep_time)
        
        except KeyboardInterrupt:
            break
        
        except Exception as e:
            logger.error(f"[ANALYSER] Критична помилка: {e}")
            app_state.analyser_state['last_error'] = str(e)[:100]
            await asyncio.sleep(analyser_interval)
    
    app_state.analyser_state['running'] = False
    logger.info("[ANALYSER] Аналізатор зупинений")
    log_to_db(db_file, 'INFO', 'ANALYSER', 'Аналізатор зупинений')
