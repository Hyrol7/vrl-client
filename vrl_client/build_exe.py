#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_exe.py - Script for building VRL Client exe file

Usage:
    python build_exe.py
    
Result:
    dist/VRL_Client.exe
"""

import PyInstaller.__main__
import os
import sys
from pathlib import Path
import io

def build_exe():
    """Build exe file with PyInstaller"""
    
    # Force UTF-8 output on Windows
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    project_root = Path(__file__).parent
    vrl_py = project_root / 'vrl.py'
    dist_dir = project_root / 'dist'
    build_dir = project_root / 'build'
    spec_file = project_root / 'VRL_Client.spec'
    
    if not vrl_py.exists():
        print(f"[ERROR] vrl.py not found at: {vrl_py}")
        sys.exit(1)
    
    print("=" * 60)
    print("BUILD VRL CLIENT EXE")
    print("=" * 60)
    print(f"\nProject:      {project_root}")
    print(f"Script:       {vrl_py}")
    print(f"Output:       {dist_dir}/VRL_Client.exe")
    print()
    
    # PyInstaller parameters
    args = [
        str(vrl_py),
        '--onefile',                    # Single exe file
        '--console',                    # Show console
        '--name=VRL_Client',            # exe name
        f'--distpath={dist_dir}',       # exe directory
        f'--workpath={build_dir}',      # temp directory
        f'--specpath={project_root}',   # spec file directory
        '--hidden-import=yaml',         # Include yaml
        '--hidden-import=requests',     # Include requests
        '--hidden-import=ntplib',       # Include ntplib
        '--collect-all=yaml',
        '--collect-all=requests',
        '--collect-all=urllib3',
        '--collect-all=certifi',
        '--collect-all=chardet',
        '--collect-all=idna',
    ]
    
    print("Running PyInstaller...")
    print(f"Parameters: {' '.join(args[:5])}...\n")
    
    try:
        PyInstaller.__main__.run(args)
        
        exe_path = dist_dir / 'VRL_Client.exe'
        
        if exe_path.exists():
            file_size_mb = exe_path.stat().st_size / (1024 * 1024)
            print("\n" + "=" * 60)
            print("SUCCESS!")
            print("=" * 60)
            print(f"\nFile:         {exe_path}")
            print(f"Size:         {file_size_mb:.1f} MB")
            print(f"Status:       Ready for distribution")
            print("\nNext steps:")
            print(f"  1. Test: .\\dist\\VRL_Client.exe")
            print(f"  2. Upload to GitHub Releases")
            print(f"  3. Users can download exe")
            print()
            return True
        else:
            print(f"\n[ERROR] EXE file not created!")
            return False
    
    except Exception as e:
        print(f"\n[ERROR] Build failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = build_exe()
    sys.exit(0 if success else 1)
