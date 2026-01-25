from datetime import datetime
import random

def generate_greeting(name, status='CHECK_IN', context=None):
    """
    Generates a time-aware friendly greeting using local templates.
    Supports activity contexts: 'lunch', 'tea', 'end_of_day', etc.
    """
    now = datetime.now()
    hour = now.hour

    if 5 <= hour < 12:
        time_greeting = "Good morning"
    elif 12 <= hour < 17:
        time_greeting = "Good afternoon"
    elif 17 <= hour < 21:
        time_greeting = "Good evening"
    else:
        time_greeting = "Hello"

    # Context-Specific Greetings
    if context:
        if context == 'late_arrival' and status == 'CHECK_IN':
            return random.choice([
                f"{time_greeting} {name}, you are a bit late today.",
                f"Welcome {name}, please try to be on time.",
                f"Hello {name}, you have checked in late."
            ])
        elif context == 'leaving_for_lunch' and status == 'CHECK_OUT':
            return random.choice([
                f"Enjoy your lunch, {name}!",
                f"Have a good meal, {name}.",
                f"See you after lunch, {name}."
            ])
        elif context == 'returning_from_lunch' and status == 'CHECK_IN':
            return random.choice([
                f"Hope you enjoyed your lunch, {name}.",
                f"Welcome back from lunch, {name}.",
                f"Ready to get back to work, {name}?"
            ])
        elif context == 'leaving_for_tea' and status == 'CHECK_OUT':
            return random.choice([
                f"Enjoy your tea break, {name}.",
                f"Have a nice tea, {name}."
            ])
        elif context == 'returning_from_tea' and status == 'CHECK_IN':
            return random.choice([
                f"Welcome back from tea, {name}.",
                f"Refreshed after tea, {name}?"
            ])
        elif context == 'end_of_day' and status == 'CHECK_OUT':
            return random.choice([
                f"Good job today {name}, see you tomorrow.",
                f"Have a safe journey home, {name}.",
                f"Good night {name}, rest well."
            ])

    # Default Greetings
    if status == 'CHECK_IN':
        # Templates for Check-In
        templates = [
            f"{time_greeting} {name}, welcome back to Honda.",
            f"{time_greeting} {name}, good to see you.",
            f"Welcome back {name}, hope you have a great day.",
            f"{time_greeting} {name}, ready for the day?"
        ]
    else:
        # Templates for Check-Out
        templates = [
            f"{time_greeting} {name}, have a safe journey.",
            f"Goodbye {name}, see you tomorrow.",
            f"{time_greeting} {name}, take care.",
            f"Good job today {name}, see you soon."
        ]

    return random.choice(templates)
