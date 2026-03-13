import unittest
import time
import sys
import numpy as np

# Ensure backend import path
sys.path.append('/Users/hashteelab/Documents/trae_projects/multiple_face_detection/backend')
import api  # noqa


class ChunkFinalizeFlowTest(unittest.TestCase):
    def setUp(self):
        # Reset in-memory structures
        try:
            api._chunks.clear()
        except Exception:
            api._chunks = api.deque(maxlen=40)
        api._store['items'] = []
        api._save_store()

        # Seed a pending chunk (non-finalized) with one detection
        self.cid = 'testcid123'
        rec = {
            'id': self.cid,
            'ts': time.time(),
            'college_id': '',
            'names': ['alice'],
            'thumbs': [''],
            'aug_thumbs': [[]],
            'portraits': [''],
            'image': '',
            'embeddings': [[1.0, 0.0, 0.0]],
            'boxes': [],
            'finalized': False
        }
        api._chunks.append(rec)

    def test_chunks_hidden_until_finalize(self):
        client = api.app.test_client()
        r = client.get('/chunks')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        # Should not list pending chunks
        self.assertEqual(len(data.get('items', [])), 0)

        # Finalize with provided names
        r2 = client.post('/finalize_chunk', json={'id': self.cid, 'names': ['alice']})
        self.assertEqual(r2.status_code, 200)
        resp2 = r2.get_json()
        self.assertTrue(resp2.get('ok'))
        # Now chunks endpoint should include the chunk
        r3 = client.get('/chunks')
        data3 = r3.get_json()
        self.assertGreaterEqual(len(data3.get('items', [])), 1)
        ids = [it.get('id') for it in data3.get('items', [])]
        self.assertIn(self.cid, ids)

    def test_finalize_merges_into_store(self):
        client = api.app.test_client()
        # Before finalize: search should find nothing
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        res0 = api._search(v, topk=1)
        self.assertEqual(len(res0), 0)
        # Finalize
        r = client.post('/finalize_chunk', json={'id': self.cid, 'names': ['alice']})
        self.assertEqual(r.status_code, 200)
        # After finalize: search should return 'alice'
        res1 = api._search(v, topk=1)
        self.assertGreaterEqual(len(res1), 1)
        self.assertEqual(res1[0]['name'], 'alice')


if __name__ == '__main__':
    unittest.main()

