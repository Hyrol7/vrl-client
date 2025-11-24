# VRL Client — Архітектура та Документація

## 📋 Загальна архітектура

VRL Client — це асинхронна система обробки авіаційних даних в реальному часі. Система складається з 8 модулів, які працюють паралельно, координуючись через SQLite БД.

```
┌─────────────────────────────────────────────────────────────────┐
│                         VRL Client v0.1.0                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  main (vrl.py) ─ ORCHESTRATOR ─ координує всі модулі            │
│      │                                                          │
│      ├─ [1] initialization.py ─ залежності, конфіг, БД        │
│      ├─ [2] time_sync.py ─ синхронізація часу                 │
│      ├─ [3] decoder.py ─ запуск декодера (subprocess)         │
│      ├─ [4] tcp_connection.py ─ перевірка TCP підключення     │
│      │                                                          │
│      └─ ФОНОВІ МОДУЛІ (asyncio.gather):                        │
│         ├─► ping_handler.py (ping_loop) ─ 30s інтервал        │
│         ├─► parser.py (parser_loop) ─ TCP reader → packets    │
│         ├─► analyser.py (analyser_loop) ─ K1↔K2 біндинг       │
│         └─► sender.py (sender_loop) ─ відправка на API        │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                     SQLite БД (base.db)                         │
│   ┌──────────────┬──────────────┬──────────────┐               │
│   │ packets_raw  │flight_tracks │    logs      │               │
│   │ (K1/K2)      │ (біндені)    │ (аудит)      │               │
│   └──────────────┴──────────────┴──────────────┘               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Послідовність ініціалізації (Blocking)

### ЕТАП 0-5: Послідовна ініціалізація ✅

```python
# vrl.py → main()
0. check_dependencies() → [PyYAML, requests, ntplib?]
1. load_config() → config.yaml (або створюємо новий)
2. init_database() → base.db (схема + таблиці)
3. sync_system_time() → NTP/HTTP/system time sync
4. start_decoder() → subprocess decoder.exe
5. wait_for_decoder_connection() → TCP 127.0.0.1:31003 (макс 10 спроб)

✓ Успіх → переходимо до ЕТАПУ 6
✗ Помилка → exit(1) з логуванням
```

### ЕТАП 6+: Асинхронні фонові модулі (Non-blocking)

```python
# Стартують одночасно після успішної ініціалізації
asyncio.gather(
    ping_loop(config, db_file),       # ping на API (30s)
    parser_loop(config, db_file),     # читає TCP від декодера
    analyser_loop(config, db_file),   # біндить K1↔K2
    sender_loop(config, db_file),     # відправляє на API
)
```

---

## 📡 Модулі та функції

### 1️⃣ **initialization.py** — Ініціалізація (306 рядків)

**Функції:**
- `check_dependencies()` — Перевіряємо обов'язкові + опціональні пакети
- `load_config()` — Завантажуємо конфіг або створюємо новий
- `init_database(config)` — Ініціалізуємо БД зі схемою
- `log_to_db(db_file, level, component, message, details)` — Логуємо в БД

**Таблиці БД:**

```sql
packets_raw:
├─ id (int, PK)
├─ event_time (text) — часова мітка з декодера
├─ type (int) — 1=K1 (позивний), 2=K2 (висота)
├─ callsign (text) — позивний літака (K1)
├─ height (int) — висота в метрах (K2)
├─ fuel (int) — паливо у % (K2)
├─ alarm, faithfulness (int)
├─ sent (int) — 0=чекає, 1=надіслано, -1=помилка
├─ bound_to_track (int) — FK до flight_tracks
└─ created_at, updated_at (timestamps)

flight_tracks:
├─ id (int, PK)
├─ k1_packet_id (int, FK) — позивний
├─ k2_packet_id (int, FK) — висота
├─ callsign (text)
├─ height, fuel (int)
├─ timestamp (text)
├─ sent (int) — 0=чекає, 1=надіслано, -1=помилка
├─ sent_at, error (text)
└─ created_at (timestamp)

logs:
├─ id (int, PK)
├─ level (text) — INFO/WARNING/ERROR
├─ component (text) — MAIN/PARSER/ANALYSER/SENDER/etc
├─ message (text)
├─ details (text) — JSON деталі
└─ created_at (timestamp)
```

---

### 2️⃣ **time_sync.py** — Синхронізація часу (189 рядків)

**Функції:**
- `get_timezone_offset(timezone_str)` → UTC offset (години)
- `get_ntp_time()` → час з NTP сервера (якщо ntplib доступна)
- `sync_system_time(config)` → Синхронізація з fallback:

**Fallback стратегія:**
```
1. Спробуємо NTP (якщо ntplib встановлена)
2. Якщо NTP недоступна → HTTP (worldtimeapi.org)
3. Якщо нема інтернету → система sync (w32tm, sntp, timedatectl)
4. Якщо все не вдалося → використовуємо локальний час + offset
```

**Платформна підтримка:**
- Windows: `w32tm /resync`
- macOS: `sntp -sS ntp.ubuntu.com`
- Linux: `timedatectl set-ntp true`

---

### 3️⃣ **decoder.py** — Управління декодером (80+ рядків)

**Функції:**
- `start_decoder(config, db_file)` → Запускаємо subprocess
- `stop_decoder(process)` → Закриваємо з timeout=5s

**Параметри:**
```python
command = f"{config['decoder']['executable']} {config['decoder']['command_args']}"
# Приклад: "/path/to/uvd_rtl.exe /tcp"
```

---

### 4️⃣ **tcp_connection.py** — Перевірка TCP (80+ рядків)

**Функції:**
- `check_tcp_port(host, port)` → Socket check (синхронна)
- `wait_for_decoder_connection(config, db_file)` → Async с retry

**Логіка:**
```python
max_attempts = 10
delay = 5s
timeout = 10s

Спроба 1-10:
└─► check_tcp_port() → 127.0.0.1:31003
    ├─ Успіх → return True
    ├─ Помилка → sleep(5s) → retry
    └─ Timeout → sleep(5s) → retry
```

---

### 5️⃣ **ping_handler.py** — Периодичний ping (180+ рядків)

**Класи:**
- `PingStatus` — State management (stages dict, tcp_connected, etc)

**Функції:**
- `generate_status_ping(status)` → JSON payload
- `send_status_ping(config, payload)` → POST + HMAC подпись
- `ping_loop(status, db_file)` → Infinite loop (30s інтервал)

**Payload структура:**
```json
{
    "client_id": 1,
    "version": "0.1.0",
    "stages": {
        "dependencies": true,
        "config": true,
        "database": true,
        "time_sync": true,
        "decoder": true,
        "tcp_connection": true
    },
    "tcp_connected": true,
    "uptime": 12345.67,
    "system_info": "Darwin-20.6.0"
}
```

**Безпека:**
- HMAC-SHA256 підпис (secret_key)
- Bearer token auth
- X-Signature заголовок

---

### 6️⃣ **parser.py** — Парсинг TCP даних (288 рядків)

**Регулярні вирази (Regex):**

```python
K1_PATTERN = r'^K1\s+(\d{2}):(\d{2}):(\d{2})\.(\d+)\.(\d+)\s+.*?:(\d+)$'
# Формат: K1 11:11:38.370.366 [ 8832] {018} **** :10437
#         ↓  ↓   ↓  ↓  ↓    ↓                        ↓
#         K1 hh mm ss ms μs                    callsign

K2_PATTERN = r'^K2\s+(\d{2}):(\d{2}):(\d{2})\.(\d+)\.(\d+)\s+.*?FL\s*(\d+)m.*?F:(\d+)%'
# Формат: K2 11:12:54.082.632 [ 8706] {017} **** FL 5360m [F176]+ F:40%
#         ↓  ↓   ↓  ↓  ↓    ↓                     ↓            ↓
#         K2 hh mm ss ms μs                  height           fuel
```

**Функції:**
- `connect_to_decoder(config)` → TCP client (asyncio)
- `parse_line(line)` → Розпізнаємо K1 або K2
- `parse_k1_packet(line)` → Витягуємо позивний
- `parse_k2_packet(line)` → Витягуємо висоту та паливо
- `save_packet_to_db(db_file, packet)` → INSERT в packets_raw
- `parser_loop(config, db_file)` → Main async loop

**Структура пакету K1:**
```python
{
    'event_time': 'YYYY-MM-DD HH:MM:SS',
    'type': 1,
    'callsign': '10437',
    'height': None,
    'fuel': None,
    'alarm': 0,
    'faithfulness': 50
}
```

**Структура пакету K2:**
```python
{
    'event_time': 'YYYY-MM-DD HH:MM:SS',
    'type': 2,
    'callsign': None,
    'height': 5360,
    'fuel': 40,
    'alarm': 0,
    'faithfulness': 0
}
```

**Логіка:**
```
Цикл:
1. connect_to_decoder() → TCP 127.0.0.1:31003
2. reader.read(4096) → буферизуємо дані
3. split('\n') → розбиваємо на рядки
4. parse_line() → K1 або K2
5. save_packet_to_db() → INSERT
6. reconnect_delay якщо помилка
```

---

### 7️⃣ **analyser.py** — Біндинг K1↔K2 (230+ рядків)

**Алгоритм біндингу:**

```
Для кожного K1 пакету:
1. Отримуємо його час: k1_time
2. Ищемо K2 пакети в діапазоні: [k1_time - 5s, k1_time + 5s]
3. Вибираємо K2 з мінімальною часовою різницею
4. Створюємо flight_track (FK: k1_packet_id, k2_packet_id)
5. Позначаємо пакети як пов'язані (bound_to_track)

TIME_WINDOW = 5 секунд (макс різниця часу)
```

**Функції:**
- `match_k1_k2_packets(db_file, k1_packets, k2_packets)` → Біндинг
- `create_flight_track()` → INSERT в flight_tracks
- `get_unmatched_packets()` → SELECT K1 + K2 (sent=0)
- `analyser_loop(config, db_file)` → Main async loop

**Приклад:**
```
K1 10:44:40.708 [ 8832] :10437  → k1_time = 10:44:40
K2 10:44:42.065 [ 8706] FL5360m → k2_time = 10:44:42
Δt = 2.357s < 5s ✓

→ flight_track створено:
  callsign: 10437
  height: 5360m
  fuel: ?%
  sent: 0
```

---

### 8️⃣ **sender.py** — Передача на API (280+ рядків)

**Функції:**
- `generate_hmac_signature(data, secret_key)` → HMAC-SHA256
- `get_pending_tracks(db_file, limit)` → SELECT flight_tracks (sent=0)
- `send_tracks_to_api(config, db_file, tracks)` → POST з HMAC
- `mark_tracks_as_sent(db_file, track_ids)` → UPDATE sent=1
- `sender_loop(config, db_file)` → Main async loop

**API Endpoint:**
```
POST /api/tracks
Content-Type: application/json
Authorization: Bearer YOUR_BEARER_TOKEN
X-Signature: HMAC_SHA256_SIGNATURE

{
    "client_id": 1,
    "tracks": [
        {
            "callsign": "10437",
            "height": 5360,
            "fuel": 40,
            "timestamp": "2025-11-24T10:44:42.000Z"
        },
        ...
    ]
}
```

**Безпека:**
```
1. HMAC-SHA256 підпис: hmac.new(secret_key, payload_json)
2. Base64 кодування підпису
3. Bearer token в Authorization заголовку
4. HTTPS з timeout=10s
```

**Логіка retry:**
```
Для кожного batch:
1. get_pending_tracks() → макс 100 за раз
2. send_tracks_to_api() → POST
   ├─ 200 OK → mark_tracks_as_sent(sent=1)
   ├─ 4xx → mark_tracks_as_failed(sent=-1)
   └─ 5xx → retry за RETRY_DELAY
3. sleep(sender_interval) → 10s
```

---

### 9️⃣ **vrl.py** — Оркестратор (230 рядків)

**Глобальний стан:**
```python
class AppState:
    decoder_process: Process
    db_file: str
    config: dict
    ping_status: PingStatus
```

**Сигнал обробка:**
```python
signal.signal(signal.SIGINT, signal_handler)
# Ctrl+C → stop_decoder() → exit(0)
```

**Основна логіка:**
```python
async def main():
    # Послідовна ініціалізація
    check_dependencies()
    config = load_config()
    db_file = init_database(config)
    sync_system_time(config)
    decoder_process = start_decoder(config, db_file)
    await wait_for_decoder_connection(config, db_file)
    
    # Запуск фонових модулів
    tasks = [
        ping_loop(config, db_file),
        parser_loop(config, db_file),
        analyser_loop(config, db_file),
        sender_loop(config, db_file),
    ]
    
    await asyncio.gather(*tasks)
```

---

## 📊 Потік даних

```
Decoder (subprocess)
    │
    └─► TCP 127.0.0.1:31003
            │
            ↓ parser.py
        packets_raw table
        ├─ K1: callsign
        └─ K2: height, fuel
            │
            ↓ analyser.py (K1↔K2 біндинг, Δt ≤ 5s)
        flight_tracks table
        ├─ k1_packet_id → callsign
        ├─ k2_packet_id → height
        └─ sent = 0 (чекає)
            │
            ↓ sender.py
        API Server
        ├─ POST /api/tracks
        ├─ HMAC-SHA256 підпис
        └─ sent = 1 (успішно)
```

---

## ⚙️ Конфігурація (config.yaml)

```yaml
app:
  name: VRL Client
  version: 0.1.0
  timezone: Europe/Kiev  # Для локальної синхронізації

decoder:
  executable: /path/to/uvd_rtl.exe
  command_args: /tcp
  host: 127.0.0.1
  port: 31003
  timeout: 10
  reconnect_delay: 5

api:
  url: https://skybind.pp.ua/vrl_api/ingest.php
  status_url: https://skybind.pp.ua/vrl_api/status.php
  client_id: 1
  secret_key: your-secret-key-here
  bearer_token: your-bearer-token-here
  timeout: 30
  ping_interval: 30

database:
  file: base.db

cycles:
  parser_interval: 0.1      # сек (читаємо часто)
  analyser_interval: 5      # сек (оброблюємо раз на 5с)
  sender_interval: 10       # сек (відправляємо раз на 10с)
  connectivity_check: 5     # сек
  ntp_sync_interval: 3600   # 1 година
  batch_size: 1000          # макс записів за раз
```

---

## 🧪 Тестування

### Тестування парсера:
```bash
cd /Users/oleksandr/Desktop/api/vrl_client
python3 parser.py
```

**Очікуваний результат:**
```
✓ K1 11:11:38.370.366 [ 8832] {018} **** :10437
  → {..., 'callsign': '10437', 'type': 1}

✓ K2 11:12:54.082.632 [ 8706] {017} **** FL 5360m [F176]+ F:40%
  → {..., 'height': 5360, 'fuel': 40, 'type': 2}
```

### Запуск VRL Client:
```bash
python3 vrl.py
```

**Очікуваний вихід:**
```
[...] INFO: ЕТАП 0: ПЕРЕВІРКА ЗАЛЕЖНОСТЕЙ
[...] INFO:   ✓ PyYAML
[...] INFO:   ✓ requests
[...] INFO: ЕТАП 1: ЗАВАНТАЖЕННЯ КОНФІГУРАЦІЇ
[...] INFO:   ✓ config.yaml завантажена
[...] INFO: ЕТАП 2: ІНІЦІАЛІЗАЦІЯ БД
[...] INFO:   ✓ base.db ініціалізована
[...] INFO: ЕТАП 3: СИНХРОНІЗАЦІЯ ЧАСУ
[...] INFO:   ✓ Час синхронізований
[...] INFO: ЕТАП 4: ЗАПУСК ДЕКОДЕРА
[...] INFO:   ✓ Декодер запущений
[...] INFO: ЕТАП 5: ОЧІКУВАННЯ TCP ПІДКЛЮЧЕННЯ
[...] INFO:   ✓ TCP підключено
[...] INFO: ІНІЦІАЛІЗАЦІЯ ЗАВЕРШЕНА УСПІШНО
[...] INFO: [PING] Запуск ping loop...
[...] INFO: [PARSER] Запуск парсера...
[...] INFO: [ANALYSER] Запуск аналізатора...
[...] INFO: [SENDER] Запуск sender...
```

---

## 🔐 Безпека

### HMAC-SHA256 підпис:
```python
import hmac
import hashlib
import base64

# Payload JSON (sorted keys)
payload_json = '{"client_id":1,"tracks":[...]}'

# Генеруємо підпис
signature = base64.b64encode(
    hmac.new(secret_key.encode(), payload_json.encode(), hashlib.sha256).digest()
).decode()

# Відправляємо в заголовку
headers['X-Signature'] = signature
```

### Bearer token:
```
Authorization: Bearer YOUR_BEARER_TOKEN
```

### HTTPS:
```
Всі запити на API мають бути HTTPS (перехід автоматичний)
```

---

## 📈 Масштабованість

### Batch обробка:
- `batch_size: 1000` — обробляємо до 1000 пакетів за раз
- Паралельна обробка через asyncio

### Асинхронність:
- Всі модулі (ping, parser, analyser, sender) працюють паралельно
- Кожний має свій інтервал (не блокують один одного)

### База даних:
- SQLite для простоти (локально на клієнті)
- Можна міграціювати на PostgreSQL у майбутньому
- Індекси на `event_time`, `callsign` для швидкості

---

## 🚀 Розгортання

### Вимоги:
- Python 3.8+ (якщо запускати з вихідного коду)
- Або просто `vrl.exe` (готова бінарна)

### Встановлення залежностей:
```bash
pip install PyYAML requests ntplib
```

### Запуск:
```bash
python3 vrl.py
# або
vrl.exe  # (скомпільована версія)
```

### Оновлення:
1. Завантажити нову версію `vrl.exe` з GitHub Releases
2. Замінити старий exe на новий
3. Перезапустити
4. Файли `config.yaml` та `base.db` збережуться!

---

## 📝 Версія

- **Версія:** 0.1.0
- **Статус:** Alpha (активна розробка)
- **Останнє оновлення:** 2025-11-24
- **Останній коміт:** 0c78647

---

## 📚 Посилання

- GitHub: https://github.com/Hyrol7/vrl-client
- API Docs: https://skybind.pp.ua/vrl_api/
- Ліцензія: MIT
