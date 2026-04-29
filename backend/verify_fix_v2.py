from app import app
import json
from routes.auth import generate_token_with_claims

# Testing with the corrected username
token = generate_token_with_claims('parent_1_kbtug20192', 'parent', {'sv': 1})
headers = {'Authorization': f'Bearer {token}'}

with app.test_client() as client:
    print('--- Testing /api/parents/lecture-attendance ---')
    r1 = client.get('/api/parents/lecture-attendance', headers=headers)
    print('STATUS:', r1.status_code)
    data1 = r1.get_json()
    print('DATA:', data1)

    print('\n--- Testing /api/parents/student-day ---')
    r2 = client.get('/api/parents/student-day', headers=headers)
    print('STATUS:', r2.status_code)
    data2 = r2.get_json()
    print('DATA:', data2)
