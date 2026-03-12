import unittest
import numpy as np
import sys

# ensure module path
sys.path.append('/Users/hashteelab/Documents/trae_projects/multiple_face_detection/backend')
import api  # noqa


class StoreIndexDeletionTest(unittest.TestCase):
    def setUp(self):
        # ensure a SuperAdmin user for auth
        api._users['items'] = []
        salt = api.os.urandom(16)
        user = {
            'id': 'u1',
            'email': 'admin@example.com',
            'username': 'admin',
            'role': 'SuperAdmin',
            'college_id': '',
            'password_salt': salt.hex(),
            'password_hash': api._hash_password('pass', salt),
            'is_active': True
        }
        api._users.setdefault('items', []).append(user)
        # reset store with two simple labels
        api._store['items'] = [
            {'name': 'alice', 'vecs': [{'id': 'a1', 'v': [1.0, 0.0, 0.0]}], 'dim': 3, 'aug_vecs': []},
            {'name': 'bob', 'vecs': [{'1d': 'b1', 'v': [0.0, 1.0, 0.0]}] if False else [{'id': 'b1', 'v': [0.0, 1.0, 0.0]}], 'dim': 3, 'aug_vecs': []}
        ]
        api._save_store()

    def test_search_before_after_delete(self):
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        res = api._search(v, topk=1)
        self.assertTrue(len(res) >= 1)
        self.assertEqual(res[0]['name'], 'alice')
        # delete 'alice' via authenticated HTTP route
        client = api.app.test_client()
        # login to get token
        r_login = client.post('/auth_login', json={'email': 'admin@example.com', 'password': 'pass'})
        self.assertEqual(r_login.status_code, 200)
        tok = r_login.get_json().get('token')
        r = client.post('/delete_label', json={'name': 'alice'}, headers={'Authorization': f'Bearer {tok}'})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data.get('ok'))
        # search again should not return 'alice'
        res2 = api._search(v, topk=2)
        names = [x['name'] for x in res2]
        self.assertNotIn('alice', names)


if __name__ == '__main__':
    unittest.main()

