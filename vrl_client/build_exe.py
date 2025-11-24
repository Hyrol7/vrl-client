#!/usr/bin/env python3
"""
build_exe.py - Скрипт для збірки VRL Client в exe файл

Використання:
    python build_exe.py
    
Результат:
    dist/VRL_Client.exe
"""

import PyInstaller.__main__
import os
import sys
from pathlib import Path

def build_exe():
    """Збираємо exe файл з PyInstaller"""
    
    project_root = Path(__file__).parent
    vrl_py = project_root / 'vrl.py'
    dist_dir = project_root / 'dist'
    build_dir = project_root / 'build'
    spec_file = project_root / 'VRL_Client.spec'
    
    if not vrl_py.exists():
        print(f"❌ ПОМИЛКА: vrl.py не знайдений за адресою: {vrl_py}")
        sys.exit(1)
    
    print("=" * 60)
    print("🔨 ЗБІРКА VRL CLIENT EXE")
    print("=" * 60)
    print(f"\n📁 Проект:     {project_root}")
    print(f"📄 Скрипт:     {vrl_py}")
    print(f"📦 Результат:  {dist_dir}/VRL_Client.exe")
    print()
    
    # Параметри для PyInstaller
    args = [
        str(vrl_py),
        '--onefile',                    # Один файл exe
        '--console',                    # Показувати консоль
        '--name=VRL_Client',            # Назва exe
        f'--distpath={dist_dir}',       # Директорія для exe
        f'--buildpath={build_dir}',     # Директорія для проміжних файлів
        f'--specpath={project_root}',   # Директорія для spec файлу
        '--hidden-import=yaml',         # Явно включити yaml
        '--hidden-import=requests',     # Явно включити requests
        '--hidden-import=ntplib',       # Явно включити ntplib
        '--collect-all=yaml',
        '--collect-all=requests',
        '--collect-all=urllib3',
        '--collect-all=certifi',
        '--collect-all=chardet',
        '--collect-all=idna',
    ]
    
    print("🚀 Запуск PyInstaller...")
    print(f"   Параметри: {' '.join(args)}\n")
    
    try:
        PyInstaller.__main__.run(args)
        
        exe_path = dist_dir / 'VRL_Client.exe'
        
        if exe_path.exists():
            file_size_mb = exe_path.stat().st_size / (1024 * 1024)
            print("\n" + "=" * 60)
            print("✅ ЗБІРКА УСПІШНА!")
            print("=" * 60)
            print(f"\n📦 Файл:      {exe_path}")
            print(f"📊 Розмір:    {file_size_mb:.1f} МБ")
            print(f"✓ Статус:     Готовий до розповсюдження")
            print("\n💡 Наступні кроки:")
            print(f"   1. Тестувати: .\\dist\\VRL_Client.exe")
            print(f"   2. Завантажити на GitHub Releases")
            print(f"   3. Користувачи можуть завантажити exe")
            print()
            return True
        else:
            print(f"\n❌ ПОМИЛКА: EXE файл не створений!")
            return False
    
    except Exception as e:
        print(f"\n❌ ПОМИЛКА під час збірки: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = build_exe()
    sys.exit(0 if success else 1)
