from app import app
import json
from routes.auth import generate_token_with_claims

# Generate a real parent token for testing
token = generate_token_with_claims('parent_3_kbtug20192', 'parent', {'sv': 1})
headers = {'Authorization': f'Bearer {token}'}

with app.test_client() as client:
    print('--- Testing /api/parents/lecture-attendance ---')
    r1 = client.get('/api/parents/lecture-attendance', headers=headers)
    print('STATUS:', r1.status_code)
    data1 = r1.get_json()
    if data1 and 'attendance' in data1 and len(data1['attendance']) > 0:
        print('FIRST RECORD DATE:', data1['attendance'][0].get('lecture_date'))
    else:
        print('NO ATTENDANCE RECORDS FOUND')

    print('\n--- Testing /api/parents/student-day ---')
    r2 = client.get('/api/parents/student-day', headers=headers)
    print('STATUS:', r2.status_code)
    data2 = r2.get_json()
    if data2 and 'student' in data2:
        print('STUDENT NAME:', data2['student'].get('name'))
    else:
        print('STUDENT DATA ERROR:', data2)
