import unittest
from datetime import datetime, timedelta
from app import calculate_daily_hours, calculate_arrival_status

class TestAttendanceLogic(unittest.TestCase):
    
    # --- Late Mark Tests ---
    
    def test_late_mark_basic(self):
        # Schedule: 9:00 AM Start, 15 min tolerance (via grace_period rule)
        expected_start = "09:00"
        day_activities = [{'start_time': '09:00', 'rules': {'grace_period': 15}}]
        
        # Case 1: On Time (9:15)
        sessions_ontime = [{'type': 'Work', 'start': '09:15', 'end': '12:00'}]
        status = calculate_arrival_status(expected_start, sessions_ontime, day_activities)
        self.assertEqual(status, "On Time", "9:15 should be On Time with 15m tolerance")
        
        # Case 2: Late (9:16)
        sessions_late = [{'type': 'Work', 'start': '09:16', 'end': '12:00'}]
        status = calculate_arrival_status(expected_start, sessions_late, day_activities)
        self.assertEqual(status, "Late", "9:16 should be Late with 15m tolerance")

    def test_late_mark_midnight_crossing(self):
        # Schedule: 11:00 PM Start (23:00), 15 min tolerance
        expected_start = "23:00"
        day_activities = [{'start_time': '23:00', 'rules': {'grace_period': 15}}]
    
        # Case 1: On Time (23:10)
        sessions_ontime = [{'type': 'Work', 'start': '23:10', 'end': '02:00'}]
        status = calculate_arrival_status(expected_start, sessions_ontime, day_activities)
        self.assertEqual(status, "On Time", "23:10 should be On Time for 23:00 start")
        
        # Case 2: Late (23:16)
        sessions_late = [{'type': 'Work', 'start': '23:16', 'end': '02:00'}]
        status = calculate_arrival_status(expected_start, sessions_late, day_activities)
        self.assertEqual(status, "Late", "23:16 should be Late for 23:00 start")

    def test_late_mark_midnight_boundary(self):
        # Schedule: 23:50 Start, 20 min tolerance (Up to 00:10 next day)
        expected_start = "23:50"
        day_activities = [{'start_time': '23:50', 'rules': {'grace_period': 20}}]
        
        # Case 1: Arrive 00:05 (Next Day) -> Should be On Time
        # The logic must handle the date rollover
        sessions_boundary = [{'type': 'Work', 'start': '00:05', 'end': '06:00'}]
        status = calculate_arrival_status(expected_start, sessions_boundary, day_activities)
        self.assertEqual(status, "On Time", "00:05 should be On Time for 23:50 start (within 20m)")
        
        # Case 2: Arrive 00:15 (Next Day) -> Late (25 mins)
        sessions_boundary_late = [{'type': 'Work', 'start': '00:15', 'end': '06:00'}]
        status = calculate_arrival_status(expected_start, sessions_boundary_late, day_activities)
        self.assertEqual(status, "Late", "00:15 should be Late for 23:50 start")

    # --- Payable Hours Tests ---

    def test_payable_hours_mixed(self):
        # Timetable
        timetable = [
            {'name': 'Work', 'type': 'Work', 'is_payable': True},
            {'name': 'Lunch', 'type': 'Break', 'is_payable': False},
            {'name': 'Meeting', 'type': 'Work', 'is_payable': True}
        ]
        
        # Records
        records = [
            {'timestamp': '2023-10-27 09:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 12:00:00', 'status': 'CHECK_OUT', 'activity': 'Work'}, # 3h
            {'timestamp': '2023-10-27 13:00:00', 'status': 'CHECK_IN', 'activity': 'Lunch'}, # Gap 12-13 (Not counted), Lunch 13-14 (Not payable)
            {'timestamp': '2023-10-27 14:00:00', 'status': 'CHECK_OUT', 'activity': 'Lunch'},
            {'timestamp': '2023-10-27 14:00:00', 'status': 'CHECK_IN', 'activity': 'Meeting'},
            {'timestamp': '2023-10-27 15:30:00', 'status': 'CHECK_OUT', 'activity': 'Meeting'} # 1.5h
        ]
        
        stats = calculate_daily_hours(records, timetable)
        self.assertEqual(stats['total_hours'], 4.5, "Should be 3h + 1.5h = 4.5h")
        self.assertEqual(stats['total_hours_str'], "4h 30m")

    def test_payable_hours_night_shift(self):
        # Timetable
        timetable = [{'name': 'NightWork', 'type': 'Work', 'is_payable': True}]
        
        # Records: 10 PM to 2 AM
        records = [
            {'timestamp': '2023-10-27 22:00:00', 'status': 'CHECK_IN', 'activity': 'NightWork'},
            {'timestamp': '2023-10-28 02:00:00', 'status': 'CHECK_OUT', 'activity': 'NightWork'}
        ]
        
        stats = calculate_daily_hours(records, timetable)
        self.assertEqual(stats['total_hours'], 4.0, "Should handle overnight shift correctly")
        self.assertEqual(stats['total_hours_str'], "4h 0m")

    # --- Real-Time Sync Tests ---

    def test_real_time_hours_active(self):
        # Timetable
        timetable = [{'name': 'Work', 'type': 'Work', 'is_payable': True}]
        
        now = datetime.now()
        start_time = now - timedelta(hours=2, minutes=30)
        
        records = [
            {'timestamp': start_time.strftime('%Y-%m-%d %H:%M:%S'), 'status': 'CHECK_IN', 'activity': 'Work'}
        ]
        
        today_str = now.strftime('%Y-%m-%d')
        stats = calculate_daily_hours(records, timetable, date_str=today_str)
        
        # Expect ~2.5 hours
        self.assertTrue(2.49 <= stats['total_hours'] <= 2.51, f"Expected ~2.5h, got {stats['total_hours']}")
        self.assertEqual(stats['total_hours_str'], "2h 30m")
        self.assertTrue(stats['is_active'])

    def test_real_time_hours_active_non_payable(self):
        # Timetable
        timetable = [{'name': 'Break', 'type': 'Break', 'is_payable': False}]
        
        now = datetime.now()
        start_time = now - timedelta(hours=1)
        
        records = [
            {'timestamp': start_time.strftime('%Y-%m-%d %H:%M:%S'), 'status': 'CHECK_IN', 'activity': 'Break'}
        ]
        
        today_str = now.strftime('%Y-%m-%d')
        stats = calculate_daily_hours(records, timetable, date_str=today_str)
        
        # Expect 0 hours (Not Payable)
        self.assertEqual(stats['total_hours'], 0.0, "Active non-payable session should count as 0 hours")
        self.assertEqual(stats['total_hours_str'], "0h 0m")
        self.assertTrue(stats['is_active'])

    def test_payable_hours_work_through_lunch(self):
        # Scenario: User works 9-5 straight. Lunch is 1-2 (Unpaid) in timetable.
        # Expected: 8 hours pay (since they didn't check out).
        
        # Timetable
        timetable = [
            {'name': 'Work', 'type': 'Work', 'is_payable': True, 'start_time': '09:00', 'end_time': '17:00', 'days': ['Fri']},
            {'name': 'Lunch', 'type': 'Break', 'is_payable': False, 'start_time': '13:00', 'end_time': '14:00', 'days': ['Fri']}
        ]
        
        # Records: Check In 9:00, Check Out 17:00 (No Lunch Check Out)
        records = [
            {'timestamp': '2023-10-27 09:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 17:00:00', 'status': 'CHECK_OUT', 'activity': 'Work'}
        ]
        
        stats = calculate_daily_hours(records, timetable)
        self.assertEqual(stats['total_hours'], 8.0, "Should count full 8h if user worked through lunch")
        self.assertEqual(stats['total_hours_str'], "8h 0m")

    def test_payable_hours_taken_lunch(self):
        # Scenario: User works 9-5 but takes Lunch 1-2.
        # Expected: 7 hours pay.
        
        timetable = [
            {'name': 'Work', 'type': 'Work', 'is_payable': True},
            {'name': 'Lunch', 'type': 'Break', 'is_payable': False}
        ]
        
        records = [
            {'timestamp': '2023-10-27 09:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 13:00:00', 'status': 'CHECK_OUT', 'activity': 'Work'}, # 4h
            {'timestamp': '2023-10-27 14:00:00', 'status': 'CHECK_IN', 'activity': 'Work'}, # Gap 13-14 ignored
            {'timestamp': '2023-10-27 17:00:00', 'status': 'CHECK_OUT', 'activity': 'Work'} # 3h
        ]
        
        stats = calculate_daily_hours(records, timetable)
        self.assertEqual(stats['total_hours'], 7.0, "Should count 7h (4+3)")
        self.assertEqual(stats['total_hours_str'], "7h 0m")

    def test_duplicate_checkin(self):
        # Scenario: IN (9:00), IN (10:00), OUT (11:00).
        # Should be 9:00 to 11:00 = 2 hours. Intermediate IN ignored.
        timetable = [{'name': 'Work', 'type': 'Work', 'is_payable': True}]
        records = [
            {'timestamp': '2023-10-27 09:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 10:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 11:00:00', 'status': 'CHECK_OUT', 'activity': 'Work'}
        ]
        stats = calculate_daily_hours(records, timetable)
        self.assertEqual(stats['total_hours'], 2.0, "Should handle duplicate check-ins")

    def test_orphaned_checkout(self):
        # Scenario: OUT (9:00) without prior IN. Should be 0 hours.
        records = [
            {'timestamp': '2023-10-27 09:00:00', 'status': 'CHECK_OUT', 'activity': 'Work'}
        ]
        stats = calculate_daily_hours(records, [])
        self.assertEqual(stats['total_hours'], 0.0, "Should ignore orphaned checkout")

    def test_gap_payable_logic(self):
        # Scenario: Work 9-12. TeaBreak 12-12:15 (Payable). Work 12:15-17.
        # User Checks OUT for TeaBreak, then IN for Work.
        timetable = [
            {'name': 'Work', 'type': 'Work', 'is_payable': True},
            {'name': 'TeaBreak', 'type': 'Break', 'is_payable': True, 'start_time': '12:00', 'end_time': '12:15'}
        ]
        records = [
            {'timestamp': '2023-10-27 09:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 12:00:00', 'status': 'CHECK_OUT', 'activity': 'TeaBreak'},
            {'timestamp': '2023-10-27 12:15:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 17:00:00', 'status': 'CHECK_OUT', 'activity': 'Work'}
        ]
        # Session 1: 3h. Gap: 0.25h (Strictly NOT Payable). Session 2: 4.75h. Total: 7.75h.
        stats = calculate_daily_hours(records, timetable)
        self.assertEqual(stats['total_hours'], 7.75, "Gap should NOT be payable in strict mode")

    def test_gap_not_payable_logic(self):
        # Scenario: Work 9-12. Lunch 12-1 (Not Payable). Work 1-5.
        timetable = [
            {'name': 'Work', 'type': 'Work', 'is_payable': True},
            {'name': 'Lunch', 'type': 'Break', 'is_payable': False}
        ]
        records = [
            {'timestamp': '2023-10-27 09:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 12:00:00', 'status': 'CHECK_OUT', 'activity': 'Lunch'},
            {'timestamp': '2023-10-27 13:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 17:00:00', 'status': 'CHECK_OUT', 'activity': 'Work'}
        ]
        # Session 1: 3h. Gap: 1h (Unpaid). Session 2: 4h. Total: 7h.
        stats = calculate_daily_hours(records, timetable)
        self.assertEqual(stats['total_hours'], 7.0, "Should exclude unpaid gap")

if __name__ == '__main__':
    unittest.main()
