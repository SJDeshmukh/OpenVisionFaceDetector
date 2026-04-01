import os
import re

directory = '.'

for filename in os.listdir(directory):
    if filename.endswith(".py") and (filename.startswith("test_") or filename == "app.py"):
        filepath = os.path.join(directory, filename)
        with open(filepath, 'r') as file:
            content = file.read()
            
        # Regex to find system_users table creation and add password_plain if missing
        if "CREATE TABLE IF NOT EXISTS system_users" in content:
            if "password_plain" not in content:
                # Replace 'password TEXT,' with 'password TEXT, password_plain TEXT,'
                # Also handle 'password TEXT NOT NULL,'
                content = re.sub(r'(password\s+TEXT(?:\s+NOT\s+NULL)?),', r'\1,\n            password_plain TEXT,\n            person_id INTEGER,\n            has_set_password INTEGER DEFAULT 0,', content)
                
                with open(filepath, 'w') as file:
                    file.write(content)
                print(f"Updated {filename}")
