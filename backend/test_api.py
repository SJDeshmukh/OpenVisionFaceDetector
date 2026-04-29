from app import app
from services.auth_service import generate_token_with_claims
import json

with app.test_client() as client:
    token = generate_token_with_claims('parent_3_kbtug20192', 'parent', {'sv': 1})
    headers = {'Authorization': f'Bearer {token}'}
    resp = client.get('/api/parents/lecture-attendance', headers=headers)
    print('STATUS:', resp.status_code)
    print('DATA:', resp.get_data(as_text=True))
