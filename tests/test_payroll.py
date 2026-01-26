
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
        # However, Lunch is Unpaid (13:00-14:00).
        # Logic in calculate_daily_hours (lines 2598+) DEDUCTS unpaid overlaps.
        # So 9 hours - 1 hour (Lunch) = 8 hours.
        self.assertEqual(stats['total_hours'], 8.0)

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
        # Overlap Deduction: 
        # Session 1 (9-13) overlaps Lunch (13-14)? No.
        # Session 2 (14-18) overlaps Lunch? No.
        # Deduction = 0.
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
        # Gap: 16:00-16:15 (0.25 hours). Last activity "Tea Break". is_payable=True. Added!
        # Session 2: 16:15-18:00 (1.75 hours)
        # Total Raw: 7 + 0.25 + 1.75 = 9.0 hours.
        
        # Overlap Deduction:
        # Lunch (13-14) is unpaid.
        # Session 1 (9-16) overlaps Lunch (13-14) by 1 hour.
        # Deduction = 1 hour.
        # Net Total: 9.0 - 1.0 = 8.0 hours.
        
        self.assertEqual(stats['total_hours'], 8.0)
        
        # Wait, if Tea Break is paid, shouldn't it be included?
        # Yes, it is included in the raw total (via Gap logic).
        # But Lunch is deducted because they worked through it (according to timestamps 9-16).
        # If they actually worked through lunch, they get paid for it?
        # NO. The system assumes unpaid breaks are MANDATORY deductions if they fall within "Work" sessions.
        # Line 2619: `if not is_payable: unpaid_acts.append(act)`
        # Line 2634: `if session.get('type') == 'Work' ...`
        # So if you work through unpaid lunch, you lose that hour. (Standard labor law compliance usually requires breaks or pays penalties, but here logic deducts).
        
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
        # Gap: 12-14 (2h). Last activity "Work". is_payable=False (hardcoded logic). Not added.
        # Session 2: 14-18 (4h)
        # Total Raw: 7h.
        # Overlap Deduction: Lunch (13-14).
        # Session 1 (9-12): No overlap.
        # Session 2 (14-18): No overlap.
        # Gap (12-14): Contains Lunch. But Gap is not a "Work Session", so deduction logic (which iterates sessions) ignores it.
        # Result: 7h.
        self.assertEqual(stats['total_hours'], 7.0)

    def test_payable_break_explicit(self):
         # Test a gap that IS payable and NO unpaid overlaps.
         records = [
            {"timestamp": "2023-10-27 16:00:00", "status": "CHECK_IN", "activity": "Work"},
            {"timestamp": "2023-10-27 16:15:00", "status": "CHECK_OUT", "activity": "Tea Break"},
            {"timestamp": "2023-10-27 16:30:00", "status": "CHECK_IN", "activity": "Work"},
            {"timestamp": "2023-10-27 17:00:00", "status": "CHECK_OUT", "activity": "Work"}
        ]
         # Tea Break is 16:00-16:15 in timetable.
         # Here user takes it 16:15-16:30.
         # Logic checks `last_checkout_activity` = "Tea Break".
         # Finds "Tea Break" in timetable. `is_payable` = True.
         # Adds gap (15 mins).
         
         # Session 1: 16:00-16:15 (15m)
         # Gap: 15m (Paid)
         # Session 2: 16:30-17:00 (30m)
         # Total: 60m = 1.0h.
         stats = calculate_daily_hours(records, self.timetable)
         self.assertEqual(stats['total_hours'], 1.0)

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
        # Gap: 16:15 to 09:00 next day (~16.75h).
        # Tea Break is payable.
        # If naive logic, it pays 16.75h.
        # Ideally, it should cap at Tea Break duration (15m) or max break duration?
        # Or maybe it shouldn't pay if it crosses midnight?
        
        stats = calculate_daily_hours(records, self.timetable)
        # Check what it currently does
        print(f"Overshoot Total Hours: {stats['total_hours']}")
        
        # With the fix, it should be capped at Tea Break duration (15m = 0.25h)
        # Session 1: 0.25h
        # Gap: 0.25h (Capped)
        # Session 2: 3.0h
        # Total: 3.5h
        self.assertEqual(stats['total_hours'], 3.5)


if __name__ == '__main__':
    unittest.main()
