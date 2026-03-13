import numpy as np
from backend import api

def make_vec(seed, dim=512):
    rng = np.random.RandomState(seed)
    v = rng.randn(dim).astype(np.float32)
    v /= np.linalg.norm(v) + 1e-8
    return v

def snapshot():
    return [(it['name'], len(it.get('vecs', [])), len(it.get('aug_vecs', []))) for it in api._store['items']]

def main():
    api._store['items'] = []
    a1 = make_vec(1)
    a2 = make_vec(2)
    b1 = make_vec(100)
    api._store['items'].append({'name': 'bhau', 'vec': a1.tolist(), 'vecs': [a1.tolist()], 'dim': 512, 'thumb': '', 'aug_thumbs': [], 'aug_vecs': []})
    api._store['items'].append({'name': 'bhau', 'vec': a2.tolist(), 'vecs': [a2.tolist()], 'dim': 512, 'thumb': '', 'aug_thumbs': [], 'aug_vecs': []})
    api._store['items'].append({'name': 'sudhanshu', 'vec': b1.tolist(), 'vecs': [b1.tolist()], 'dim': 512, 'thumb': '', 'aug_thumbs': [], 'aug_vecs': []})
    print('Initial:', snapshot())
    with api.app.test_client() as c:
        rv = c.post('/rename_label', json={'old': 'bhau', 'new': 'sudhanshu', 'vector': a1.tolist()})
        assert rv.status_code == 200, rv.data
    print('After rename bhau->sudhanshu using a1:', snapshot())
    names = [it['name'] for it in api._store['items']]
    assert names.count('bhau') == 1, 'Expected one remaining bhau'
    assert names.count('sudhanshu') == 1, 'Expected one sudhanshu'
    sud = [it for it in api._store['items'] if it['name'] == 'sudhanshu'][0]
    assert len(sud.get('vecs', [])) >= 2, 'Destination should gain the sample'
    bhau = [it for it in api._store['items'] if it['name'] == 'bhau'][0]
    assert len(bhau.get('vecs', [])) >= 1, 'Source should retain remaining samples'
    # test search prefers sudhanshu for a1
    res = api._search(np.array(a1, dtype=np.float32), topk=1)
    print('Search for a1 ->', res)
    assert res and res[0]['name'] == 'sudhanshu', 'Search must return sudhanshu'
    print('OK')

if __name__ == '__main__':
    main()
