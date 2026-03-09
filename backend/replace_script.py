import re
import os

app_path = os.path.join(os.path.dirname(__file__), 'app.py')
with open(app_path, 'r') as f:
    content = f.read()

# Remove login
content = re.sub(r'@greeting_bp\.route\("/auth/login".*?def login\(\):.*?(?=@greeting_bp\.route|# ---)', '', content, flags=re.DOTALL)

# Remove register_user
content = re.sub(r'@greeting_bp\.route\("/auth/register".*?def register_user\(\):.*?(?=@greeting_bp\.route|# ---)', '', content, flags=re.DOTALL)

# Remove register_parent
content = re.sub(r'@greeting_bp\.route\("/parents/register".*?def register_parent\(\):.*?(?=@greeting_bp\.route|# ---)', '', content, flags=re.DOTALL)

# Remove parent_login
content = re.sub(r'@greeting_bp\.route\("/parents/login".*?def parent_login\(\):.*?(?=@greeting_bp\.route|# ---)', '', content, flags=re.DOTALL)

# Remove parent_logout
content = re.sub(r'@greeting_bp\.route\("/parents/logout".*?def parent_logout\(\):.*?(?=@greeting_bp\.route|# ---)', '', content, flags=re.DOTALL)

# Remove parent_student_day
content = re.sub(r'@greeting_bp\.route\("/parents/student-day".*?def parent_student_day\(\):.*?(?=@greeting_bp\.route|# ---)', '', content, flags=re.DOTALL)

# Remove get_parent_attendance
content = re.sub(r'@greeting_bp\.route\("/parents/attendance".*?def get_parent_attendance\(\):.*?(?=@greeting_bp\.route|# ---)', '', content, flags=re.DOTALL)

# Remove parent_select_student
content = re.sub(r'@greeting_bp\.route\("/parents/select-student".*?def parent_select_student\(\):.*?(?=@greeting_bp\.route|# ---)', '', content, flags=re.DOTALL)


with open(app_path, 'w') as f:
    f.write(content)
