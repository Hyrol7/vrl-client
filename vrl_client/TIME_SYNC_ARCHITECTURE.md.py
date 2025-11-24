#!/usr/bin/env python3
"""
TIME_SYNC_ARCHITECTURE.md - Архітектура синхронізації часу

ПИТАННЯ: Куди ми записуємо різницю часу?

ВІДПОВІДЬ: На кількох рівнях

═════════════════════════════════════════════════════════════
РІВЕНЬ 1: ЛОГУВАННЯ В КОНСОЛЬ (при запуску)
═════════════════════════════════════════════════════════════

Коли користувач запускає програму:

    [2025-11-24 14:30:45,123] INFO: ЕТАП: СИНХРОНІЗАЦІЯ ЧАСУ
    [2025-11-24 14:30:45,150] INFO: Локальний час: 2025-11-24T14:30:45.123456
    [2025-11-24 14:30:45,200] INFO: Часовий пояс: Europe/Kiev
    [2025-11-24 14:30:45,300] INFO: NTP час (UTC): 2025-11-24T12:30:40.000000
    [2025-11-24 14:30:45,350] INFO: ⚠ Різниця: 5.1 сек
    [2025-11-24 14:30:45,400] INFO: ✓ Час синхронізований через w32tm

КУДИ: Консоль (stdout) + система логування Python


═════════════════════════════════════════════════════════════
РІВЕНЬ 2: БД ЛОГІВ (для аналізу)
═════════════════════════════════════════════════════════════

Після синхронізації записуємо в SQLite logs таблицю:

    INSERT INTO logs (level, component, message, details, created_at)
    VALUES (
        'INFO',                                    ← level
        'TIME_SYNC',                               ← component
        'Час синхронізований через w32tm',         ← message
        '{"diff_seconds": 5.1, "ntp_server": "pool.ntp.org", "method": "w32tm"}',
        CURRENT_TIMESTAMP                          ← created_at
    )

КУДИ: /Users/oleksandr/Desktop/api/vrl_client/base.db → logs таблиця


═════════════════════════════════════════════════════════════
РІВЕНЬ 3: PING СТАТУС (періодичні оновлення)
═════════════════════════════════════════════════════════════

При відправці ping на API сервер (кожні 30 сек):

{
    "client_id": 1,
    "version": "0.1.0",
    "timestamp": "2025-11-24T12:30:45Z",
    "uptime_seconds": 3600,
    "stages": {
        "dependencies": true,
        "time_sync": true,              ← статус синхронізації
        "config": true,
        "database": true,
        "decoder": true,
        "tcp_connection": true
    },
    "messages": {
        "dependencies": "OK",
        "time_sync": "Синхронізовано (diff: 5.1s)",   ← повідомлення з різницею
        ...
    },
    "system": {
        "platform": "Windows",
        "python_version": "3.11.0"
    }
}

КУДИ: API сервер (https://skybind.pp.ua/vrl_api/status.php)


═════════════════════════════════════════════════════════════
РІВЕНЬ 4: КОНФІГ З ОФСЕТОМ (runtime)
═════════════════════════════════════════════════════════════

Під час запису даних від декодера (при парсингу K1/K2):

Якщо різниця часу > 5 сек і синхронізація не вдалася, то:

    packet_time_from_decoder = 11:11:38  (локальний час декодера)
    
    timezone_offset = +2h (Europe/Kiev)
    time_diff_offset = +5.1s (різниця NTP-Local)
    
    corrected_time = packet_time_from_decoder + timezone_offset + time_diff_offset
                   = 11:11:38 + 2h + 5.1s
                   = 13:11:43.1 (UTC)

КУДИ: packets_raw таблиця (при вставці, враховується офсет)


═════════════════════════════════════════════════════════════
СТРУКТУРА БД ДЛЯ ЗБЕРІГАННЯ
═════════════════════════════════════════════════════════════

CREATE TABLE logs (
    id INTEGER PRIMARY KEY,
    level TEXT,              ← 'INFO', 'WARNING', 'ERROR'
    component TEXT,          ← 'TIME_SYNC', 'DECODER', 'PARSER', тощо
    message TEXT,            ← основне повідомлення
    details TEXT,            ← JSON з додатковою інформацією
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ПРИКЛАДИ ЗАПИСІВ:

Запис 1: Успішна синхронізація
┌────┬────────────┬───────────┬──────────────────────────┬────────────────────────────┐
│ id │ level      │ component │ message                  │ details                    │
├────┼────────────┼───────────┼──────────────────────────┼────────────────────────────┤
│ 42 │ 'INFO'     │ 'TIME'    │ 'Синхронізовано'         │ {"diff": 0.5, "method":... │
└────┴────────────┴───────────┴──────────────────────────┴────────────────────────────┘

Запис 2: Помилка синхронізації
┌────┬────────────┬───────────┬────────────────────────────┬──────────────────────────┐
│ id │ level      │ component │ message                    │ details                  │
├────┼────────────┼───────────┼────────────────────────────┼──────────────────────────┤
│ 43 │ 'WARNING'  │ 'TIME'    │ 'Різниця часу: 10.5 сек' │ {"diff": 10.5, "ntp":... │
└────┴────────────┴───────────┴────────────────────────────┴──────────────────────────┘


═════════════════════════════════════════════════════════════
МОДИФІКОВАНА ФУНКЦІЯ sync_system_time()
═════════════════════════════════════════════════════════════

Поточна реалізація в time_sync.py:

    def sync_system_time(config):
        # ... отримуємо NTP/HTTP час
        # ... порівнюємо з локальним
        # ... пробуємо синхронізувати систему
        
        return (success, message)

ЩО ПОТРІБНО ДОДАТИ:

1. Повертати також diff_seconds:
    return (success, message, diff_seconds, method)

2. Логувати в БД (після ініціалізації):
    log_to_db(db_file, 'INFO', 'TIME_SYNC', message, json.dumps({
        'diff_seconds': diff_seconds,
        'method': method,
        'timezone': timezone_str,
        'ntp_server': 'pool.ntp.org'
    }))

3. Зберігати в AppState для ping:
    app_state.time_sync_diff = diff_seconds
    app_state.time_sync_message = message


═════════════════════════════════════════════════════════════
ПРАКТИЧНІ СЦЕНАРІЇ
═════════════════════════════════════════════════════════════

СЦЕНАРІЙ 1: Все ОК (diff < 1s)
────────────────────────────────
[Console]    ✓ Час синхронізований (різниця < 5с)
[DB logs]    INSERT ... 'INFO', 'TIME_SYNC', 'OK', {'diff': 0.3}
[API ping]   "time_sync": "OK (diff: 0.3s)"
[Decoder]    Використовуємо локальний час як є


СЦЕНАРІЙ 2: Синхронізація пройшла (diff > 5s, але виправлено)
──────────────────────────────────────────────────────────────
[Console]    ✓ Час синхронізований через w32tm
[DB logs]    INSERT ... 'INFO', 'TIME_SYNC', 'Synced via w32tm', {'diff': 7.2, 'method': 'w32tm'}
[API ping]   "time_sync": "Synced (was: 7.2s)"
[Decoder]    Використовуємо локальний час (вже синхронізований)


СЦЕНАРІЙ 3: Синхронізація не вдалася (diff > 5s, manual fix needed)
───────────────────────────────────────────────────────────────────
[Console]    ⚠ Різниця: 10.5 сек — враховуємо пояс
[DB logs]    INSERT ... 'WARNING', 'TIME_SYNC', 'Manual sync needed', {'diff': 10.5}
[API ping]   "time_sync": "Manual sync needed (diff: 10.5s)"
[Decoder]    Додаємо офсет при обробці даних: time = decoder_time + 10.5s


СЦЕНАРІЙ 4: Інтернету немає (NTP/HTTP не доступні)
──────────────────────────────────────────────────
[Console]    ⚠ Будемо використовувати локальний час
[DB logs]    INSERT ... 'WARNING', 'TIME_SYNC', 'No internet', {'diff': null, 'reason': 'offline'}
[API ping]   "time_sync": "Offline mode (using local)"
[Decoder]    Використовуємо локальний час (на виск користувача)


═════════════════════════════════════════════════════════════
ЗАПИТ ДО БД ДЛЯ АНАЛІЗУ ЧАСОВОЇ СИНХРОНІЗАЦІЇ
═════════════════════════════════════════════════════════════

# Переглянути останні 10 спроб синхронізації:
sqlite3 base.db "
SELECT 
    created_at,
    level,
    message,
    details
FROM logs
WHERE component = 'TIME_SYNC'
ORDER BY created_at DESC
LIMIT 10;
"

# Визуалізувати тренд різниці часу:
sqlite3 base.db "
SELECT 
    created_at,
    json_extract(details, '$.diff_seconds') as diff,
    message
FROM logs
WHERE component = 'TIME_SYNC'
ORDER BY created_at;
"


═════════════════════════════════════════════════════════════
МОДИФІКАЦІЯ: Додавання log_to_db в time_sync.py
═════════════════════════════════════════════════════════════

Поточна проблема: time_sync.py не знає про db_file

Рішення 1: Передавати db_file як параметр
────────────────────────────────────────────
def sync_system_time(config, db_file=None):
    # ... синхронізація
    
    if db_file:
        from initialization import log_to_db
        log_to_db(db_file, 'INFO', 'TIME_SYNC', message, 
                  json.dumps({'diff': diff, 'method': method}))


Рішення 2: Повертати дані, логування робить vrl.py
──────────────────────────────────────────────────────
def sync_system_time(config):
    # ... синхронізація
    
    return {
        'success': True,
        'message': 'Синхронізовано',
        'diff_seconds': 5.1,
        'method': 'w32tm',
        'timestamp': datetime.now(),
    }

# У vrl.py:
time_info = sync_system_time(config)
log_to_db(db_file, 'INFO', 'TIME_SYNC', time_info['message'], 
          json.dumps(time_info))


═════════════════════════════════════════════════════════════
РЕКОМЕНДАЦІЯ
═════════════════════════════════════════════════════════════

Використати РІШЕННЯ 2, оскільки:
1. time_sync.py залишається чистим (не залежить від БД)
2. vrl.py отримує повну інформацію для логування
3. Легше тестувати time_sync.py окремо
4. AppState може зберігати diff для ping'у

"""

if __name__ == '__main__':
    print(__doc__)
