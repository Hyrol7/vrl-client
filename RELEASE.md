# Release та Deployment Посібник

## 🚀 Підготовка релізу

### 1. Оновлення версії

Відредагуйте `vrl_client/initialization.py`:

```python
DEFAULT_CONFIG = {
    'app': {
        'version': '0.2.0',  # ← Оновіть версію
        ...
    }
}
```

### 2. Оновлення CHANGELOG

Створіть/оновіть `CHANGELOG.md`:

```markdown
## [0.2.0] - 2025-11-24

### Added
- Нова фіча 1
- Нова фіча 2

### Fixed
- Баг 1 виправлений
- Баг 2 виправлений

### Changed
- Зміни в API
- Покращення производительности
```

### 3. Commit та Push

```bash
git add .
git commit -m "release: v0.2.0"
git push origin main
```

## 📦 Запуск на GitHub

### Автоматичний релиз через tag

```bash
# Створити tag
git tag v0.2.0

# Push tag на GitHub
git push origin v0.2.0
```

GitHub Actions автоматично:
1. Запуститься workflow `Build EXE`
2. Компілюватиме exe-файл на Windows
3. Створятиме Release з exe-файлом

### Ручний запуск

Якщо потрібен exe без релізу:

1. Перейдіть на вкладку **Actions**
2. Виберіть **Build EXE**
3. Клацніть **Run workflow**
4. Завантажте артефакт з `vrl_client-windows`

## 📥 Завантаження до GitHub Releases

### Через GitHub Web UI

1. Перейдіть на **Releases**
2. Клацніть **Draft a new release**
3. Виберіть tag (або створіть новий)
4. Заповніть title і description
5. Завантажте exe-файл
6. Клацніть **Publish release**

### Через GitHub CLI

```bash
# Встановіть gh CLI (якщо не встановлено)
# https://cli.github.com/

# Створіть release
gh release create v0.2.0 ./dist/vrl_client.exe \
  --title "Version 0.2.0" \
  --notes "See CHANGELOG for details"
```

### Через API

```bash
curl -X POST \
  -H "Authorization: token YOUR_GITHUB_TOKEN" \
  -H "Content-Type: application/json" \
  https://api.github.com/repos/Hyrol7/vrl-client/releases \
  -d '{
    "tag_name": "v0.2.0",
    "name": "Version 0.2.0",
    "body": "Release notes here",
    "draft": false,
    "prerelease": false
  }'
```

## 🔗 Посилання для користувачів

Після публікації, поділіться цими посиланнями:

### Прямо до exe-файлу

```
https://github.com/Hyrol7/vrl-client/releases/download/v0.2.0/vrl_client.exe
```

### Через Release сторінку

```
https://github.com/Hyrol7/vrl-client/releases/tag/v0.2.0
```

### Всі релізи

```
https://github.com/Hyrol7/vrl-client/releases
```

## 🛠️ Локальна побудова для тестування

```bash
# Встановіть PyInstaller
pip install pyinstaller

# Побудуйте exe
python build.py

# Протестуйте exe
dist/vrl_client.exe --help
```

## ✅ Чек-лист перед релізом

- [ ] Обновлена версія в `initialization.py`
- [ ] Обновлена документація (README, BUILD.md)
- [ ] CHANGELOG оновлен
- [ ] Локально протестований exe-файл
- [ ] Всі тести пройдені (`pytest` або `test_quick.py`)
- [ ] Git комітми мають значимі повідомлення
- [ ] Созданий tag з правильним форматом (`v X.Y.Z`)
- [ ] GitHub Actions успішно завершив побудову

## 🔄 Безперервний розвиток

### Налаштування автоматичного релізу

Додайте цей워크flow в `.github/workflows/release.yml`:

```yaml
name: Automatic Release

on:
  push:
    tags:
      - 'v*'

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Create Release Notes
        run: echo "Release ${{ github.ref }}" > release_notes.txt
      - name: Create Release
        uses: softprops/action-gh-release@v1
        with:
          files: dist/vrl_client.exe
          body_path: release_notes.txt
```

## 📊 Моніторинг завантажень

### Через GitHub API

```bash
curl https://api.github.com/repos/Hyrol7/vrl-client/releases/latest | jq .

# Вивід включатиме download_count для кожного assets
```

## 🐛 Гарячі фікси (Hotfix)

Якщо потрібна швидка виправка:

```bash
# Створіть гілку від main
git checkout -b hotfix/критичний-баг

# Виправте баг
# ...

# Commit
git commit -m "hotfix: Критичний баг в парсері"

# Tag
git tag v0.2.1

# Push
git push origin hotfix/критичний-баг
git push origin v0.2.1
```

## 📞 Поддержка

Користувачі можуть повідомити про проблеми через:
- GitHub Issues
- GitHub Discussions
- Email

Дякуємо за використання VRL Client! 🚀
