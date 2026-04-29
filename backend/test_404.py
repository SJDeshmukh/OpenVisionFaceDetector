from app import app
with app.test_client() as client:
    resp = client.get('/non-existent')
    print('404 SIZE:', len(resp.get_data()))
    resp2 = client.get('/api/parents/lecture-attendance') # No auth should be 401
    print('401 SIZE:', len(resp2.get_data()))
