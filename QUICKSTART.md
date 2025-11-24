# 🚀 ШВИДКИЙ СТАРТ: VRL Client

## Для користувачів (Windows)

### 1️⃣ Завантаження

1. Перейти на https://github.com/YOUR_USERNAME/vrl-client/releases
2. Завантажити останній `VRL_Client.exe`
3. Зберегти на комп'ютер (наприклад, `C:\VRL_Client\`)

### 2️⃣ Перший запуск

1. Запустити `VRL_Client.exe` подвійним кліком
2. На екрані побачите:
```
═════════════════════════════════════════════════════════════
ЕТАП 0: ПЕРЕВІРКА ЗАЛЕЖНОСТЕЙ
...
```
3. Програма завершиться з повідомленням:
```
✓ config.yaml створена за адресою: C:\VRL_Client\config.yaml
⚠ УВАГА: Відредагуйте config.yaml перед повторним запуском!
```

### 3️⃣ Конфігурація

Відкрити файл `config.yaml` в будь-якому текстовому редакторі (Notepad, VS Code, тощо):

```yaml
decoder:
  executable: 'C:\path\to\uvd_rtl.exe'    ← Вставити шлях до декодера
  command_args: '/tcp'
  host: '127.0.0.1'
  port: 31003

api:
  url: 'https://your-server.com/api/ingest.php'
  status_url: 'https://your-server.com/api/status.php'
  client_id: 1                            ← Ваш client ID
  secret_key: 'your-secret-key'           ← Ваш secret key
  bearer_token: 'your-bearer-token'       ← Ваш bearer token
  ping_interval: 30
```

**Обов'язково встановити:**
- `decoder.executable` - шлях до uvd_rtl.exe
- `api.client_id`, `api.secret_key`, `api.bearer_token`

### 4️⃣ Другий запуск

Запустити `VRL_Client.exe` знову. На цей раз всі системи запустяться:

```
═════════════════════════════════════════════════════════════
ЕТАП 0: ПЕРЕВІРКА ЗАЛЕЖНОСТЕЙ
✓ PyYAML
✓ requests
✓ Всі залежності встановлені

ЕТАП 1: СИНХРОНІЗАЦІЯ ЧАСУ
✓ Час синхронізований (різниця < 5с)

ЕТАП 2: ЗАВАНТАЖЕННЯ КОНФІГУРАЦІЇ
✓ config.yaml завантажена успішно

ЕТАП 3: ІНІЦІАЛІЗАЦІЯ БАЗИ ДАНИХ
✓ БД ініціалізована: C:\VRL_Client\base.db

ЕТАП 4: ЗАПУСК ДЕКОДЕРА
✓ Декодер запущений (PID: 12345)

ЕТАП 5: ОЧІКУВАННЯ ПІДКЛЮЧЕННЯ ДО ДЕКОДЕРА
✓ TCP підключення встановлено (127.0.0.1:31003)

ЕТАП 6: ПЕРЕВІРКА ОСНОВНИХ МОДУЛІВ
✓ parser.py
✓ analyser.py
✓ sender.py

═════════════════════════════════════════════════════════════
✅ ІНІЦІАЛІЗАЦІЯ ЗАВЕРШЕНА УСПІШНО
═════════════════════════════════════════════════════════════

✓ Залежності:      OK
✓ Синхронізація часу: Час актуальний
✓ Конфігурація:    OK
✓ БД:              OK
✓ Декодер:         Running (PID: 12345)
✓ TCP підключення: Connected to 127.0.0.1:31003
✓ Модулі:          OK

Для завершення натисніть: Ctrl+C
```

Все готово! 🎉

### 5️⃣ Оновлення

Коли вийде нова версія:

1. Завантажити нову `VRL_Client.exe` з GitHub Releases
2. Замінити старий файл
3. Запустити новий exe
4. Конфіг та база даних збережеться

---

## Для розробників (Python)

### Установка

```bash
# 1. Клонувати репозиторій
git clone https://github.com/YOUR_USERNAME/vrl-client.git
cd vrl-client

# 2. Створити віртуальне оточення
python -m venv venv
venv\Scripts\activate  # Windows

# 3. Встановити залежності
pip install -r vrl_client/requirements.txt

# 4. Запустити
python vrl_client/vrl.py
```

### Розробка

```bash
# Редагувати файли
vim vrl_client/parser.py

# Тестувати
python vrl_client/vrl.py

# Commit та push
git add vrl_client/
git commit -m "Add new feature"
git push origin main

# Release (створює exe автоматично)
git tag v1.0.1
git push origin v1.0.1
```

### Локальна збірка exe

```bash
cd vrl_client
pip install pyinstaller
python build_exe.py

# Результат: dist/VRL_Client.exe
```

---

## 🆘 Рішення проблем

### Проблема: "Декодер не знайдений"

**Рішення:**
1. Перевірте шлях до `uvd_rtl.exe` в `config.yaml`
2. Переконайтесь, що файл існує та виконуваний
3. Спробуйте абсолютний шлях: `C:\Program Files\Decoder\uvd_rtl.exe`

### Проблема: "TCP підключення не встановлено"

**Рішення:**
1. Перевірте, чи декодер запущений окремо
2. Перевірте порт: `netstat -an | findstr 31003`
3. Спробуйте запустити декодер вручну
4. Перевірте firewall

### Проблема: "API error 401"

**Рішення:**
1. Перевірте `client_id`, `secret_key`, `bearer_token`
2. Переконайтесь, що ключі актуальні
3. Перевірте API URL

### Проблема: "Час синхронізації не вдалася"

**Рішення:**
1. На Windows потребує прав адміністратора для w32tm
2. Перевірте інтернет з'єднання
3. Перевірте NTP сервер (за замовчуванням pool.ntp.org)

---

## 📊 Перегляд логів

###查看 SQLite БД

```bash
# Windows PowerShell
sqlite3 C:\VRL_Client\base.db "SELECT * FROM logs ORDER BY created_at DESC LIMIT 20;"
```

### Або використати GUI

Download DB Browser for SQLite: https://sqlitebrowser.org/

---

## 🔗 Посилання

- **GitHub Repository:** https://github.com/YOUR_USERNAME/vrl-client
- **Releases:** https://github.com/YOUR_USERNAME/vrl-client/releases
- **Issues:** https://github.com/YOUR_USERNAME/vrl-client/issues
- **README:** https://github.com/YOUR_USERNAME/vrl-client#readme

---

## 📞 Підтримка

Якщо щось не працює:
1. Перевірте логи в базі даних
2. Створите issue на GitHub
3. Напишіть детальний опис проблеми

---

**Версія:** 1.0.0  
**Останнє оновлення:** Листопад 2025
