# Побудова EXE файлу

## Локальна побудова

### Вимоги
```bash
pip install pyinstaller pyyaml requests psutil
```

### Метод 1: Python скрипт
```bash
python3 build.py
```

Результат буде в `dist/vrl_client.exe`

### Метод 2: PyInstaller напряму
```bash
cd vrl_client
pyinstaller --onefile \
  --name=vrl_client \
  --add-data="config.yaml:." \
  --hidden-import=psutil \
  --hidden-import=requests \
  --hidden-import=yaml \
  vrl.py
```

## GitHub Actions побудова

### Опція 1: Через tag (автоматично)
```bash
git tag v1.0.0
git push origin v1.0.0
```

Це запустить workflow автоматично, створить Release та завантажить exe-файл.

### Опція 2: Ручний запуск
1. Перейдіть на вкладку **Actions** на GitHub
2. Виберіть **Build EXE** workflow
3. Клацніть **Run workflow**
4. Завантажити артефакт з сторінки запуску

## Структура виходу

```
dist/
├── vrl_client.exe          # Готовий до запуску файл
└── vrl_client/
    ├── config.yaml         # Конфігурація (включена в exe)
    ├── *.pyc              # Компільовані модулі Python
    └── ...
```

## Налаштування

### config.yaml всередині EXE
Файл `config.yaml` автоматично включається в `--add-data`. 
Він буде в тій же директорії, що й exe-файл.

### Розмір файлу
- Типовий розмір: 60-80 MB (з усіма залежностями)
- Запуск першого разу: 2-3 секунди (розпакування)
- Наступні запуски: <1 сек

## Отримання Release

### На GitHub
1. Перейдіть на **Releases** сторінку репозиторію
2. Знайдіть потрібну версію
3. Завантажте `vrl_client.exe`

### Через API
```bash
curl -L https://github.com/Hyrol7/vrl-client/releases/download/v1.0.0/vrl_client.exe -o vrl_client.exe
```

## Контроль версії

Версія зберігається в `vrl_client/initialization.py`:
```python
'version': '0.1.0',
```

Оновлюйте її перед кожним релізом та vytvor новий tag:
```bash
git tag v0.1.0
git push origin v0.1.0
```

## Як запустити exe-файл

1. **Windows Explorer**: подвійний клік на `vrl_client.exe`
2. **Командний рядок**: `.\vrl_client.exe`
3. **PowerShell**: `& '.\vrl_client.exe'`

## Поіб у Firewall

Якщо Windows Defender блокує файл:
1. Клацніть **More info** → **Run anyway**
2. Або додайте до whitelist в Windows Defender

## Усунення проблем

### Помилка: "File not found: config.yaml"
- config.yaml повинен бути в тій же директорії, що й exe
- Перевірте `--add-data` параметр у PyInstaller

### Помилка: "Module not found: psutil"
- Переконайтесь, що `--hidden-import=psutil` включений
- Встановіть локально: `pip install psutil`

### Велике розміру файлу (>150 MB)
- Використовуйте `--onefile` для одного файлу
- Розгляньте `UPX` для компресії (не завжди компатибільно)
