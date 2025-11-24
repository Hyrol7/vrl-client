#!/usr/bin/env python3
"""
parser.py - Парсинг даних від декодера
Підключається до TCP-порту декодера та парсить пакети K1/K2 в формату AVR
"""

import asyncio
import sqlite3
import re
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Регулярні вирази для парсингу
K1_PATTERN = re.compile(
    r'^K1\s+(\d{2}):(\d{2}):(\d{2})\.(\d+)\.(\d+)\s+.*?:(\d+)$',
    re.MULTILINE
)

K2_PATTERN = re.compile(
    r'^K2\s+(\d{2}):(\d{2}):(\d{2})\.(\d+)\.(\d+)\s+.*?FL\s*(\d+)m.*?F:(\d+)%',
    re.MULTILINE
)


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


def get_local_date():
    """Отримуємо локальну дату в форматі YYYY-MM-DD"""
    return datetime.now().strftime('%Y-%m-%d')


def parse_k1_packet(line, db_file):
    """
    Парсимо K1 пакет (позивний літака)
    Формат: K1 11:11:38.370.366 [ 8832] {018} **** :10437
    """
    try:
        match = K1_PATTERN.search(line)
        if not match:
            log_to_db(db_file, 'WARNING', 'PARSER', 'K1 пакет не розпізнаний', line)
            return None
        
        hours = match.group(1)
        minutes = match.group(2)
        seconds = match.group(3)
        callsign = match.group(6)
        
        event_time = f"{get_local_date()} {hours}:{minutes}:{seconds}"
        
        return {
            'event_time': event_time,
            'type': 1,  # K1
            'callsign': callsign,
            'height': None,
            'fuel': None,
            'alarm': 0,
            'faithfulness': 50,
        }
    
    except Exception as e:
        log_to_db(db_file, 'ERROR', 'PARSER', 'Помилка парсингу K1', f"{line} | {str(e)}")
        return None


def parse_k2_packet(line, db_file):
    """
    Парсимо K2 пакет (висота та паливо)
    Формат: K2 11:12:54.082.632 [ 8706] {017} **** FL 5360m [F176]+  F:40%
    """
    try:
        match = K2_PATTERN.search(line)
        if not match:
            log_to_db(db_file, 'WARNING', 'PARSER', 'K2 пакет не розпізнаний', line)
            return None
        
        hours = match.group(1)
        minutes = match.group(2)
        seconds = match.group(3)
        height = int(match.group(6))
        fuel = int(match.group(7))
        
        event_time = f"{get_local_date()} {hours}:{minutes}:{seconds}"
        
        return {
            'event_time': event_time,
            'type': 2,  # K2
            'callsign': None,
            'height': height,
            'fuel': fuel,
            'alarm': 0,
            'faithfulness': 0,
        }
    
    except Exception as e:
        log_to_db(db_file, 'ERROR', 'PARSER', 'Помилка парсингу K2', f"{line} | {str(e)}")
        return None


def parse_line(line, db_file):
    """
    Розпізнаємо тип пакету та парсимо його
    """
    if not line or not line.strip():
        return None
    
    line = line.strip()
    
    if line.startswith('K1 '):
        return parse_k1_packet(line, db_file)
    elif line.startswith('K2 '):
        return parse_k2_packet(line, db_file)
    else:
        # Ігноруємо інші рядки (наприклад, інформацію про старт програми)
        return None


def save_packet_to_db(db_file, packet):
    """Зберігаємо розпарсений пакет в БД"""
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        cursor.execute(
            """INSERT INTO packets_raw 
               (event_time, type, callsign, height, fuel, alarm, faithfulness)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                packet['event_time'],
                packet['type'],
                packet['callsign'],
                packet['height'],
                packet['fuel'],
                packet['alarm'],
                packet['faithfulness'],
            )
        )
        
        conn.commit()
        conn.close()
        return True
    
    except Exception as e:
        log_to_db(db_file, 'ERROR', 'PARSER', 'Помилка збереження пакету', str(e))
        return False


async def connect_to_decoder(config):
    """Підключаємось до TCP-порту декодера"""
    host = config['decoder']['host']
    port = config['decoder']['port']
    timeout = config['decoder']['timeout']
    
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout
        )
        logger.info(f"✓ Підключено до декодера ({host}:{port})")
        return reader, writer
    
    except Exception as e:
        logger.error(f"❌ Не вдалось підключитись до декодера: {e}")
        return None, None


async def parser_loop(config, db_file):
    """Головний цикл парсера"""
    logger.info("[PARSER] Запуск парсера...")
    log_to_db(db_file, 'INFO', 'PARSER', 'Парсер запущений')
    
    reconnect_delay = config['decoder']['reconnect_delay']
    parser_interval = config['cycles']['parser_interval']
    
    reader, writer = None, None
    packet_buffer = ""
    packets_count = 0
    
    while True:
        try:
            # Якщо з'єднання розірване - переподключаємось
            if reader is None:
                logger.info("[PARSER] Спроба переподключення...")
                reader, writer = await connect_to_decoder(config)
                if reader is None:
                    await asyncio.sleep(reconnect_delay)
                    continue
                
                log_to_db(db_file, 'INFO', 'PARSER', 'Переподключено до декодера')
            
            # Читаємо дані з декодера
            try:
                data = await asyncio.wait_for(
                    reader.read(4096),
                    timeout=config['decoder']['timeout']
                )
                
                if not data:
                    logger.warning("[PARSER] З'єднання закрито декодером")
                    reader, writer = None, None
                    log_to_db(db_file, 'WARNING', 'PARSER', 'З\'єднання закрито')
                    await asyncio.sleep(reconnect_delay)
                    continue
                
                # Додаємо дані до буфера
                packet_buffer += data.decode('utf-8', errors='ignore')
                
                # Обробляємо рядки з буфера
                while '\n' in packet_buffer:
                    line, packet_buffer = packet_buffer.split('\n', 1)
                    
                    # Парсимо рядок
                    packet = parse_line(line, db_file)
                    
                    if packet:
                        # Зберігаємо в БД
                        if save_packet_to_db(db_file, packet):
                            packets_count += 1
                            if packets_count % 100 == 0:
                                logger.info(f"[PARSER] Оброблено {packets_count} пакетів")
                
            except asyncio.TimeoutError:
                logger.warning("[PARSER] Timeout при читанні даних")
                reader, writer = None, None
                log_to_db(db_file, 'WARNING', 'PARSER', 'Timeout')
                await asyncio.sleep(reconnect_delay)
                continue
            
            except Exception as e:
                logger.error(f"[PARSER] Помилка при читанні: {e}")
                reader, writer = None, None
                log_to_db(db_file, 'ERROR', 'PARSER', 'Помилка читання', str(e))
                await asyncio.sleep(reconnect_delay)
                continue
            
            await asyncio.sleep(parser_interval)
        
        except KeyboardInterrupt:
            break
        
        except Exception as e:
            logger.error(f"[PARSER] Критична помилка: {e}")
            log_to_db(db_file, 'ERROR', 'PARSER', 'Критична помилка', str(e))
            await asyncio.sleep(reconnect_delay)
    
    # Закриваємо з'єднання при завершенні
    if writer:
        writer.close()
        await writer.wait_closed()
    
    logger.info("[PARSER] Парсер зупинений")
    log_to_db(db_file, 'INFO', 'PARSER', 'Парсер зупинений')


# Точка входу для тестування
if __name__ == '__main__':
    # Для тестування парсера окремо
    test_lines = [
        "K1 11:11:38.370.366 [ 8832] {018} **** :10437",
        "K2 11:12:54.082.632 [ 8706] {017} **** FL 5360m [F176]+  F:40%",
        "K1 10:44:40.708.069 [     ] {016} **** :14055",
        "K2 10:44:45.065.415 [     ] {01B} **** FL 6130m [F201]+  F:35%",
    ]
    
    print("Тестування парсера:")
    for line in test_lines:
        packet = parse_line(line, '')
        if packet:
            print(f"✓ {line}")
            print(f"  → {packet}\n")
        else:
            print(f"✗ {line}\n")
