import re
import os

app_path = os.path.join(os.path.dirname(__file__), 'routes/auth.py')
with open(app_path, 'r') as f:
    content = f.read()

# Remove the top level import
content = re.sub(r'from app import get_db_connection, socketio, is_testing, ALL_FEATURES', '', content)

# Replace 'def login():' with 'def login():\n    from app import get_db_connection, socketio, is_testing, ALL_FEATURES'
content = content.replace('def login():', 'def login():\n    from app import get_db_connection, socketio, is_testing, ALL_FEATURES')
content = content.replace('def register_user():', 'def register_user():\n    from app import get_db_connection, socketio, is_testing, ALL_FEATURES')
content = content.replace('def register_parent():', 'def register_parent():\n    from app import get_db_connection, socketio, is_testing, ALL_FEATURES')
content = content.replace('def parent_login():', 'def parent_login():\n    from app import get_db_connection, socketio, is_testing, ALL_FEATURES')
content = content.replace('def parent_logout():', 'def parent_logout():\n    from app import get_db_connection, socketio, is_testing, ALL_FEATURES')
content = content.replace('def get_parent_attendance():', 'def get_parent_attendance():\n    from app import get_db_connection, socketio, is_testing, ALL_FEATURES')
content = content.replace('def parent_student_day():', 'def parent_student_day():\n    from app import get_db_connection, socketio, is_testing, ALL_FEATURES')
content = content.replace('def parent_select_student():', 'def parent_select_student():\n    from app import get_db_connection, socketio, is_testing, ALL_FEATURES')
content = content.replace('def logout():', 'def logout():\n    from app import get_db_connection, socketio, is_testing, ALL_FEATURES')

with open(app_path, 'w') as f:
    f.write(content)
