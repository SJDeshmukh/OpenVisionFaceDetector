
import unittest
from datetime import datetime, timedelta
import sys
import os

# Add backend to path to import app logic if needed, 
# but here we will test calculate_daily_hours logic directly by copying/mocking it
# or importing if possible.
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app import calculate_daily_hours

class TestPayrollLogic(unittest.TestCase):
    
    def setUp(self):
        # Define some common activities
        self.timetable = [
            {
                "name": "Work",
                "type": "Work",
                "start_time": "09:00",
                "end_time": "18:00",
                "is_payable": True,
                "days": ["Mon", "Tue", "Wed", "Thu", "Fri"]
            },
            {
                "name": "Lunch Break",
                "type": "Break",
                "start_time": "13:00",
                "end_time": "14:00",
                "is_payable": False, # Unpaid
                "days": ["Mon", "Tue", "Wed", "Thu", "Fri"]
            },
            {
                "name": "Tea Break",
                "type": "Break",
                "start_time": "16:00",
                "end_time": "16:15",
                "is_payable": True, # Paid
                "days": ["Mon", "Tue", "Wed", "Thu", "Fri"]
            }
        ]

    def test_basic_work_day_no_breaks(self):
        records = [
            {"timestamp": "2023-10-27 09:00:00", "status": "CHECK_IN", "activity": "Work"},
            {"timestamp": "2023-10-27 18:00:00", "status": "CHECK_OUT", "activity": "Work"}
        ]
        stats = calculate_daily_hours(records, self.timetable)
        # 9 hours total.
        # Strict Check-In/Check-Out Logic: No automatic deductions for missing breaks.
        # If user didn't check out for lunch, they worked through it.
        self.assertEqual(stats['total_hours'], 9.0)

    def test_work_day_with_unpaid_gap(self):
        # Check In 9:00
        # Check Out 13:00 (Lunch)
        # Check In 14:00 (Resume)
        # Check Out 18:00 (End)
        records = [
            {"timestamp": "2023-10-27 09:00:00", "status": "CHECK_IN", "activity": "Work"},
            {"timestamp": "2023-10-27 13:00:00", "status": "CHECK_OUT", "activity": "Lunch Break"},
            {"timestamp": "2023-10-27 14:00:00", "status": "CHECK_IN", "activity": "Work"},
            {"timestamp": "2023-10-27 18:00:00", "status": "CHECK_OUT", "activity": "Work"}
        ]
        stats = calculate_daily_hours(records, self.timetable)
        
        # Session 1: 9-13 (4 hours)
        # Gap: 13-14 (1 hour). Last activity "Lunch Break". is_payable=False. Not added.
        # Session 2: 14-18 (4 hours)
        # Total: 8 hours.
        self.assertEqual(stats['total_hours'], 8.0)

    def test_work_day_with_paid_gap(self):
        # Check In 9:00
        # Check Out 16:00 (Tea)
        # Check In 16:15 (Resume)
        # Check Out 18:00 (End)
        # Assume Lunch was skipped (worked through).
        records = [
            {"timestamp": "2023-10-27 09:00:00", "status": "CHECK_IN", "activity": "Work"},
            {"timestamp": "2023-10-27 16:00:00", "status": "CHECK_OUT", "activity": "Tea Break"},
            {"timestamp": "2023-10-27 16:15:00", "status": "CHECK_IN", "activity": "Work"},
            {"timestamp": "2023-10-27 18:00:00", "status": "CHECK_OUT", "activity": "Work"}
        ]
        stats = calculate_daily_hours(records, self.timetable)
        
        # Session 1: 9-16 (7 hours)
        # Gap: 16:00-16:15 (0.25 hours). Last activity "Tea Break". is_payable=True.
        # BUT STRICT LOGIC says gaps are UNPAID.
        # Session 2: 16:15-18:00 (1.75 hours)
        # Total Raw: 7 + 0 + 1.75 = 8.75 hours.
        self.assertEqual(stats['total_hours'], 8.75)
        
        # Wait, if Tea Break is paid, shouldn't it be included?
        # Only if checked IN to Tea Break.

    def test_work_day_gap_after_work_is_not_payable(self):
        # Check In 9:00
        # Check Out 12:00 (Work - e.g. went home early)
        # Check In 14:00 (Came back)
        # Check Out 18:00
        records = [
            {"timestamp": "2023-10-27 09:00:00", "status": "CHECK_IN", "activity": "Work"},
            {"timestamp": "2023-10-27 12:00:00", "status": "CHECK_OUT", "activity": "Work"},
            {"timestamp": "2023-10-27 14:00:00", "status": "CHECK_IN", "activity": "Work"},
            {"timestamp": "2023-10-27 18:00:00", "status": "CHECK_OUT", "activity": "Work"}
        ]
        stats = calculate_daily_hours(records, self.timetable)
        
        # Session 1: 9-12 (3h)
        # Gap: 12-14 (2h). Unpaid.
        # Session 2: 14-18 (4h)
        # Total: 7h.
        self.assertEqual(stats['total_hours'], 7.0)

    def test_payable_break_explicit(self):
         # Test a gap that IS payable in theory but unpaid in strict mode.
         records = [
            {"timestamp": "2023-10-27 16:00:00", "status": "CHECK_IN", "activity": "Work"},
            {"timestamp": "2023-10-27 16:15:00", "status": "CHECK_OUT", "activity": "Tea Break"},
            {"timestamp": "2023-10-27 16:30:00", "status": "CHECK_IN", "activity": "Work"},
            {"timestamp": "2023-10-27 17:00:00", "status": "CHECK_OUT", "activity": "Work"}
        ]
         # Session 1: 16:00-16:15 (15m = 0.25h)
         # Gap: 15m (Unpaid per strict rules)
         # Session 2: 16:30-17:00 (30m = 0.5h)
         # Total: 0.75h.
         stats = calculate_daily_hours(records, self.timetable)
         self.assertEqual(stats['total_hours'], 0.75)

    def test_payable_gap_overshoot(self):
        # User checks out for Tea Break (Paid) but stays out overnight
        records = [
            {"timestamp": "2023-10-27 16:00:00", "status": "CHECK_IN", "activity": "Work"},
            {"timestamp": "2023-10-27 16:15:00", "status": "CHECK_OUT", "activity": "Tea Break"},
            # Next day check in
            {"timestamp": "2023-10-28 09:00:00", "status": "CHECK_IN", "activity": "Work"},
            {"timestamp": "2023-10-28 12:00:00", "status": "CHECK_OUT", "activity": "Work"}
        ]
        # Session 1: 15m (0.25h)
        # Gap: Unpaid.
        # Session 2: 3.0h
        # Total: 3.25h
        
        stats = calculate_daily_hours(records, self.timetable)
        # Check what it currently does
        print(f"Overshoot Total Hours: {stats['total_hours']}")
        
        self.assertEqual(stats['total_hours'], 3.25)


if __name__ == '__main__':
    unittest.main()
