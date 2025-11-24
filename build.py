#!/usr/bin/env python3
"""
build.py - Створення exe-файлу використовуючи PyInstaller

Встановіть:
    pip install pyinstaller
"""

import sys
import subprocess
import os
from pathlib import Path

def main():
    print("\n" + "="*60)
    print("BUILD vrl_client.exe")
    print("="*60 + "\n")
    
    # Перевіряємо наявність PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("❌ PyInstaller не встановлений!")
        print("   Встановіть: pip install pyinstaller")
        sys.exit(1)
    
    vrl_dir = Path(__file__).parent / "vrl_client"
    build_dir = Path(__file__).parent / "build"
    dist_dir = Path(__file__).parent / "dist"
    
    # Переходимо в директорію vrl_client
    os.chdir(vrl_dir)
    
    print(f"📁 Директорія: {vrl_dir}")
    print(f"📦 Вихід: {dist_dir}\n")
    
    # PyInstaller команда
    cmd = [
        "pyinstaller",
        "--onefile",
        "--name=vrl_client",
        "--add-data", f"config.yaml{os.pathsep}.",
        "--hidden-import=psutil",
        "--hidden-import=requests",
        "--hidden-import=yaml",
        f"--distpath={dist_dir}",
        f"--buildpath={build_dir}",
        "--clean",
        "vrl.py"
    ]
    
    print("🔨 Запускаємо PyInstaller...")
    print(f"   Команда: {' '.join(cmd)}\n")
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        exe_path = dist_dir / "vrl_client.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024*1024)
            print(f"\n✅ SUCCESS!")
            print(f"   📂 Файл: {exe_path}")
            print(f"   📊 Розмір: {size_mb:.1f} MB\n")
        else:
            print(f"\n⚠️  Файл не знайдений: {exe_path}")
            sys.exit(1)
    else:
        print(f"\n❌ ПОМИЛКА при компіляції (код: {result.returncode})")
        sys.exit(1)

if __name__ == "__main__":
    main()
