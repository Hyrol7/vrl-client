#!/usr/bin/env python3
"""
test_time_sync.py - Комплексне тестування модуля time_sync.py

Тести покривають:
1. get_timezone_offset() - з pytz, zoneinfo, невалідний пояс
2. get_ntp_time() - при наявності ntplib, без нього
3. sync_system_time() - всі сценарії (NTP OK, NTP fail, HTTP fail тощо)

Використання:
    python test_time_sync.py
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from pathlib import Path

# Імпортуємо модуль для тестування
import time_sync


# ============================================================
# UNIT ТЕСТИ
# ============================================================

class TestTimezone(unittest.TestCase):
    """Тести для функцій часового поясу"""
    
    def test_get_timezone_offset_valid(self):
        """Тест: коректно отримуємо offset для валідного часового поясу"""
        offset = time_sync.get_timezone_offset('Europe/Kiev')
        
        # Europe/Kiev повинен мати позитивний offset
        self.assertIsInstance(offset, (int, float))
        self.assertGreater(offset, 0)
        print(f"✓ Europe/Kiev offset: {offset}s ({offset/3600}h)")
    
    def test_get_timezone_offset_utc(self):
        """Тест: UTC повинен мати offset 0"""
        offset = time_sync.get_timezone_offset('UTC')
        self.assertEqual(offset, 0)
        print(f"✓ UTC offset: {offset}s")
    
    def test_get_timezone_offset_invalid(self):
        """Тест: невалідний пояс повинен повернути 0"""
        offset = time_sync.get_timezone_offset('Invalid/Timezone')
        self.assertEqual(offset, 0)
        print(f"✓ Invalid timezone offset: {offset}s (default)")
    
    def test_get_timezone_offset_different_zones(self):
        """Тест: різні часові пояси мають різні offsets"""
        offset_kiev = time_sync.get_timezone_offset('Europe/Kiev')
        offset_london = time_sync.get_timezone_offset('Europe/London')
        offset_tokyo = time_sync.get_timezone_offset('Asia/Tokyo')
        
        # Вони повинні відрізнятися
        offsets = {offset_kiev, offset_london, offset_tokyo}
        self.assertGreater(len(offsets), 1)
        
        print(f"✓ Різні пояси:")
        print(f"  - Europe/Kiev: {offset_kiev}s")
        print(f"  - Europe/London: {offset_london}s")
        print(f"  - Asia/Tokyo: {offset_tokyo}s")


class TestNTPTime(unittest.TestCase):
    """Тести для функцій NTP"""
    
    def test_get_ntp_time_without_ntplib(self):
        """Тест: без ntplib повинен повернути (None, False)"""
        with patch.dict('sys.modules', {'ntplib': None}):
            result = time_sync.get_ntp_time()
            self.assertEqual(result, (None, False))
            print("✓ NTP без ntplib: (None, False)")
    
    def test_get_ntp_time_mocked_success(self):
        """Тест: имітуємо успішне отримання NTP часу"""
        mock_response = MagicMock()
        mock_response.tx_time = datetime.now().timestamp()
        
        with patch('ntplib.NTPClient') as mock_client:
            mock_instance = MagicMock()
            mock_instance.request.return_value = mock_response
            mock_client.return_value = mock_instance
            
            timestamp, success = time_sync.get_ntp_time()
            self.assertTrue(success)
            self.assertIsInstance(timestamp, float)
            print(f"✓ NTP успішно: timestamp={timestamp}, success={success}")
    
    def test_get_ntp_time_mocked_failure(self):
        """Тест: імітуємо помилку при отриманні NTP часу"""
        with patch('ntplib.NTPClient') as mock_client:
            mock_instance = MagicMock()
            mock_instance.request.side_effect = Exception("NTP timeout")
            mock_client.return_value = mock_instance
            
            timestamp, success = time_sync.get_ntp_time()
            self.assertFalse(success)
            self.assertIsNone(timestamp)
            print(f"✓ NTP помилка: timestamp={timestamp}, success={success}")


class TestSyncSystemTime(unittest.TestCase):
    """Тести для функції синхронізації часу"""
    
    def setUp(self):
        """Підготовка конфігурації для тестів"""
        self.config = {
            'app': {
                'name': 'VRL Client',
                'version': '0.1.0',
                'timezone': 'Europe/Kiev',
            },
            'decoder': {
                'host': '127.0.0.1',
                'port': 31003,
            },
            'api': {
                'url': 'http://localhost',
                'client_id': 1,
            },
        }
    
    def test_sync_system_time_ntp_ok_small_diff(self):
        """Тест: NTP доступен, різниця < 5 сек"""
        ntp_timestamp = datetime.now().timestamp()
        
        with patch('time_sync.get_ntp_time') as mock_ntp:
            mock_ntp.return_value = (ntp_timestamp, True)
            
            success, message = time_sync.sync_system_time(self.config)
            
            self.assertTrue(success)
            self.assertIn('актуальний', message.lower())
            print(f"✓ NTP OK (diff < 5s): success={success}, msg='{message}'")
    
    def test_sync_system_time_ntp_ok_large_diff(self):
        """Тест: NTP доступен, різниця > 5 сек (але системна синхронізація не працює)"""
        # Час 1 годину назад
        ntp_timestamp = (datetime.now() - timedelta(hours=1)).timestamp()
        
        with patch('time_sync.get_ntp_time') as mock_ntp:
            mock_ntp.return_value = (ntp_timestamp, True)
            
            # Симулюємо, що системна синхронізація не вдалася
            with patch('platform.system', return_value='UnknownOS'):
                success, message = time_sync.sync_system_time(self.config)
                
                self.assertFalse(success)
                self.assertIn('різниця', message.lower())
                print(f"✓ NTP OK але large diff: success={success}, msg='{message}'")
    
    def test_sync_system_time_ntp_fail_http_ok(self):
        """Тест: NTP не вдалася, HTTP fallback успішний"""
        with patch('time_sync.get_ntp_time') as mock_ntp:
            mock_ntp.return_value = (None, False)
            
            # Мокуємо HTTP запит
            with patch('urllib.request.urlopen') as mock_http:
                mock_response = MagicMock()
                now_iso = datetime.now().isoformat()
                mock_response.read.return_value = b'{"datetime": "' + now_iso.encode() + b'Z"}'
                mock_http.return_value = mock_response
                
                success, message = time_sync.sync_system_time(self.config)
                
                # HTTP fallback спробував, результат залежить від різниці часу
                print(f"✓ NTP fail, HTTP fallback: success={success}, msg='{message}'")
    
    def test_sync_system_time_all_fail(self):
        """Тест: NTP і HTTP обидва не вдалися"""
        with patch('time_sync.get_ntp_time') as mock_ntp:
            mock_ntp.return_value = (None, False)
            
            with patch('urllib.request.urlopen', side_effect=Exception("HTTP error")):
                success, message = time_sync.sync_system_time(self.config)
                
                self.assertFalse(success)
                self.assertIn('локальний', message.lower())
                print(f"✓ All methods fail: success={success}, msg='{message}'")


# ============================================================
# СЦЕНАРІЇВНІ ТЕСТИ (INTEGRATION)
# ============================================================

class TestTimeSyncScenarios(unittest.TestCase):
    """Тести для реальних сценаріїв"""
    
    def setUp(self):
        self.config = {
            'app': {
                'timezone': 'Europe/Kiev',
            },
            'decoder': {'host': '127.0.0.1', 'port': 31003},
            'api': {'url': 'http://localhost', 'client_id': 1},
        }
    
    def test_scenario_1_real_timezone_calculation(self):
        """СЦЕНАРІЙ 1: Реальний розрахунок часового поясу"""
        print("\n" + "="*60)
        print("СЦЕНАРІЙ 1: Розрахунок часового поясу")
        print("="*60)
        
        timezones = ['UTC', 'Europe/Kiev', 'Europe/London', 'America/New_York', 'Asia/Tokyo']
        
        for tz in timezones:
            offset = time_sync.get_timezone_offset(tz)
            hours = offset / 3600
            print(f"  {tz:20} → {offset:6.0f}s ({hours:+.1f}h)")
    
    def test_scenario_2_time_difference_detection(self):
        """СЦЕНАРІЙ 2: Виявлення різниці часу"""
        print("\n" + "="*60)
        print("СЦЕНАРІЙ 2: Виявлення різниці часу")
        print("="*60)
        
        test_cases = [
            ("Різниця < 1s", 0.5),
            ("Різниця 3s (OK)", 3),
            ("Різниця 5s (edge)", 5),
            ("Різниця 10s (alert)", 10),
            ("Різниця 1h (critical)", 3600),
        ]
        
        local_now = datetime.now()
        
        for description, diff_seconds in test_cases:
            ntp_time = (local_now - timedelta(seconds=diff_seconds)).timestamp()
            
            with patch('time_sync.get_ntp_time', return_value=(ntp_time, True)):
                success, message = time_sync.sync_system_time(self.config)
                
                status = "✓ СИНХРО" if success else "⚠ РІЗНИЦЯ"
                print(f"  {description:25} → {status}: {message}")


# ============================================================
# ТОЧКА ВХОДУ
# ============================================================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("КОМПЛЕКСНЕ ТЕСТУВАННЯ time_sync.py")
    print("="*60 + "\n")
    
    # Запускаємо unittest з повним выводом
    unittest.main(verbosity=2)
