#!/usr/bin/env python3
"""
parser.py - Парсинг даних від декодера
Підключається до TCP-порту декодера та парсить пакети K1/K2 в формату AVR
"""

import asyncio
import sqlite3
import re
import logging
from datetime import datetime, timedelta
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


def get_local_date(time_offset=0.0):
    """
    Отримуємо локальну дату в форматі YYYY-MM-DD
    Враховуємо time_offset (різницю між системним і реальним часом)
    """
    now = datetime.now()
    if time_offset != 0:
        now = now + timedelta(seconds=time_offset)
    return now.strftime('%Y-%m-%d')


def parse_k1_packet(line, db_file, time_offset=0.0):
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
        
        event_time = f"{get_local_date(time_offset)} {hours}:{minutes}:{seconds}"
        
        return {
            'event_time': event_time,
            'type': 1,  # K1
            'callsign': callsign,
            'height': None,
            'fuel': None,
            'alarm': 0,
            'faithfulness': 50,
            'sent': 1,
        }
    
    except Exception as e:
        log_to_db(db_file, 'ERROR', 'PARSER', 'Помилка парсингу K1', f"{line} | {str(e)}")
        return None


def parse_k2_packet(line, db_file, time_offset=0.0):
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
        
        event_time = f"{get_local_date(time_offset)} {hours}:{minutes}:{seconds}"
        
        return {
            'event_time': event_time,
            'type': 2,  # K2
            'callsign': None,
            'height': height,
            'fuel': fuel,
            'alarm': 0,
            'faithfulness': 0,
            'sent': 0,
        }
    
    except Exception as e:
        log_to_db(db_file, 'ERROR', 'PARSER', 'Помилка парсингу K2', f"{line} | {str(e)}")
        return None


def parse_line(line, db_file, time_offset=0.0):
    """
    Розпізнаємо тип пакету та парсимо його
    """
    if not line or not line.strip():
        return None
    
    line = line.strip()
    
    if line.startswith('K1 '):
        return parse_k1_packet(line, db_file, time_offset)
    elif line.startswith('K2 '):
        return parse_k2_packet(line, db_file, time_offset)
    else:
        # Ігноруємо інші рядки (наприклад, інформацію про старт програми)
        return None


def save_packet_to_db(db_file, packet):
    """Зберігаємо розпарсений пакет в БД"""
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        cursor.execute(
            """INSERT INTO packets 
               (event_time, type, callsign, height, fuel, alarm, faithfulness, sent)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                packet['event_time'],
                packet['type'],
                packet['callsign'],
                packet['height'],
                packet['fuel'],
                packet['alarm'],
                packet['faithfulness'],
                packet['sent'],
            )
        )
        
        conn.commit()
        conn.close()
        return True
    
    except Exception as e:
        log_to_db(db_file, 'ERROR', 'PARSER', 'Помилка збереження пакету', str(e))
        return False


async def flush_packets(db_file, packets_buffer, total_packets):
    """
    Записуємо накопичені пакети в БД
    
    ПАРАМЕТРИ:
        - db_file: шлях до БД
        - packets_buffer: список накопичених пакетів
        - total_packets: поточна кількість записаних пакетів
    
    ПОВЕРТАЄ:
        - total_packets: оновлена кількість записаних пакетів
    """
    if not packets_buffer:
        return total_packets
    
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # Батч-запис: executemany() одним запитом (набагато швидше!)
        data = [
            (
                packet['event_time'],
                packet['type'],
                packet['callsign'],
                packet['height'],
                packet['fuel'],
                packet['alarm'],
                packet['faithfulness'],
                packet['sent'],
            )
            for packet in packets_buffer
        ]
        
        cursor.executemany(
            """INSERT INTO packets 
               (event_time, type, callsign, height, fuel, alarm, faithfulness, sent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            data
        )
        
        conn.commit()
        conn.close()
        
        packets_count = len(packets_buffer)
        total_packets += packets_count
        
        # Логування тільки кожних 100 пакетів
        if total_packets % 100 == 0:
            logger.info(f"[PARSER] ✓ Оброблено {total_packets} пакетів")
        
        return total_packets
    
    except Exception as e:
        log_to_db(db_file, 'ERROR', 'PARSER', 'Помилка запису буфера', str(e)[:200])
        # ⚠️ ВАЖЛИВО: буфер НЕ очищується при помилці!
        # Повинна повертатися та спробуватися записати наступний раз
        return total_packets


async def connect_to_decoder(config):
    """Підключаємось до TCP-порту декодера"""
    decoder_config = config.get('decoder', {})
    
    host = decoder_config.get('host', '127.0.0.1')
    port = decoder_config.get('port', 31003)
    connect_timeout = decoder_config.get('connect_timeout', 2)
    
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=connect_timeout
        )
        logger.info(f"✓ Підключено до декодера ({host}:{port})")
        return reader, writer
    
    except Exception as e:
        logger.error(f"❌ Не вдалось підключитись до декодера: {e}")
        return None, None


async def parser_loop(config, db_file, app_state):
    """
    Головний цикл парсера
    
    Логіка:
    1. Підключаємось до декодера
    2. Постійно очікуємо дані (без затримок)
    3. Накопичуємо пакети в буфер протягом parser_buffer_interval сек
    4. Через визначений інтервал записуємо накопичені пакети в БД
    5. При розриві з'єднання — перепідключаємось з визначеним інтервалом
    6. Записуємо тільки ті стрічки, які починаються на K1 або K2
    """
    logger.info("[PARSER] Запуск парсера...")
    log_to_db(db_file, 'INFO', 'PARSER', 'Парсер запущений')
    
    # Ініціалізуємо стан парсера
    app_state.parser_state['running'] = True
    app_state.parser_state['connected'] = False
    app_state.parser_state['packets_total'] = 0
    app_state.parser_state['packets_last_flush'] = 0
    app_state.parser_state['buffer_size'] = 0
    app_state.parser_state['last_error'] = None
    
    # Валідація конфігурації з дефолтними значеннями
    DEFAULT_DECODER = {
        'host': '127.0.0.1',
        'port': 31003,
        'connect_timeout': 2,
        'reconnect_delay': 3,
        'buffer_overflow_limit': 10000,
    }
    DEFAULT_CYCLES = {
        'parser_buffer_interval': 2,
    }
    
    decoder_config = config.get('decoder', {})
    cycles_config = config.get('cycles', {})
    
    connect_timeout = decoder_config.get('connect_timeout', DEFAULT_DECODER['connect_timeout'])
    reconnect_delay = decoder_config.get('reconnect_delay', DEFAULT_DECODER['reconnect_delay'])
    buffer_overflow_limit = decoder_config.get('buffer_overflow_limit', DEFAULT_DECODER['buffer_overflow_limit'])
    buffer_interval = cycles_config.get('parser_buffer_interval', DEFAULT_CYCLES['parser_buffer_interval'])
    
    reader, writer = None, None
    text_buffer = ""  # Буфер для накопичення текстових даних
    packets_buffer = []  # Буфер для накопичених пакетів перед записом в БД
    last_flush_time = asyncio.get_event_loop().time()
    total_packets = 0
    connected = False
    
    while True:
        try:
            # Якщо з'єднання розірване - переподключаємось
            if reader is None:
                if connected:
                    logger.warning("[PARSER] З'єднання розірвано! Перепідключаємся...")
                    log_to_db(db_file, 'WARNING', 'PARSER', 'З\'єднання розірвано')
                    connected = False
                    app_state.parser_state['connected'] = False
                
                logger.info(f"[PARSER] Спроба підключення (чекаємо {reconnect_delay}s)...")
                await asyncio.sleep(reconnect_delay)
                
                reader, writer = await connect_to_decoder(config)
                
                if reader is not None:
                    logger.info("[PARSER] ✓ Підключено до декодера")
                    log_to_db(db_file, 'INFO', 'PARSER', 'Підключено до декодера')
                    connected = True
                    app_state.parser_state['connected'] = True
                    app_state.parser_state['last_error'] = None
                    text_buffer = ""  # Очищуємо text_buffer при новому підключенні
                    # ⚠️ НЕ скидаємо last_flush_time тут! Залишаємо таймер як є
                    continue
                else:
                    # Логуємо невдалу спробу тільки якщо це перша спроба або пройшло багато часу
                    # щоб не спамити в логи кожні 3 секунди
                    logger.warning("[PARSER] Не вдалось підключитись, декодер ще не готовий...")
                    continue
            
            # Постійно очікуємо дані (БЕЗ timeout, БЕЗ затримок)
            try:
                data = await reader.read(4096)
                
                if not data:
                    # Дані пусті - декодер закрив з'єднання
                    logger.warning("[PARSER] Декодер закрив з'єднання (дані пусті)")
                    reader, writer = None, None
                    log_to_db(db_file, 'WARNING', 'PARSER', 'Декодер закрив з\'єднання')
                    # Записуємо накопичені пакети перед розривом
                    if packets_buffer:
                        await flush_packets(db_file, packets_buffer, total_packets)
                        packets_buffer = []
                    continue
                
                # 🟢 ДАНІ ПРИЙШЛИ! Додаємо в текстовий буфер
                text_buffer += data.decode('utf-8', errors='ignore')
                
                # Обробляємо ВСІ повні рядки з буфера
                while '\n' in text_buffer:
                    line, text_buffer = text_buffer.split('\n', 1)
                    line = line.strip()
                    
                    # Парсимо тільки K1 та K2 пакети (без логування для інших)
                    if line.startswith('K1 ') or line.startswith('K2 '):
                        # Використовуємо актуальний time_offset з app_state
                        packet = parse_line(line, db_file, app_state.time_offset)
                        if packet:
                            packets_buffer.append(packet)
                    # Інші рядки просто ігноруємо без логування
                
                # Контроль переповнення text_buffer (overflow protection)
                if len(text_buffer) > buffer_overflow_limit:
                    logger.warning(f"[PARSER] text_buffer overflow ({len(text_buffer)} > {buffer_overflow_limit})")
                    log_to_db(db_file, 'WARNING', 'PARSER', 'text_buffer overflow', 
                             f"Size: {len(text_buffer)} bytes")
                    text_buffer = ""  # Очищуємо буфер, щоб уникнути утечки пам'яті
                
                # Перевіряємо, чи час флаша
                current_time = asyncio.get_event_loop().time()
                if current_time - last_flush_time >= buffer_interval and packets_buffer:
                    total_packets = await flush_packets(db_file, packets_buffer, total_packets)
                    
                    # Оновлюємо статистику в app_state після успішного запису
                    app_state.parser_state['packets_total'] = total_packets
                    app_state.parser_state['packets_last_flush'] = len(packets_buffer)
                    app_state.parser_state['buffer_size'] = 0
                    
                    packets_buffer = []
                    last_flush_time = current_time
                
                # Оновлюємо поточний розмір буфера в app_state (для моніторингу)
                app_state.parser_state['buffer_size'] = len(packets_buffer)
                
            except ConnectionResetError as e:
                logger.error(f"[PARSER] Розрив з'єднання: {e}")
                reader, writer = None, None
                log_to_db(db_file, 'ERROR', 'PARSER', 'Розрив з\'єднання', str(e))
                # Записуємо накопичені пакети перед розривом
                if packets_buffer:
                    total_packets = await flush_packets(db_file, packets_buffer, total_packets)
                    packets_buffer = []
                continue
            
            except OSError as e:
                logger.error(f"[PARSER] Помилка мережі: {e}")
                reader, writer = None, None
                log_to_db(db_file, 'ERROR', 'PARSER', 'Помилка мережі', str(e)[:200])
                # Записуємо накопичені пакети перед розривом
                if packets_buffer:
                    total_packets = await flush_packets(db_file, packets_buffer, total_packets)
                    packets_buffer = []
                continue
            
            except Exception as e:
                logger.error(f"[PARSER] Помилка при читанні: {e}")
                reader, writer = None, None
                log_to_db(db_file, 'ERROR', 'PARSER', 'Помилка читання', str(e)[:200])
                # Записуємо накопичені пакети перед розривом
                if packets_buffer:
                    total_packets = await flush_packets(db_file, packets_buffer, total_packets)
                    packets_buffer = []
                continue
        
        except KeyboardInterrupt:
            logger.info("[PARSER] Цикл зупинений користувачем")
            # Записуємо накопичені пакети перед завершенням
            if packets_buffer:
                total_packets = await flush_packets(db_file, packets_buffer, total_packets)
            break
        
        except Exception as e:
            logger.error(f"[PARSER] Критична помилка циклу: {e}")
            log_to_db(db_file, 'ERROR', 'PARSER', 'Критична помилка', str(e)[:200])
            await asyncio.sleep(reconnect_delay)
    
    # Закриваємо з'єднання при завершенні
    if writer:
        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass
    
    logger.info("[PARSER] Парсер зупинений")
    log_to_db(db_file, 'INFO', 'PARSER', 'Парсер зупинений')
