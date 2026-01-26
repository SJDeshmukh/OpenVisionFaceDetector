import unittest
from datetime import datetime
from app import calculate_daily_hours

class TestAdvancedAttendanceLogic(unittest.TestCase):
    
    def test_multiple_gaps_mixed_payability(self):
        # Scenario: 
        # 1. Work (9:00-11:00) -> 2h.
        # 2. Tea Break (11:00-11:15, Payable). -> 0.25h.
        # 3. Work (11:15-13:00) -> 1.75h.
        # 4. Lunch (13:00-14:00, Not Payable). -> 0h.
        # 5. Work (14:00-17:00) -> 3h.
        # Total: 2 + 0.25 + 1.75 + 0 + 3 = 7.0 hours.
        
        timetable = [
            {'name': 'Work', 'type': 'Work', 'is_payable': True},
            {'name': 'TeaBreak', 'type': 'Break', 'is_payable': True, 'start_time': '11:00', 'end_time': '11:15'},
            {'name': 'Lunch', 'type': 'Break', 'is_payable': False, 'start_time': '13:00', 'end_time': '14:00'}
        ]
        
        records = [
            {'timestamp': '2023-10-27 09:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 11:00:00', 'status': 'CHECK_OUT', 'activity': 'TeaBreak'},
            {'timestamp': '2023-10-27 11:15:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 13:00:00', 'status': 'CHECK_OUT', 'activity': 'Lunch'},
            {'timestamp': '2023-10-27 14:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 17:00:00', 'status': 'CHECK_OUT', 'activity': 'Work'}
        ]
        
        stats = calculate_daily_hours(records, timetable)
        self.assertEqual(stats['total_hours'], 7.0, "Should handle mixed payable/unpayable gaps correctly")
        self.assertEqual(stats['total_hours_str'], "7h 0m")

    def test_gap_cap_enforcement(self):
        # Scenario: User takes a LONG Tea Break (Payable).
        # Tea Break scheduled: 15 mins.
        # Actual Break: 60 mins (11:00-12:00).
        # Payable Amount: Should be CAPPED at 15 mins (0.25h).
        # Work: 9-11 (2h), 12-17 (5h).
        # Total: 2 + 0.25 + 5 = 7.25 hours.
        
        timetable = [
            {'name': 'Work', 'type': 'Work', 'is_payable': True},
            {'name': 'TeaBreak', 'type': 'Break', 'is_payable': True, 'start_time': '11:00', 'end_time': '11:15'}
        ]
        
        records = [
            {'timestamp': '2023-10-27 09:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 11:00:00', 'status': 'CHECK_OUT', 'activity': 'TeaBreak'},
            {'timestamp': '2023-10-27 12:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 17:00:00', 'status': 'CHECK_OUT', 'activity': 'Work'}
        ]
        
        stats = calculate_daily_hours(records, timetable)
        self.assertEqual(stats['total_hours'], 7.25, "Should cap payable gap at scheduled duration")

    def test_gap_under_cap(self):
        # Scenario: User takes a SHORT Tea Break (Payable).
        # Tea Break scheduled: 15 mins.
        # Actual Break: 10 mins (11:00-11:10).
        # Payable Amount: Should be actual 10 mins (0.166...h).
        # Work: 9-11 (2h), 11:10-17 (5h 50m = 5.833h).
        # Total: 2 + 0.166 + 5.833 = 8.0 hours (actually 7h 60m = 8h).
        
        timetable = [
            {'name': 'Work', 'type': 'Work', 'is_payable': True},
            {'name': 'TeaBreak', 'type': 'Break', 'is_payable': True, 'start_time': '11:00', 'end_time': '11:15'}
        ]
        
        records = [
            {'timestamp': '2023-10-27 09:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 11:00:00', 'status': 'CHECK_OUT', 'activity': 'TeaBreak'},
            {'timestamp': '2023-10-27 11:10:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 17:00:00', 'status': 'CHECK_OUT', 'activity': 'Work'}
        ]
        
        stats = calculate_daily_hours(records, timetable)
        # 10 mins = 600s. 5h 50m = 21000s. 2h = 7200s. Total = 28800s = 8h.
        self.assertEqual(stats['total_hours'], 8.0, "Should pay actual duration if under cap")

    def test_overnight_gap_cap(self):
        # Scenario: User checks out for "Tea" (Payable 15m) at 11:00 PM and returns at 1:00 AM.
        # Gap: 2 hours. Cap: 15 mins.
        # Work: 20:00-23:00 (3h). 01:00-02:00 (1h).
        # Total: 3 + 0.25 + 1 = 4.25 hours.
        
        timetable = [
            {'name': 'NightWork', 'type': 'Work', 'is_payable': True},
            {'name': 'TeaBreak', 'type': 'Break', 'is_payable': True, 'start_time': '23:00', 'end_time': '23:15'}
        ]
        
        records = [
            {'timestamp': '2023-10-27 20:00:00', 'status': 'CHECK_IN', 'activity': 'NightWork'},
            {'timestamp': '2023-10-27 23:00:00', 'status': 'CHECK_OUT', 'activity': 'TeaBreak'},
            {'timestamp': '2023-10-28 01:00:00', 'status': 'CHECK_IN', 'activity': 'NightWork'},
            {'timestamp': '2023-10-28 02:00:00', 'status': 'CHECK_OUT', 'activity': 'NightWork'}
        ]
        
        stats = calculate_daily_hours(records, timetable)
        self.assertEqual(stats['total_hours'], 4.25, "Should cap overnight payable gap correctly")

    def test_no_timetable_strict(self):
        # Scenario: No timetable provided.
        # User Instruction: "payable hours calculated only when we register an activity with shift!"
        # So if 'Work' is not in timetable, it is NOT payable. Result should be 0.
        
        records = [
            {'timestamp': '2023-10-27 09:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 12:00:00', 'status': 'CHECK_OUT', 'activity': 'Break'},
            {'timestamp': '2023-10-27 13:00:00', 'status': 'CHECK_IN', 'activity': 'Work'},
            {'timestamp': '2023-10-27 17:00:00', 'status': 'CHECK_OUT', 'activity': 'Work'}
        ]
        
        stats = calculate_daily_hours(records, []) # Empty timetable
        self.assertEqual(stats['total_hours'], 0.0, "Should strictly exclude ALL hours if no timetable (activity not registered)")

    def test_unknown_activity_strict(self):
        # Scenario: Timetable has 'Work'. User logs 'RandomTask'.
        # Should be 0 hours for RandomTask.
        
        timetable = [{'name': 'Work', 'type': 'Work', 'is_payable': True}]
        
        records = [
            {'timestamp': '2023-10-27 09:00:00', 'status': 'CHECK_IN', 'activity': 'RandomTask'},
            {'timestamp': '2023-10-27 12:00:00', 'status': 'CHECK_OUT', 'activity': 'RandomTask'}
        ]
        
        stats = calculate_daily_hours(records, timetable)
        self.assertEqual(stats['total_hours'], 0.0, "Should exclude unknown activity not in timetable")

if __name__ == '__main__':
    unittest.main()
