import io
import base64
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import numpy as np
import cv2
import os
import app as detect_app
import json
import numpy.typing as npt
from collections import deque
import time
import uuid
import logging
import hmac
import hashlib
import threading
from flask import g

app = Flask(__name__)
_allowed_origins = [origin.strip() for origin in os.getenv('CORS_ALLOWED_ORIGINS', 'http://localhost:5173').split(',') if origin.strip()]
CORS(app, origins=_allowed_origins, supports_credentials=True)
app.logger.setLevel(logging.INFO)
try:
    import faiss as _faiss
except Exception:
    _faiss = None
if str(os.getenv('DISABLE_FAISS', '0')).strip() in ('1', 'true', 'True'):
    _faiss = None
FAISS_NLIST = int(os.getenv('FAISS_NLIST', '0'))
FAISS_NPROBE = int(os.getenv('FAISS_NPROBE', '10'))
FAISS_HNSW_M = int(os.getenv('FAISS_HNSW_M', '32'))
FAISS_CAND_K = int(os.getenv('FAISS_CAND_K', '256'))
try:
    import mediapipe as mp
    _mp_face_mesh = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, refine_landmarks=True)
except Exception:
    _mp_face_mesh = None
try:
    import onnxruntime as ort
    _minifasnet_path = os.getenv('MINIFASNET_MODEL', os.path.join(os.path.dirname(__file__), 'models', 'minifasnet.onnx'))
    _minifasnet_session = ort.InferenceSession(_minifasnet_path, providers=['CPUExecutionProvider']) if os.path.exists(_minifasnet_path) else None
except Exception:
    _minifasnet_session = None
_silentface_net = None
try:
    _silent_dir = os.getenv('SILENT_FACE_DIR', os.path.join(os.path.dirname(__file__), 'models', 'Silent-Face-Anti-Spoofing'))
    _silent_prototxt = os.getenv('SILENT_FACE_PROTOTXT', os.path.join(_silent_dir, 'deploy.prototxt'))
    _silent_caffemodel = os.getenv('SILENT_FACE_CAFFE', os.path.join(_silent_dir, 'anti_spoof.caffemodel'))
    if os.path.exists(_silent_prototxt) and os.path.exists(_silent_caffemodel):
        _silentface_net = cv2.dnn.readNetFromCaffe(_silent_prototxt, _silent_caffemodel)
except Exception:
    _silentface_net = None
_silentface_torch = None
_silentface_model_path = None
try:
    import sys
    _sf_repo = os.getenv('SILENT_FACE_REPO', os.path.join(os.path.dirname(__file__), '..', 'third_party', 'Silent-Face-Anti-Spoofing'))
    _sf_src = os.path.join(_sf_repo, 'src')
    _sf_models = os.path.join(_sf_repo, 'resources', 'anti_spoof_models')
    if os.path.isdir(_sf_src):
        if _sf_src not in sys.path:
            sys.path.insert(0, _sf_src)
        from anti_spoof_predict import AntiSpoofPredict
        _silentface_torch = AntiSpoofPredict(device_id=0)
        cand = os.path.join(_sf_models, '2.7_80x80_MiniFASNetV2.pth')
        if os.path.exists(cand):
            _silentface_model_path = cand
        else:
            alt = os.path.join(_sf_models, '4_0_0_80x80_MiniFASNetV1SE.pth')
            _silentface_model_path = alt if os.path.exists(alt) else None
except Exception:
    _silentface_torch = None
    _silentface_model_path = None

def to_data_uri(rgb):
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return ''
    b64 = base64.b64encode(buf.tobytes()).decode('ascii')
    return 'data:image/jpeg;base64,' + b64

STORE_PATH = os.path.join(os.path.dirname(__file__), 'embeddings.json')
_store = {'items': []}  # each item: {'name': str, 'vec': [floats]}
STORE_THUMBS = os.getenv('STORE_THUMBS', 'true').lower() == 'true'
CHUNKS_LOG_PATH = os.path.join(os.path.dirname(__file__), 'chunks_log.jsonl')
# Default: do NOT auto-learn until user completes review
AUTO_LEARN_CHUNKS = os.getenv('AUTO_LEARN_CHUNKS', 'false').lower() == 'true'
AUTO_TRAIN = os.getenv('AUTO_TRAIN', 'false').lower() == 'true'
TRAIN_ON_LABEL = os.getenv('TRAIN_ON_LABEL', 'false').lower() == 'true'
_clf = None
_clf_meta = {'names': [], 'dim': 0}
_clf_dirty = False
_clf_last_train = 0.0
COLLEGES_PATH = os.path.join(os.path.dirname(__file__), 'colleges.json')
PLANS_PATH = os.path.join(os.path.dirname(__file__), 'plans.json')
SESSIONS_PATH = os.path.join(os.path.dirname(__file__), 'sessions.json')
USAGE_PATH = os.path.join(os.path.dirname(__file__), 'usage.json')
STUDENTS_PATH = os.path.join(os.path.dirname(__file__), 'students.json')
FACULTY_PATH = os.path.join(os.path.dirname(__file__), 'faculty.json')
DEPARTMENTS_PATH = os.path.join(os.path.dirname(__file__), 'departments.json')
SUBJECTS_PATH = os.path.join(os.path.dirname(__file__), 'subjects.json')
CLASSES_PATH = os.path.join(os.path.dirname(__file__), 'classes.json')
ATTENDANCE_PATH = os.path.join(os.path.dirname(__file__), 'attendance.json')
USERS_PATH = os.path.join(os.path.dirname(__file__), 'users.json')
CHECK_EVENTS_PATH = os.path.join(os.path.dirname(__file__), 'check_events.json')
PLACES_PATH = os.path.join(os.path.dirname(__file__), 'places.json')
DEVICES_PATH = os.path.join(os.path.dirname(__file__), 'devices.json')
_colleges = {'items': []}
_plans = {'items': []}
_sessions = {'items': []}
_usage = {'items': []}
_students = {'items': []}
_faculty = {'items': []}
_departments = {'items': []}
_subjects = {'items': []}
_classes = {'items': []}
_attendance = {'items': []}
_users = {'items': []}
_check_events = {'items': []}
_places = {'items': []}
_devices = {'items': []}
_data_lock = threading.RLock()

def _atomic_json_dump(path, value):
    """Write JSON without exposing readers to a partially-written file."""
    tmp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with _data_lock:
        try:
            with open(tmp_path, 'w') as f:
                json.dump(value, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass

def _load_store():
    global _store
    if os.path.exists(STORE_PATH):
        try:
            with open(STORE_PATH, 'r') as f:
                _store = json.load(f)
            dirty = False
            if 'items' in _store:
                for it in _store['items']:
                    if 'vec' in it and 'dim' not in it:
                        try:
                            it['dim'] = int(len(it['vec']))
                        except Exception:
                            it['dim'] = 0
                    if 'vecs' not in it:
                        it['vecs'] = []
                    new_vecs = []
                    for r in it.get('vecs', []):
                        if isinstance(r, dict) and 'v' in r and 'id' in r:
                            new_vecs.append(r)
                        else:
                            try:
                                rid = uuid.uuid4().hex[:12]
                            except Exception:
                                rid = str(int(time.time()*1000))
                            if isinstance(r, list):
                                new_vecs.append({'id': rid, 'v': r})
                            else:
                                new_vecs.append({'id': rid, 'v': []})
                            dirty = True
                    it['vecs'] = new_vecs
                    if 'vec' in it and isinstance(it['vec'], list):
                        try:
                            rid = uuid.uuid4().hex[:12]
                        except Exception:
                            rid = str(int(time.time()*1000))
                        it['vecs'].append({'id': rid, 'v': it['vec']})
                        it.pop('vec', None)
                        dirty = True
            if dirty:
                _save_store()
        except Exception:
            _store = {'items': []}
    else:
        _store = {'items': []}

def _save_store():
    try:
        _atomic_json_dump(STORE_PATH, _store)
        try:
            _mark_index_dirty()
        except Exception:
            pass
        try:
            global _clf_dirty
            _clf_dirty = True
        except Exception:
            pass
    except Exception:
        pass
def _load_mt():
    global _colleges, _plans, _sessions, _usage, _students, _faculty, _departments, _subjects, _classes, _attendance, _users, _check_events, _places, _devices
    try:
        if os.path.exists(COLLEGES_PATH):
            with open(COLLEGES_PATH, 'r') as f:
                _colleges = json.load(f)
    except Exception:
        _colleges = {'items': []}
    try:
        if os.path.exists(PLANS_PATH):
            with open(PLANS_PATH, 'r') as f:
                _plans = json.load(f)
    except Exception:
        _plans = {'items': []}
    try:
        if os.path.exists(SESSIONS_PATH):
            with open(SESSIONS_PATH, 'r') as f:
                _sessions = json.load(f)
    except Exception:
        _sessions = {'items': []}
    try:
        if os.path.exists(USAGE_PATH):
            with open(USAGE_PATH, 'r') as f:
                _usage = json.load(f)
    except Exception:
        _usage = {'items': []}
    try:
        if os.path.exists(STUDENTS_PATH):
            with open(STUDENTS_PATH, 'r') as f:
                _students = json.load(f)
    except Exception:
        _students = {'items': []}
    try:
        if os.path.exists(FACULTY_PATH):
            with open(FACULTY_PATH, 'r') as f:
                _faculty = json.load(f)
    except Exception:
        _faculty = {'items': []}
    try:
        if os.path.exists(DEPARTMENTS_PATH):
            with open(DEPARTMENTS_PATH, 'r') as f:
                _departments = json.load(f)
    except Exception:
        _departments = {'items': []}
    try:
        if os.path.exists(SUBJECTS_PATH):
            with open(SUBJECTS_PATH, 'r') as f:
                _subjects = json.load(f)
    except Exception:
        _subjects = {'items': []}
    try:
        if os.path.exists(CLASSES_PATH):
            with open(CLASSES_PATH, 'r') as f:
                _classes = json.load(f)
    except Exception:
        _classes = {'items': []}
    try:
        if os.path.exists(ATTENDANCE_PATH):
            with open(ATTENDANCE_PATH, 'r') as f:
                _attendance = json.load(f)
    except Exception:
        _attendance = {'items': []}
    try:
        if os.path.exists(CHECK_EVENTS_PATH):
            with open(CHECK_EVENTS_PATH, 'r') as f:
                _check_events = json.load(f)
    except Exception:
        _check_events = {'items': []}
    try:
        if os.path.exists(PLACES_PATH):
            with open(PLACES_PATH, 'r') as f:
                _places = json.load(f)
    except Exception:
        _places = {'items': []}
    try:
        if os.path.exists(DEVICES_PATH):
            with open(DEVICES_PATH, 'r') as f:
                _devices = json.load(f)
    except Exception:
        _devices = {'items': []}
    try:
        if os.path.exists(USERS_PATH):
            with open(USERS_PATH, 'r') as f:
                _users = json.load(f)
    except Exception:
        _users = {'items': []}
def _save_colleges():
    try:
        _atomic_json_dump(COLLEGES_PATH, _colleges)
    except Exception:
        pass
def _save_plans():
    try:
        _atomic_json_dump(PLANS_PATH, _plans)
    except Exception:
        pass
def _save_sessions():
    try:
        _atomic_json_dump(SESSIONS_PATH, _sessions)
    except Exception:
        pass
def _save_usage():
    try:
        _atomic_json_dump(USAGE_PATH, _usage)
    except Exception:
        pass
def _save_students():
    try:
        _atomic_json_dump(STUDENTS_PATH, _students)
    except Exception:
        pass
def _save_faculty():
    try:
        _atomic_json_dump(FACULTY_PATH, _faculty)
    except Exception:
        pass
def _save_departments():
    try:
        _atomic_json_dump(DEPARTMENTS_PATH, _departments)
    except Exception:
        pass
def _save_subjects():
    try:
        _atomic_json_dump(SUBJECTS_PATH, _subjects)
    except Exception:
        pass
def _save_classes():
    try:
        _atomic_json_dump(CLASSES_PATH, _classes)
    except Exception:
        pass
def _save_attendance():
    try:
        _atomic_json_dump(ATTENDANCE_PATH, _attendance)
    except Exception:
        pass
def _save_check_events():
    try:
        _atomic_json_dump(CHECK_EVENTS_PATH, _check_events)
    except Exception:
        pass
def _save_users():
    try:
        _atomic_json_dump(USERS_PATH, _users)
    except Exception:
        pass
def _save_places():
    try:
        _atomic_json_dump(PLACES_PATH, _places)
    except Exception:
        pass
def _save_devices():
    try:
        _atomic_json_dump(DEVICES_PATH, _devices)
    except Exception:
        pass
def _bootstrap_superadmin():
    try:
        user = os.getenv('SUPERADMIN_BOOTSTRAP_USER', '').strip()
        pw = os.getenv('SUPERADMIN_BOOTSTRAP_PASS', '').strip()
        email = os.getenv('SUPERADMIN_BOOTSTRAP_EMAIL', '').strip()
        college_id = os.getenv('SUPERADMIN_BOOTSTRAP_COLLEGE', '').strip()
        if (user or email) and pw:
            exists = False
            for u in _users.get('items', []):
                if str(u.get('role','')) == 'SuperAdmin':
                    exists = True
                    break
            if not exists:
                salt = os.urandom(16)
                it = {'id': uuid.uuid4().hex[:12], 'email': email.lower(), 'username': user, 'role': 'SuperAdmin', 'college_id': college_id, 'password_salt': salt.hex(), 'password_hash': _hash_password(pw, salt), 'is_active': True, 'created_at': time.time(), 'is_bootstrap': True}
                _users.setdefault('items', []).append(it)
                _save_users()
    except Exception:
        pass

def _hash_password(pw: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt, 120000).hex()

def _secret_bytes() -> bytes:
    secret = os.getenv('SECRET_KEY', '').strip()
    if not secret:
        raise RuntimeError('SECRET_KEY must be configured')
    return secret.encode('utf-8')

def _make_token(user: dict) -> str:
    secret = _secret_bytes()
    payload = {'uid': user.get('id',''), 'role': user.get('role',''), 'cid': user.get('college_id',''), 'exp': time.time() + 86400.0}
    raw = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    b64 = base64.urlsafe_b64encode(raw).decode('ascii')
    sig = hmac.new(secret, b64.encode('ascii'), hashlib.sha256).hexdigest()
    return b64 + '.' + sig

def _verify_token(tok: str) -> dict | None:
    if not tok or '.' not in tok:
        return None
    try:
        secret = _secret_bytes()
    except RuntimeError:
        return None
    b64, sig = tok.split('.', 1)
    calc = hmac.new(secret, b64.encode('ascii'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, sig):
        return None
    try:
        raw = base64.urlsafe_b64decode(b64.encode('ascii'))
        payload = json.loads(raw.decode('utf-8'))
        if float(payload.get('exp', 0.0)) < time.time():
            return None
        return payload
    except Exception:
        return None

def _current_user():
    auth = request.headers.get('Authorization','').strip()
    if auth.lower().startswith('bearer '):
        tok = auth.split(' ', 1)[1].strip()
        payload = _verify_token(tok)
        if payload is None:
            return None
        uid = str(payload.get('uid',''))
        for u in _users.get('items', []):
            if str(u.get('id','')) == uid and bool(u.get('is_active', True)):
                return {'id': uid, 'role': str(u.get('role','')), 'college_id': str(u.get('college_id',''))}
    return None

def _require_role(roles: list[str]) -> dict | None:
    user = getattr(g, 'current_user', None) or _current_user()
    if user is None or str(user.get('role', '')) not in set(roles):
        return None
    return user

def _scoped_college_id(requested: str = '') -> str:
    user = getattr(g, 'current_user', None) or _current_user() or {}
    if str(user.get('role', '')) != 'SuperAdmin':
        return str(user.get('college_id', '')).strip()
    return str(requested or '').strip()

@app.before_request
def _authenticate_api_request():
    if request.method == 'OPTIONS':
        return None
    endpoint = request.endpoint or ''
    if endpoint in {'auth_login', 'superadmin_create_user', 'web_login', 'static'}:
        return None
    # HTML shells are public; every API call they make remains protected.
    if request.path.startswith('/web/'):
        return None
    user = _current_user()
    if user is None:
        return jsonify({'error': 'authentication required'}), 401
    g.current_user = user
    if str(user.get('role', '')) != 'SuperAdmin':
        requested_cid = str(request.args.get('college_id', '') or request.form.get('college_id', '')).strip()
        if not requested_cid and request.is_json:
            requested_cid = str((request.get_json(silent=True) or {}).get('college_id', '')).strip()
        if requested_cid and requested_cid != str(user.get('college_id', '')):
            return jsonify({'error': 'cross-business access denied'}), 403
    return None
def _find_college(cid: str):
    for it in _colleges.get('items', []):
        if str(it.get('id','')) == str(cid):
            return it
    return None
def _find_plan(name: str):
    for it in _plans.get('items', []):
        if str(it.get('name','')) == str(name):
            return it
    return None
def _month_key(ts: float):
    tm = time.localtime(ts)
    return f"{tm.tm_year}-{tm.tm_mon:02d}"
def _count_month_sessions(cid: str, month_key: str):
    cnt = 0
    for s in _sessions.get('items', []):
        if str(s.get('college_id','')) == str(cid) and str(s.get('month','')) == month_key:
            cnt += 1
    return cnt
def _active_sessions_count(cid: str):
    x = 0
    for s in _sessions.get('items', []):
        if str(s.get('college_id','')) == str(cid) and str(s.get('status','')) == 'Active':
            x += 1
    return x
def _append_chunk_disk(chunk: dict):
    try:
        with open(CHUNKS_LOG_PATH, 'a') as f:
            f.write(json.dumps(chunk) + '\n')
    except Exception:
        pass
def _find_chunk_disk(cid: str):
    try:
        if not os.path.exists(CHUNKS_LOG_PATH):
            return None
        with open(CHUNKS_LOG_PATH, 'r') as f:
            lines = f.readlines()
        for line in reversed(lines):
            try:
                obj = json.loads(line)
                if str(obj.get('id','')) == cid:
                    return obj
            except Exception:
                continue
    except Exception:
        return None
    return None
def _read_chunks_log(limit: int = 40):
    items = []
    try:
        if not os.path.exists(CHUNKS_LOG_PATH):
            return items
        with open(CHUNKS_LOG_PATH, 'r') as f:
            lines = f.readlines()
        for line in reversed(lines[-limit:]):
            try:
                obj = json.loads(line)
                cnt = int(len(obj.get('thumbs', []))) + int(sum(len(x) for x in obj.get('aug_thumbs', []) if isinstance(x, list))) + int(len(obj.get('portraits', [])))
                nm = list({str(n) for n in obj.get('names', [])})
                items.append({'id': obj.get('id',''), 'ts': float(obj.get('ts',0.0)), 'count': cnt, 'names': nm, 'image': (obj.get('image','') if STORE_THUMBS else '')})
            except Exception:
                continue
    except Exception:
        items = []
    return items

def _normalize(v: np.ndarray) -> np.ndarray:
    if v is None or v.size == 0:
        return np.zeros((0,), dtype=np.float32)
    try:
        x = np.array(v, dtype=np.float32)
        x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
        n = float(np.linalg.norm(x))
        if not np.isfinite(n) or n <= 1e-12:
            return x
        return (x / n).astype(np.float32)
    except Exception:
        return np.zeros((0,), dtype=np.float32)

def _search(vec: np.ndarray, topk: int = 1, college_id: str | None = None):
    if not _store['items'] or vec.size == 0:
        return []
    v = _normalize(vec)
    names, sims = [], []
    try:
        cache_key = str(college_id or '')
        if '_index_cache_map' not in globals():
            globals()['_index_cache_map'] = {}
        idx_cache = globals()['_index_cache_map'].get(cache_key, {'vecs': None, 'names': [], 'name_to_indices': {}, 'dim': 0, 'dirty': True})
        if idx_cache.get('dirty', True) or idx_cache.get('vecs') is None or int(idx_cache.get('dim', 0)) != int(v.size):
            vecs = []
            labs = []
            dim = 0
            for it in _store.get('items', []):
                cid = str(it.get('college_id',''))
                if college_id is not None and cid != str(college_id):
                    continue
                nm = it.get('name', '')
                if 'vecs' in it and isinstance(it['vecs'], list):
                    for r in it['vecs']:
                        rr = np.array(r['v'] if isinstance(r, dict) else r, dtype=np.float32)
                        if rr.size > 0:
                            vecs.append(_normalize(rr)); labs.append(nm); dim = int(rr.size)
                if 'vec' in it:
                    rr = np.array(it['vec'], dtype=np.float32)
                    if rr.size > 0:
                        vecs.append(_normalize(rr)); labs.append(nm); dim = int(rr.size)
                if 'aug_vecs' in it and isinstance(it['aug_vecs'], list):
                    for r in it['aug_vecs']:
                        rr = np.array(r, dtype=np.float32)
                        if rr.size > 0:
                            vecs.append(_normalize(rr)); labs.append(nm); dim = int(rr.size)
            if vecs:
                mat = np.stack(vecs, axis=0).astype(np.float32)
            else:
                mat = np.zeros((0, 0), dtype=np.float32)
            name_to_indices = {}
            for i, nm in enumerate(labs):
                name_to_indices.setdefault(nm, []).append(i)
            for k in list(name_to_indices.keys()):
                name_to_indices[k] = np.array(name_to_indices[k], dtype=np.int64)
            faiss_flat = None
            faiss_ivf = None
            faiss_hnsw = None
            ivf_nprobe = FAISS_NPROBE
            try:
                if _faiss is not None and mat is not None and mat.size > 0 and dim > 0:
                    n = int(len(labs))
                    faiss_flat = _faiss.IndexFlatIP(dim)
                    faiss_flat.add(mat)
                    enable_ivf = str(os.getenv('FAISS_ENABLE_IVF', '0')).strip().lower() in ('1', 'true')
                    enable_hnsw = str(os.getenv('FAISS_ENABLE_HNSW', '0')).strip().lower() in ('1', 'true')
                    if enable_ivf and n >= 100:
                        nlist = FAISS_NLIST if FAISS_NLIST > 0 else max(8, min(4096, max(8, n // 4)))
                        need = max(200, nlist * 32)
                        if n >= need:
                            faiss_ivf = _faiss.index_factory(dim, f"IVF{nlist},Flat", _faiss.METRIC_INNER_PRODUCT)
                            if not faiss_ivf.is_trained:
                                faiss_ivf.train(mat)
                            faiss_ivf.add(mat)
                            faiss_ivf.nprobe = ivf_nprobe
                    if enable_hnsw and n >= 1000:
                        faiss_hnsw = _faiss.index_factory(dim, f"HNSW{FAISS_HNSW_M}", _faiss.METRIC_INNER_PRODUCT)
                        faiss_hnsw.add(mat)
            except Exception:
                faiss_flat = None
                faiss_ivf = None
                faiss_hnsw = None
            idx_cache = {'vecs': mat, 'names': labs, 'name_to_indices': name_to_indices, 'dim': dim, 'dirty': False, 'faiss_flat': faiss_flat, 'faiss_ivf': faiss_ivf, 'faiss_hnsw': faiss_hnsw, 'ivf_nprobe': ivf_nprobe}
            globals()['_index_cache_map'][cache_key] = idx_cache
        mat = idx_cache.get('vecs')
        if mat is not None and mat.size > 0 and int(idx_cache.get('dim', 0)) == int(v.size):
            vv = np.nan_to_num(v, nan=0.0, posinf=0.0, neginf=0.0)
            if mat.shape[1] != vv.size:
                raise ValueError('index dimension mismatch')
            per_name_max = {}
            faiss_ivf = idx_cache.get('faiss_ivf', None)
            faiss_hnsw = idx_cache.get('faiss_hnsw', None)
            faiss_flat = idx_cache.get('faiss_flat', None)
            cand_set = None
            if faiss_ivf is not None:
                try:
                    k1 = min(len(idx_cache['names']), max(FAISS_CAND_K, topk * 16))
                    D1, I1 = faiss_ivf.search(vv.reshape(1, -1), k1)
                    cand_set = set(int(x) for x in I1[0] if int(x) >= 0)
                except Exception:
                    cand_set = set()
            if faiss_hnsw is not None:
                try:
                    k2 = min(len(idx_cache['names']), max(FAISS_CAND_K, topk * 16))
                    D2, I2 = faiss_hnsw.search(vv.reshape(1, -1), k2)
                    hs = set(int(x) for x in I2[0] if int(x) >= 0)
                    cand_set = (cand_set | hs) if cand_set is not None else hs
                except Exception:
                    pass
            if cand_set is None or len(cand_set) == 0:
                s_all = mat @ vv
                for nm, idxs in idx_cache.get('name_to_indices', {}).items():
                    if len(idxs) == 0:
                        continue
                    m = float(np.max(s_all[idxs]))
                    per_name_max[nm] = m
            else:
                cands = np.array(sorted(list(cand_set)), dtype=np.int64)
                s_sub = mat[cands] @ vv
                for nm, idxs in idx_cache.get('name_to_indices', {}).items():
                    if len(idxs) == 0:
                        continue
                    sel = np.intersect1d(cands, idxs)
                    if len(sel) == 0:
                        continue
                    pos = np.searchsorted(cands, sel)
                    m = float(np.max(s_sub[pos]))
                    per_name_max[nm] = m
            if per_name_max:
                names = list(per_name_max.keys())
                sims = [per_name_max[nm] for nm in names]
                order = np.argsort(sims)[::-1]
                return [{'name': names[i], 'similarity': sims[i]} for i in order[:topk]]
    except Exception:
        pass
    for it in _store['items']:
        if college_id is not None and str(it.get('college_id','')) != str(college_id):
            continue
        vecs = []
        if 'vecs' in it and isinstance(it['vecs'], list):
            for r in it['vecs']:
                rr = np.array(r['v'] if isinstance(r, dict) else r, dtype=np.float32)
                if rr.size == v.size:
                    vecs.append(_normalize(rr))
        if 'vec' in it:
            u = np.array(it['vec'], dtype=np.float32)
            if u.size == v.size:
                vecs.append(_normalize(u))
        if 'aug_vecs' in it and isinstance(it['aug_vecs'], list):
            for r in it['aug_vecs']:
                rr = np.array(r, dtype=np.float32)
                if rr.size == v.size:
                    vecs.append(_normalize(rr))
        if not vecs:
            continue
        arr = np.stack(vecs, axis=0).astype(np.float32)
        s_all = arr @ v
        s_max = float(np.max(s_all))
        centroid = _normalize(np.mean(arr, axis=0).astype(np.float32))
        s_cent = float(np.dot(v, centroid))
        s = float(0.85 * s_max + 0.15 * s_cent)
        names.append(it.get('name', 'Unknown')); sims.append(s)
    if not sims:
        return []
    order = np.argsort(sims)[::-1]
    return [{'name': names[i], 'similarity': sims[i]} for i in order[:topk]]
_index_cache = {'vecs': None, 'names': [], 'name_to_indices': {}, 'dim': 0, 'dirty': True}
def _mark_index_dirty():
    try:
        globals()['_index_cache_map'] = {}
        _index_cache['dirty'] = True
    except Exception:
        pass
def _rebuild_index():
    global _index_cache
    vecs = []
    labs = []
    dim = 0
    for it in _store.get('items', []):
        nm = it.get('name', '')
        if 'vecs' in it and isinstance(it['vecs'], list):
            for r in it['vecs']:
                rr = np.array(r['v'] if isinstance(r, dict) else r, dtype=np.float32)
                if rr.size > 0:
                    vecs.append(_normalize(rr)); labs.append(nm); dim = int(rr.size)
        if 'vec' in it:
            rr = np.array(it['vec'], dtype=np.float32)
            if rr.size > 0:
                vecs.append(_normalize(rr)); labs.append(nm); dim = int(rr.size)
        if 'aug_vecs' in it and isinstance(it['aug_vecs'], list):
            for r in it['aug_vecs']:
                rr = np.array(r, dtype=np.float32)
                if rr.size > 0:
                    vecs.append(_normalize(rr)); labs.append(nm); dim = int(rr.size)
    if vecs:
        mat = np.stack(vecs, axis=0).astype(np.float32)
    else:
        mat = np.zeros((0, 0), dtype=np.float32)
    name_to_indices = {}
    for i, nm in enumerate(labs):
        name_to_indices.setdefault(nm, []).append(i)
    for k in list(name_to_indices.keys()):
        name_to_indices[k] = np.array(name_to_indices[k], dtype=np.int64)
    _index_cache = {'vecs': mat, 'names': labs, 'name_to_indices': name_to_indices, 'dim': dim, 'dirty': False}

def _unique_assign_from_candidates(cand_lists, min_sim: float = 0.8):
    try:
        n = len(cand_lists)
        assigned = set()
        taken_det = [False] * n
        out = ['Unknown'] * n
        pairs = []
        for i, lst in enumerate(cand_lists):
            for c in (lst or []):
                nm = str(c.get('name', ''))
                s = float(c.get('similarity', 0.0))
                if nm and nm != 'Unknown' and s >= float(min_sim):
                    pairs.append((s, i, nm))
        pairs.sort(key=lambda x: x[0], reverse=True)
        for s, i, nm in pairs:
            if not taken_det[i] and nm not in assigned:
                out[i] = nm
                taken_det[i] = True
                assigned.add(nm)
        return out
    except Exception:
        return ['Unknown'] * len(cand_lists)

def _build_classification_dataset():
    X, y, names = [], [], []
    label_to_idx = {}
    dim = 0
    for it in _store.get('items', []):
        nm = str(it.get('name','')).strip()
        if nm == '':
            continue
        if nm not in label_to_idx:
            label_to_idx[nm] = len(names); names.append(nm)
        idx = label_to_idx[nm]
        vecs = it.get('vecs', [])
        if isinstance(vecs, list):
            for r in vecs:
                rr = np.array(r['v'] if isinstance(r, dict) else r, dtype=np.float32)
                if rr.size > 0:
                    X.append(_normalize(rr)); y.append(idx); dim = int(rr.size)
        if 'vec' in it:
            rr = np.array(it['vec'], dtype=np.float32)
            if rr.size > 0:
                X.append(_normalize(rr)); y.append(idx); dim = int(rr.size)
        if 'aug_vecs' in it and isinstance(it['aug_vecs'], list):
            for r in it['aug_vecs']:
                rr = np.array(r, dtype=np.float32)
                if rr.size > 0:
                    X.append(_normalize(rr)); y.append(idx); dim = int(rr.size)
    if not X or len(names) < 2:
        return None, None, [], 0
    X = np.stack(X, axis=0).astype(np.float32)
    y = np.array(y, dtype=np.int64)
    return X, y, names, dim

def _train_classifier(max_epochs: int = 20):
    global _clf, _clf_meta, _clf_dirty, _clf_last_train
    try:
        X, y, names, dim = _build_classification_dataset()
        if X is None or len(names) < 2:
            try:
                app.logger.info("[ML] classifier: not enough classes to train (need >=2)")
            except Exception:
                pass
            _clf = None; _clf_meta = {'names': [], 'dim': 0}; _clf_dirty = False; _clf_last_train = time.time()
            return False
        try:
            app.logger.info(f"[ML] classifier: start training samples={X.shape[0]} dim={dim} classes={len(names)} epochs={max_epochs}")
        except Exception:
            pass
        import torch
        import torch.nn as nn
        import torch.optim as optim
        device = 'cpu'
        C = int(len(names))
        model = nn.Linear(dim, C)
        model = model.to(device)
        criterion = nn.CrossEntropyLoss()
        opt = optim.Adam(model.parameters(), lr=1e-2, weight_decay=1e-4)
        # simple training loop
        tX = torch.from_numpy(X).to(device)
        ty = torch.from_numpy(y).to(device)
        bs = 64
        epochs = max_epochs
        model.train()
        last_loss = 0.0
        for ep in range(epochs):
            perm = torch.randperm(tX.shape[0])
            for i in range(0, tX.shape[0], bs):
                idx = perm[i:i+bs]
                xb = tX[idx]; yb = ty[idx]
                opt.zero_grad()
                out = model(xb)
                loss = criterion(out, yb)
                loss.backward()
                opt.step()
                last_loss = float(loss.detach().cpu().item())
            if (ep + 1) % max(1, epochs // 4) == 0:
                try:
                    app.logger.info(f"[ML] classifier: epoch {ep+1}/{epochs} loss={last_loss:.4f}")
                except Exception:
                    pass
        _clf = model.eval()
        _clf_meta = {'names': names, 'dim': dim}
        # save lightweight state
        try:
            import torch
            torch.save({'state_dict': _clf.state_dict(), 'meta': _clf_meta}, os.path.join(os.path.dirname(__file__), 'classifier.pth'))
            try:
                app.logger.info(f"[ML] classifier: finished training; saved state for {len(names)} classes")
            except Exception:
                pass
        except Exception:
            pass
        _clf_dirty = False
        _clf_last_train = time.time()
        return True
    except Exception:
        _clf = None; _clf_meta = {'names': [], 'dim': 0}; _clf_dirty = False; _clf_last_train = time.time()
        return False

def _maybe_auto_train():
    try:
        global _clf_dirty, _clf_last_train
        if _clf_dirty and (time.time() - _clf_last_train) > 5.0:
            try:
                app.logger.info("[ML] classifier: auto-train triggered")
            except Exception:
                pass
            _train_classifier(max_epochs=12)
    except Exception:
        pass

def _clf_predict(vec: np.ndarray, topk: int = 1):
    try:
        if _clf is None or not _clf_meta or int(_clf_meta.get('dim', 0)) != int(vec.size):
            return []
        try:
            if _clf_dirty:
                return []
        except Exception:
            pass
        import torch
        with torch.no_grad():
            x = torch.from_numpy(_normalize(vec)[None, ...].astype(np.float32))
            out = _clf(x)[0]
            prob = torch.softmax(out, dim=0).cpu().numpy().astype(np.float32)
        names = list(_clf_meta.get('names', []))
        order = np.argsort(prob)[::-1]
        return [{'name': names[i], 'similarity': float(prob[i])} for i in order[:topk]]
    except Exception:
        return []
@app.get('/plans')
def get_plans():
    return jsonify({'items': _plans.get('items', [])})
@app.post('/plans')
def add_plan():
    if _require_role(['SuperAdmin']) is None:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True)
    if not data or 'name' not in data:
        return jsonify({'error': 'name required'}), 400
    it = {
        'id': uuid.uuid4().hex[:12],
        'name': str(data['name']),
        'max_students': int(data.get('max_students', 0)),
        'max_faculty': int(data.get('max_faculty', 0)),
        'max_sessions_per_month': int(data.get('max_sessions_per_month', 0)),
        'max_storage_gb': int(data.get('max_storage_gb', 0)),
        'ai_model_access': str(data.get('ai_model_access','')),
        'price': float(data.get('price', 0.0))
    }
    _plans.setdefault('items', []).append(it)
    _save_plans()
    return jsonify({'ok': True, 'id': it['id']})
@app.post('/plan_update')
def plan_update():
    u = _require_role(['SuperAdmin'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    pid = str(data.get('id',''))
    for p in _plans.get('items', []):
        if str(p.get('id','')) == pid:
            for k in ['name','max_students','max_faculty','max_sessions_per_month','max_storage_gb','ai_model_access','price']:
                if k in data:
                    p[k] = data[k]
            _save_plans()
            return jsonify({'ok': True})
    return jsonify({'error': 'not found'}), 404
@app.post('/plan_delete')
def plan_delete():
    u = _require_role(['SuperAdmin'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    pid = str(data.get('id',''))
    before = len(_plans.get('items', []))
    _plans['items'] = [p for p in _plans.get('items', []) if str(p.get('id','')) != pid]
    _save_plans()
    return jsonify({'ok': True, 'deleted': before - len(_plans.get('items', []))})
@app.get('/departments')
def get_departments():
    cid = _scoped_college_id(request.args.get('college_id',''))
    items = [d for d in _departments.get('items', []) if (not cid) or str(d.get('college_id','')) == cid]
    return jsonify({'items': items})
@app.post('/departments')
def add_department():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    if not data or 'name' not in data or 'college_id' not in data:
        return jsonify({'error': 'name and college_id required'}), 400
    if u.get('role') != 'SuperAdmin' and str(data['college_id']) != str(u.get('college_id','')):
        return jsonify({'error': 'forbidden'}), 403
    it = {
        'id': uuid.uuid4().hex[:12],
        'college_id': str(data['college_id']),
        'name': str(data['name'])
    }
    _departments.setdefault('items', []).append(it)
    _save_departments()
    return jsonify({'ok': True, 'id': it['id']})
@app.post('/department_update')
def department_update():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    did = str(data.get('id',''))
    for d in _departments.get('items', []):
        if str(d.get('id','')) == did:
            if u.get('role') != 'SuperAdmin' and str(d.get('college_id','')) != str(u.get('college_id','')):
                return jsonify({'error': 'forbidden'}), 403
            for k in ['name']:
                if k in data:
                    d[k] = data[k]
            _save_departments()
            return jsonify({'ok': True})
    return jsonify({'error': 'not found'}), 404
@app.post('/department_delete')
def department_delete():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    did = str(data.get('id',''))
    before = len(_departments.get('items', []))
    _departments['items'] = [d for d in _departments.get('items', []) if str(d.get('id','')) != did or (u.get('role') != 'SuperAdmin' and str(d.get('college_id','')) != str(u.get('college_id','')))]
    _save_departments()
    return jsonify({'ok': True, 'deleted': before - len(_departments.get('items', []))})
@app.get('/subjects')
def get_subjects():
    cid = _scoped_college_id(request.args.get('college_id',''))
    items = [s for s in _subjects.get('items', []) if (not cid) or str(s.get('college_id','')) == cid]
    return jsonify({'items': items})
@app.post('/subjects')
def add_subject():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    if not data or 'name' not in data or 'college_id' not in data:
        return jsonify({'error': 'name and college_id required'}), 400
    if u.get('role') != 'SuperAdmin' and str(data['college_id']) != str(u.get('college_id','')):
        return jsonify({'error': 'forbidden'}), 403
    it = {
        'id': uuid.uuid4().hex[:12],
        'college_id': str(data['college_id']),
        'name': str(data['name'])
    }
    _subjects.setdefault('items', []).append(it)
    _save_subjects()
    return jsonify({'ok': True, 'id': it['id']})
@app.post('/subject_update')
def subject_update():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    sid = str(data.get('id',''))
    for s in _subjects.get('items', []):
        if str(s.get('id','')) == sid:
            if u.get('role') != 'SuperAdmin' and str(s.get('college_id','')) != str(u.get('college_id','')):
                return jsonify({'error': 'forbidden'}), 403
            for k in ['name']:
                if k in data:
                    s[k] = data[k]
            _save_subjects()
            return jsonify({'ok': True})
    return jsonify({'error': 'not found'}), 404
@app.post('/subject_delete')
def subject_delete():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    sid = str(data.get('id',''))
    before = len(_subjects.get('items', []))
    _subjects['items'] = [s for s in _subjects.get('items', []) if str(s.get('id','')) != sid or (u.get('role') != 'SuperAdmin' and str(s.get('college_id','')) != str(u.get('college_id','')))]
    _save_subjects()
    return jsonify({'ok': True, 'deleted': before - len(_subjects.get('items', []))})
@app.get('/faculty')
def get_faculty():
    cid = _scoped_college_id(request.args.get('college_id',''))
    items = [f for f in _faculty.get('items', []) if (not cid) or str(f.get('college_id','')) == cid]
    return jsonify({'items': items})
@app.post('/faculty')
def add_faculty():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    if not data or 'name' not in data or 'college_id' not in data:
        return jsonify({'error': 'name and college_id required'}), 400
    if u.get('role') != 'SuperAdmin' and str(data['college_id']) != str(u.get('college_id','')):
        return jsonify({'error': 'forbidden'}), 403
    it = {
        'id': uuid.uuid4().hex[:12],
        'college_id': str(data['college_id']),
        'name': str(data['name']),
        'department_id': str(data.get('department_id','')),
        'email': str(data.get('email','')),
        'role': str(data.get('role','Faculty'))
    }
    _faculty.setdefault('items', []).append(it)
    _save_faculty()
    return jsonify({'ok': True, 'id': it['id']})
@app.post('/faculty_update')
def faculty_update():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    fid = str(data.get('id',''))
    for f in _faculty.get('items', []):
        if str(f.get('id','')) == fid:
            if u.get('role') != 'SuperAdmin' and str(f.get('college_id','')) != str(u.get('college_id','')):
                return jsonify({'error': 'forbidden'}), 403
            for k in ['name','email','department_id','role','college_id']:
                if k in data:
                    f[k] = data[k]
            _save_faculty()
            return jsonify({'ok': True})
    return jsonify({'error': 'not found'}), 404
@app.post('/faculty_delete')
def faculty_delete():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    fid = str(data.get('id',''))
    before = len(_faculty.get('items', []))
    _faculty['items'] = [f for f in _faculty.get('items', []) if str(f.get('id','')) != fid or (u.get('role') != 'SuperAdmin' and str(f.get('college_id','')) != str(u.get('college_id','')))]
    _save_faculty()
    return jsonify({'ok': True, 'deleted': before - len(_faculty.get('items', []))})
@app.get('/students')
def get_students():
    cid = _scoped_college_id(request.args.get('college_id',''))
    items = [s for s in _students.get('items', []) if (not cid) or str(s.get('college_id','')) == cid]
    return jsonify({'items': items})
@app.post('/students')
def add_students():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    if not data or 'name' not in data or 'college_id' not in data or 'roll_number' not in data:
        return jsonify({'error': 'name, college_id, roll_number required'}), 400
    if u.get('role') != 'SuperAdmin' and str(data['college_id']) != str(u.get('college_id','')):
        return jsonify({'error': 'forbidden'}), 403
    it = {
        'id': uuid.uuid4().hex[:12],
        'college_id': str(data['college_id']),
        'name': str(data['name']),
        'roll_number': str(data['roll_number']),
        'department_id': str(data.get('department_id','')),
        'year': str(data.get('year','')),
        'section': str(data.get('section','')),
        'email': str(data.get('email','')),
        'face_embedding': list(map(float, data.get('face_embedding', []))) if isinstance(data.get('face_embedding', []), list) else []
    }
    _students.setdefault('items', []).append(it)
    _save_students()
    return jsonify({'ok': True, 'id': it['id']})
@app.post('/student_update')
def student_update():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    sid = str(data.get('id',''))
    for s in _students.get('items', []):
        if str(s.get('id','')) == sid:
            if u.get('role') != 'SuperAdmin' and str(s.get('college_id','')) != str(u.get('college_id','')):
                return jsonify({'error': 'forbidden'}), 403
            for k in ['name','roll_number','department_id','year','section','email','college_id']:
                if k in data:
                    s[k] = data[k]
            _save_students()
            return jsonify({'ok': True})
    return jsonify({'error': 'not found'}), 404
@app.post('/student_delete')
def student_delete():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    sid = str(data.get('id',''))
    before = len(_students.get('items', []))
    _students['items'] = [s for s in _students.get('items', []) if str(s.get('id','')) != sid or (u.get('role') != 'SuperAdmin' and str(s.get('college_id','')) != str(u.get('college_id','')))]
    _save_students()
    return jsonify({'ok': True, 'deleted': before - len(_students.get('items', []))})
@app.get('/classes')
def get_classes():
    cid = _scoped_college_id(request.args.get('college_id',''))
    items = [c for c in _classes.get('items', []) if (not cid) or str(c.get('college_id','')) == cid]
    return jsonify({'items': items})
@app.post('/classes')
def add_class():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    required = ['college_id','subject_id','faculty_id','room_number','schedule_time']
    if not data or any(k not in data for k in required):
        return jsonify({'error': 'college_id, subject_id, faculty_id, room_number, schedule_time required'}), 400
    if u.get('role') != 'SuperAdmin' and str(data['college_id']) != str(u.get('college_id','')):
        return jsonify({'error': 'forbidden'}), 403
    it = {
        'id': uuid.uuid4().hex[:12],
        'college_id': str(data['college_id']),
        'subject_id': str(data['subject_id']),
        'faculty_id': str(data['faculty_id']),
        'room_number': str(data['room_number']),
        'schedule_time': str(data['schedule_time']),
        'department_id': str(data.get('department_id','')),
        'year': str(data.get('year','')),
        'section': str(data.get('section',''))
    }
    _classes.setdefault('items', []).append(it)
    _save_classes()
    return jsonify({'ok': True, 'id': it['id']})
@app.post('/class_update')
def class_update():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    cid = str(data.get('id',''))
    for c in _classes.get('items', []):
        if str(c.get('id','')) == cid:
            if u.get('role') != 'SuperAdmin' and str(c.get('college_id','')) != str(u.get('college_id','')):
                return jsonify({'error': 'forbidden'}), 403
            for k in ['subject_id','faculty_id','room_number','schedule_time','department_id','year','section','college_id']:
                if k in data:
                    c[k] = data[k]
            _save_classes()
            return jsonify({'ok': True})
    return jsonify({'error': 'not found'}), 404
@app.post('/class_delete')
def class_delete():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    cid = str(data.get('id',''))
    before = len(_classes.get('items', []))
    _classes['items'] = [c for c in _classes.get('items', []) if str(c.get('id','')) != cid or (u.get('role') != 'SuperAdmin' and str(c.get('college_id','')) != str(u.get('college_id','')))]
    _save_classes()
    return jsonify({'ok': True, 'deleted': before - len(_classes.get('items', []))})
@app.get('/colleges')
def get_colleges():
    u = getattr(g, 'current_user', {})
    if u.get('role') == 'SuperAdmin':
        return jsonify({'items': _colleges.get('items', [])})
    cid = str(u.get('college_id', ''))
    return jsonify({'items': [c for c in _colleges.get('items', []) if str(c.get('id', '')) == cid]})
@app.post('/colleges')
def add_college():
    if _require_role(['SuperAdmin']) is None:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True)
    if not data or 'name' not in data:
        return jsonify({'error': 'name required'}), 400
    it = {
        'id': uuid.uuid4().hex[:12],
        'name': str(data['name']),
        'address': str(data.get('address','')),
        'contact_email': str(data.get('contact_email','')),
        'subscription_plan': str(data.get('subscription_plan','')),
        'max_students': int(data.get('max_students', 0)),
        'max_faculty': int(data.get('max_faculty', 0)),
        'max_sessions_per_month': int(data.get('max_sessions_per_month', 0)),
        'ai_threshold': float(data.get('ai_threshold', 0.85)),
        'is_active': bool(data.get('is_active', True)),
        'model_version': str(data.get('model_version','')),
        'gpu_priority': int(data.get('gpu_priority', 0)),
        'max_concurrent_sessions': int(data.get('max_concurrent_sessions', 1)),
        'created_at': float(time.time())
    }
    _colleges.setdefault('items', []).append(it)
    _save_colleges()
    return jsonify({'ok': True, 'id': it['id']})
@app.post('/college_delete')
def college_delete():
    u = _require_role(['SuperAdmin'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    cid = str(data.get('id',''))
    before = len(_colleges.get('items', []))
    _colleges['items'] = [c for c in _colleges.get('items', []) if str(c.get('id','')) != cid]
    _save_colleges()
    return jsonify({'ok': True, 'deleted': before - len(_colleges.get('items', []))})
@app.post('/college_update')
def college_update():
    if _require_role(['SuperAdmin']) is None:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True)
    cid = str(data.get('id','')).strip()
    it = _find_college(cid)
    if it is None:
        return jsonify({'error': 'college not found'}), 404
    for k in ['name','address','contact_email','subscription_plan','max_students','max_faculty','max_sessions_per_month','ai_threshold','is_active','model_version','gpu_priority','max_concurrent_sessions']:
        if k in data:
            it[k] = data[k]
    _save_colleges()
    return jsonify({'ok': True})
@app.get('/sessions_live')
def sessions_live():
    items = [s for s in _sessions.get('items', []) if str(s.get('status','')) == 'Active']
    return jsonify({'items': items})
@app.post('/session_start')
def session_start():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD','Faculty'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    cid = _scoped_college_id(data.get('college_id',''))
    cls = str(data.get('class_id','')).strip()
    fid = str(data.get('faculty_id','')).strip()
    if u.get('role') != 'SuperAdmin' and cid != str(u.get('college_id','')):
        return jsonify({'error': 'forbidden'}), 403
    col = _find_college(cid)
    if col is None:
        return jsonify({'error': 'college not found'}), 404
    if not bool(col.get('is_active', True)):
        return jsonify({'error': 'inactive college'}), 403
    now = time.time()
    mk = _month_key(now)
    plan = _find_plan(str(col.get('subscription_plan','')))
    limit = int(col.get('max_sessions_per_month', 0))
    if plan and int(plan.get('max_sessions_per_month', 0)) > 0:
        limit = int(plan.get('max_sessions_per_month', 0))
    used = _count_month_sessions(cid, mk)
    if limit > 0 and used >= limit:
        return jsonify({'error': 'session limit exceeded'}), 403
    max_conc = int(col.get('max_concurrent_sessions', 1))
    conc = _active_sessions_count(cid)
    if max_conc > 0 and conc >= max_conc:
        return jsonify({'error': 'concurrent limit exceeded'}), 403
    sid = uuid.uuid4().hex[:12]
    rec = {'id': sid, 'college_id': cid, 'class_id': cls, 'faculty_id': fid, 'date': time.strftime('%Y-%m-%d', time.localtime(now)), 'start_time': time.strftime('%H:%M:%S', time.localtime(now)), 'end_time': '', 'status': 'Active', 'recognized_count': 0, 'total_students': 0, 'month': mk}
    _sessions.setdefault('items', []).append(rec)
    _save_sessions()
    updated = False
    for u in _usage.get('items', []):
        if str(u.get('college_id','')) == cid and str(u.get('month','')) == mk:
            u['total_sessions'] = int(u.get('total_sessions', 0)) + 1
            updated = True
            break
    if not updated:
        _usage.setdefault('items', []).append({'id': uuid.uuid4().hex[:12], 'college_id': cid, 'month': mk, 'total_sessions': 1, 'total_ai_calls': 0, 'total_recognitions': 0, 'storage_used_gb': 0.0})
    _save_usage()
    return jsonify({'ok': True, 'id': sid})
def _students_in_class(class_rec):
    cid = str(class_rec.get('college_id',''))
    dep = str(class_rec.get('department_id',''))
    year = str(class_rec.get('year',''))
    sec = str(class_rec.get('section',''))
    out = []
    for s in _students.get('items', []):
        if str(s.get('college_id','')) != cid:
            continue
        if dep and str(s.get('department_id','')) != dep:
            continue
        if year and str(s.get('year','')) != year:
            continue
        if sec and str(s.get('section','')) != sec:
            continue
        out.append(s)
    return out
@app.post('/session_finalize')
def session_finalize():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD','Faculty'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    sid = str(data.get('id','')).strip()
    rec_names = data.get('recognized_names', [])
    rec_ids = data.get('recognized_student_ids', [])
    conf = data.get('confidence', {})
    if not sid:
        return jsonify({'error': 'id required'}), 400
    sess = None
    for s in _sessions.get('items', []):
        if str(s.get('id','')) == sid:
            sess = s; break
    if sess is None:
        return jsonify({'error': 'session not found'}), 404
    cid = str(sess.get('college_id',''))
    if u.get('role') != 'SuperAdmin' and cid != str(u.get('college_id','')):
        return jsonify({'error': 'forbidden'}), 403
    clsid = str(sess.get('class_id',''))
    cls = None
    for c in _classes.get('items', []):
        if str(c.get('id','')) == clsid:
            cls = c; break
    if cls is None:
        return jsonify({'error': 'class not found'}), 404
    studs = _students_in_class(cls)
    all_ids = [str(s.get('id','')) for s in studs]
    name_to_id = {}
    for s in studs:
        name_to_id[str(s.get('name',''))] = str(s.get('id',''))
    recognized = set()
    for x in rec_ids or []:
        if str(x) in all_ids:
            recognized.add(str(x))
    for nm in rec_names or []:
        k = name_to_id.get(str(nm))
        if k:
            recognized.add(k)
    ts_now = time.time()
    for sid0 in all_ids:
        status = 'Present' if sid0 in recognized else 'Absent'
        score = float(conf.get(sid0, 0.0))
        _attendance.setdefault('items', []).append({
            'id': uuid.uuid4().hex[:12],
            'college_id': cid,
            'session_id': sid,
            'student_id': sid0,
            'status': status,
            'confidence_score': score,
            'timestamp': ts_now
        })
    sess['total_students'] = len(all_ids)
    sess['recognized_count'] = len(recognized)
    _save_attendance()
    _save_sessions()
    updated = False
    mk = _month_key(ts_now)
    for u in _usage.get('items', []):
        if str(u.get('college_id','')) == cid and str(u.get('month','')) == mk:
            u['total_recognitions'] = int(u.get('total_recognitions', 0)) + len(recognized)
            updated = True
            break
    if not updated:
        _usage.setdefault('items', []).append({'id': uuid.uuid4().hex[:12], 'college_id': cid, 'month': mk, 'total_sessions': 0, 'total_ai_calls': 0, 'total_recognitions': len(recognized), 'storage_used_gb': 0.0})
    _save_usage()
    return jsonify({'ok': True, 'recognized': len(recognized), 'total': len(all_ids)})
@app.post('/session_close')
def session_close():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD','Faculty'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    sid = str(data.get('id','')).strip()
    for s in _sessions.get('items', []):
        if str(s.get('id','')) == sid:
            if u.get('role') != 'SuperAdmin' and str(s.get('college_id', '')) != str(u.get('college_id', '')):
                return jsonify({'error': 'forbidden'}), 403
            now = time.time()
            s['status'] = 'Closed'
            s['end_time'] = time.strftime('%H:%M:%S', time.localtime(now))
            _save_sessions()
            return jsonify({'ok': True})
    return jsonify({'error': 'session not found'}), 404
@app.get('/usage_metrics')
def usage_metrics():
    cid = _scoped_college_id(request.args.get('college_id', ''))
    return jsonify({'items': [u for u in _usage.get('items', []) if (not cid) or str(u.get('college_id', '')) == cid]})

@app.get('/attendance_records')
def get_attendance_records():
    sid = request.args.get('session_id','').strip()
    cid = _scoped_college_id(request.args.get('college_id',''))
    items = []
    for r in _attendance.get('items', []):
        if sid and str(r.get('session_id','')) != sid:
            continue
        if cid and str(r.get('college_id','')) != cid:
            continue
        items.append(r)
    return jsonify({'items': items})

@app.get('/places')
def places():
    cid = _scoped_college_id(request.args.get('college_id',''))
    items = []
    for p in _places.get('items', []):
        if cid and str(p.get('college_id','')) != cid:
            continue
        items.append(p)
    return jsonify({'items': items})

@app.get('/device_assignment')
def device_assignment():
    device_id = request.args.get('device_id','').strip()
    cid = _scoped_college_id(request.args.get('college_id',''))
    assigned = None
    for d in _devices.get('items', []):
        if str(d.get('device_id','')) == device_id and ((not cid) or str(d.get('college_id', '')) == cid):
            assigned = d
            break
    if assigned is None:
        plist = [p for p in _places.get('items', []) if not cid or str(p.get('college_id','')) == cid]
        if plist:
            p0 = plist[0]
            assigned = {'id': uuid.uuid4().hex[:12], 'device_id': device_id, 'college_id': str(p0.get('college_id','')), 'place_id': str(p0.get('id','')), 'place_name': str(p0.get('name',''))}
            _devices.setdefault('items', []).append(assigned)
            _save_devices()
    return jsonify({'assignment': assigned})

@app.post('/device_assign')
def device_assign():
    if _require_role(['SuperAdmin','CollegeAdmin']) is None:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'invalid body'}), 400
    device_id = str(data.get('device_id','')).strip()
    cid = _scoped_college_id(data.get('college_id',''))
    pid = str(data.get('place_id','')).strip()
    if device_id == '' or pid == '':
        return jsonify({'error': 'device_id and place_id required'}), 400
    place = None
    for p in _places.get('items', []):
        if str(p.get('id','')) == pid and (cid == '' or str(p.get('college_id','')) == cid):
            place = p
            break
    if place is None:
        return jsonify({'error': 'place not found'}), 404
    idx = None
    for i, d in enumerate(_devices.get('items', [])):
        if str(d.get('device_id','')) == device_id:
            idx = i
            break
    rec = {'id': (uuid.uuid4().hex[:12] if idx is None else _devices['items'][idx].get('id','')), 'device_id': device_id, 'college_id': str(place.get('college_id','')), 'place_id': pid, 'place_name': str(place.get('name',''))}
    if idx is None:
        _devices.setdefault('items', []).append(rec)
    else:
        _devices['items'][idx] = rec
    _save_devices()
    return jsonify({'ok': True, 'assignment': rec})

@app.post('/student_check_event')
def student_check_event():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD','Faculty'])
    if u is None:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'invalid body'}), 400
    sid = str(data.get('student_id','')).strip()
    evt = str(data.get('event','')).strip().lower()
    lat = data.get('lat', None)
    lng = data.get('lng', None)
    acc = data.get('accuracy', None)
    place = str(data.get('place','')).strip()
    device_id = str(data.get('device_id','')).strip()
    if sid == '' or evt not in ('check_in','check_out'):
        return jsonify({'error': 'student_id and valid event required'}), 400
    try:
        lat = float(lat); lng = float(lng)
    except Exception:
        return jsonify({'error': 'lat/lng required'}), 400
    college_id = _scoped_college_id(str(data.get('college_id', '')))
    if not any(str(s.get('id', '')) == sid and ((not college_id) or str(s.get('college_id', '')) == college_id) for s in _students.get('items', [])):
        return jsonify({'error': 'student not found in this business'}), 404
    ts = time.time()
    rec = {
        'id': uuid.uuid4().hex[:12],
        'student_id': sid,
        'college_id': college_id,
        'event': evt,
        'lat': lat,
        'lng': lng,
        'accuracy': (float(acc) if isinstance(acc, (int, float)) else None),
        'place': place,
        'device_id': device_id,
        'timestamp': ts,
        'ip': request.remote_addr
    }
    _check_events.setdefault('items', []).append(rec)
    _save_check_events()
    return jsonify({'ok': True, 'id': rec['id']})

@app.get('/student_check_events')
def student_check_events():
    sid = request.args.get('student_id','').strip()
    if not sid:
        return jsonify({'error': 'student_id required'}), 400
    cid = _scoped_college_id(request.args.get('college_id', ''))
    items = [r for r in _check_events.get('items', []) if str(r.get('student_id','')) == sid and ((not cid) or str(r.get('college_id','')) == cid)]
    items.sort(key=lambda r: float(r.get('timestamp', 0.0)), reverse=True)
    return jsonify({'items': items})

@app.get('/sessions_by_college')
def sessions_by_college():
    cid = _scoped_college_id(request.args.get('college_id', ''))
    items = []
    for s in _sessions.get('items', []):
        if cid == '' or str(s.get('college_id','')) == cid:
            items.append(s)
    return jsonify({'items': items})

@app.post('/session_lock')
def session_lock():
    u = _require_role(['SuperAdmin'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    sid = str(data.get('id','')).strip()
    for s in _sessions.get('items', []):
        if str(s.get('id','')) == sid:
            s['locked'] = True
            _save_sessions()
            return jsonify({'ok': True})
    return jsonify({'error': 'session not found'}), 404

@app.get('/platform_overview')
def platform_overview():
    now = time.time()
    today_str = time.strftime('%Y-%m-%d', time.localtime(now))
    total_colleges = len(_colleges.get('items', []))
    total_sessions = len(_sessions.get('items', []))
    total_sessions_today = sum(1 for s in _sessions.get('items', []) if str(s.get('date','')) == today_str)
    active_sessions = sum(1 for s in _sessions.get('items', []) if str(s.get('status','')) == 'Active')
    revenue_per_month = 0.0
    try:
        for c in _colleges.get('items', []):
            plan = _find_plan(str(c.get('subscription_plan','')))
            price = float(plan.get('price', 0.0)) if plan else 0.0
            revenue_per_month += price
    except Exception:
        pass
    mk = _month_key(now)
    per_college_sessions = {}
    for s in _sessions.get('items', []):
        if str(s.get('month','')) == mk:
            cid = str(s.get('college_id',''))
            per_college_sessions[cid] = per_college_sessions.get(cid, 0) + 1
    most_active_college = ''
    most_count = 0
    for cid, cnt in per_college_sessions.items():
        if cnt > most_count:
            most_count = cnt
            most_active_college = cid
    return jsonify({
        'total_colleges': total_colleges,
        'total_sessions': total_sessions,
        'total_sessions_today': total_sessions_today,
        'active_sessions': active_sessions,
        'revenue_per_month': revenue_per_month,
        'most_active_college': most_active_college
    })

_load_store()
_load_mt()
_bootstrap_superadmin()

def _remove_duplicate_from_others(target_name: str, v: np.ndarray, thr: float = 0.995):
    try:
        vv = _normalize(v)
        for i in range(len(_store['items']) - 1, -1, -1):
            it = _store['items'][i]
            n = str(it.get('name', '')).strip()
            if n == str(target_name).strip():
                continue
            changed = False
            vecs = it.get('vecs', [])
            if isinstance(vecs, list):
                keep = []
                for r in vecs:
                    rr = np.array(r['v'] if isinstance(r, dict) else r, dtype=np.float32)
                    if rr.size == vv.size and float(np.dot(_normalize(rr), vv)) >= thr:
                        changed = True
                    else:
                        keep.append(r)
                it['vecs'] = keep
            if 'vec' in it:
                rr = np.array(it['vec'], dtype=np.float32)
                if rr.size == vv.size and float(np.dot(_normalize(rr), vv)) >= thr:
                    it.pop('vec', None)
                    changed = True
            if changed:
                if len(it.get('vecs', [])) == 0 and not it.get('vec') and len(it.get('aug_vecs', [])) == 0:
                    _store['items'].pop(i)
    except Exception:
        pass

def _fallback_embed(crop: npt.NDArray[np.uint8]) -> np.ndarray:
    try:
        # simple, deterministic embedding: resized grayscale + color hist
        small = cv2.resize(crop, (32, 32), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
        gvec = gray.flatten()
        # 8-bin per channel histogram
        hist_r = cv2.calcHist([small[:, :, 0]], [0], None, [8], [0, 256]).flatten()
        hist_g = cv2.calcHist([small[:, :, 1]], [0], None, [8], [0, 256]).flatten()
        hist_b = cv2.calcHist([small[:, :, 2]], [0], None, [8], [0, 256]).flatten()
        hist = np.concatenate([hist_r, hist_g, hist_b]).astype(np.float32)
        hist = hist / (np.sum(hist) + 1e-6)
        v = np.concatenate([gvec, hist]).astype(np.float32)
        return _normalize(v)
    except Exception:
        return np.zeros((0,), dtype=np.float32)

def _mild_upscale(rgb: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
    try:
        h, w = rgb.shape[:2]
        if max(h, w) >= 1080:
            return rgb
        scale = min(1080.0 / max(h, w), 2.0)
        out = cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LANCZOS4)
        blur = cv2.GaussianBlur(out, (0, 0), 0.8)
        out = cv2.addWeighted(out, 1.08, blur, -0.08, 0)
        return out
    except Exception:
        return rgb

_recent = deque(maxlen=4)  # store recent [{'embeddings': [np.ndarray], 'names': [str]}]
_tracks = []  # [{'id': int, 'vec': np.ndarray, 'ts': float}]
_next_id = 1
_track_overrides = {}  # track_id -> {'name': str, 'expires': float}
_chunks = deque(maxlen=40)

def _portrait_crop(rgb: npt.NDArray[np.uint8], box: dict, scale: float = 3.0, margin: float = 0.5) -> npt.NDArray[np.uint8]:
    try:
        h, w = rgb.shape[:2]
        x1 = int(box.get('x1', 0)); y1 = int(box.get('y1', 0)); x2 = int(box.get('x2', 0)); y2 = int(box.get('y2', 0))
        face_w = max(1, x2 - x1)
        face_h = max(1, y2 - y1)
        cx = (x1 + x2) // 2
        top = max(0, int(y1 - margin * face_h))
        bottom = int(y1 + scale * face_h)
        left = max(0, int(cx - (0.5 + margin) * face_w))
        right = int(cx + (0.5 + margin) * face_w)
        top = max(0, top); left = max(0, left)
        bottom = min(h - 1, bottom); right = min(w - 1, right)
        if bottom <= top or right <= left:
            return rgb
        return rgb[top:bottom, left:right]
    except Exception:
        return rgb

def _augment_only(rgb: npt.NDArray[np.uint8], count: int = 6):
    thumbs = []
    if rgb is None or rgb.size == 0:
        return thumbs
    try:
        img0 = rgb.copy()
        try:
            import albumentations as A
            aug = A.Compose([
                A.HorizontalFlip(p=0.5),
                A.RandomBrightnessContrast(brightness_limit=0.25, contrast_limit=0.25, p=0.7),
                A.GaussianBlur(blur_limit=3, p=0.4),
                A.Rotate(limit=15, border_mode=cv2.BORDER_REFLECT_101, p=0.6),
                A.CLAHE(p=0.4)
            ])
            for i in range(count):
                out = aug(image=img0)['image']
                thumbs.append(to_data_uri(out))
        except Exception:
            h, w = img0.shape[:2]
            for i in range(count):
                img = img0.copy()
                if i % 2 == 0:
                    img = cv2.flip(img, 1)
                alpha = 1.0 + (np.random.rand() * 0.3 - 0.15)
                beta = (np.random.rand() * 20 - 10)
                img = cv2.convertScaleAbs(img, alpha=alpha, beta=beta)
                ang = int(np.random.rand() * 20 - 10)
                M = cv2.getRotationMatrix2D((w//2, h//2), ang, 1.0)
                img = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REFLECT_101)
                thumbs.append(to_data_uri(img))
    except Exception:
        pass
    return thumbs

def _ensure_label_item(name: str, dim: int, college_id: str = '') -> int:
    dst_idx = None
    for i, it in enumerate(_store['items']):
        if str(it.get('name','')).strip() == name and str(it.get('college_id','')) == str(college_id):
            dst_idx = i
            break
    if dst_idx is None:
        _store['items'].append({'name': name, 'vecs': [], 'dim': int(dim), 'aug_vecs': [], 'college_id': str(college_id)})
        dst_idx = len(_store['items']) - 1
    return dst_idx

def _merge_vec_into_label(name: str, v: np.ndarray, aug_thumbs: list, thumb: str = '', college_id: str = ''):
    try:
        v = _normalize(np.array(v, dtype=np.float32))
        if v.size == 0:
            try:
                app.logger.info(f"[ML] skip merge: empty vector for '{name}'")
            except Exception:
                return
        dst_idx = _ensure_label_item(name, int(v.size), college_id)
        it = _store['items'][dst_idx]
        it.setdefault('vecs', [])
        # deduplicate against existing
        try:
            dup = False
            for r in it['vecs']:
                rr = np.array(r['v'] if isinstance(r, dict) else r, dtype=np.float32)
                if rr.size == v.size and float(np.dot(_normalize(rr), v)) >= 0.995:
                    dup = True; break
            if 'vec' in it:
                rr = np.array(it['vec'], dtype=np.float32)
                if rr.size == v.size and float(np.dot(_normalize(rr), v)) >= 0.995:
                    dup = True
            if not dup:
                rid = uuid.uuid4().hex[:12]
                it['vecs'].append({'id': rid, 'v': v.tolist()})
                try:
                    app.logger.info(f"[ML] merged vector into '{name}' dim={v.size} id={rid}")
                except Exception:
                    pass
            else:
                try:
                    app.logger.info(f"[ML] deduped vector for '{name}' dim={v.size}")
                except Exception:
                    pass
        except Exception:
            rid = uuid.uuid4().hex[:12]
            it['vecs'].append({'id': rid, 'v': v.tolist()})
        if STORE_THUMBS and thumb:
            if not it.get('thumb'):
                it['thumb'] = thumb
        if STORE_THUMBS and aug_thumbs:
            it.setdefault('aug_thumbs', [])
            it['aug_thumbs'].extend(list(aug_thumbs))
        # embed aug thumbs (data URIs) and append to aug_vecs
        if aug_thumbs:
            it.setdefault('aug_vecs', [])
            added_aug = 0
            for uri in aug_thumbs:
                try:
                    rgb = _data_uri_to_rgb(str(uri))
                    emb = detect_app.embedder.embed(rgb) if (rgb is not None and rgb.size > 0) else np.zeros((0,), dtype=np.float32)
                    if emb.size == v.size:
                        it['aug_vecs'].append(_normalize(emb).tolist())
                        added_aug += 1
                except Exception:
                    continue
            try:
                app.logger.info(f"[ML] added {added_aug} aug embeddings for '{name}'")
            except Exception:
                pass
        try:
            _remove_duplicate_from_others(name, v, thr=0.99)
        except Exception:
            pass
    except Exception:
        pass

def _assign_tracks(curr_vecs):
    global _next_id, _tracks
    ids = []
    now_ts = time.time()
    for v in curr_vecs:
        best_id = None
        best_sim = 0.0
        for t in _tracks:
            sim = float(np.dot(_normalize(v), _normalize(t['vec'])))
            if sim > best_sim:
                best_sim = sim; best_id = t['id']
        if best_id is not None and best_sim >= 0.85:
            for t in _tracks:
                if t['id'] == best_id:
                    t['vec'] = v; t['ts'] = now_ts
                    break
            ids.append(best_id)
        else:
            tid = _next_id; _next_id += 1
            _tracks.append({'id': tid, 'vec': v, 'ts': now_ts})
            ids.append(tid)
    _tracks = [t for t in _tracks if now_ts - t['ts'] < 60.0]
    return ids

def _spoof_score(crop: npt.NDArray[np.uint8]) -> float:
    try:
        if _silentface_torch is not None and _silentface_model_path is not None:
            img = cv2.resize(crop, (80, 80), interpolation=cv2.INTER_AREA)
            res = _silentface_torch.predict(img, _silentface_model_path)
            if isinstance(res, np.ndarray) and res.size >= 2:
                prob_live = float(res[0][1]) / 2.0
                return float(np.clip(prob_live, 0.0, 1.0))
        if _silentface_net is not None:
            img = cv2.resize(crop, (80, 80), interpolation=cv2.INTER_AREA)
            blob = cv2.dnn.blobFromImage(img, scalefactor=1.0/255.0, size=(80, 80), mean=(0.5, 0.5, 0.5), swapRB=True, crop=True)
            _silentface_net.setInput(blob)
            out = _silentface_net.forward()
            if out.ndim == 2 and out.shape[1] >= 2:
                logits = out[0].astype(np.float32)
                exps = np.exp(logits - np.max(logits))
                probs = exps / np.sum(exps)
                return float(probs[1])
            elif out.ndim == 2 and out.shape[1] == 1:
                p = float(out[0][0])
                return float(np.clip(p, 0.0, 1.0))
        if _minifasnet_session is not None:
            sz = 80
            img = cv2.resize(crop, (sz, sz), interpolation=cv2.INTER_AREA)
            img = img.astype(np.float32) / 255.0
            mean = np.array([0.5, 0.5, 0.5], dtype=np.float32)
            std = np.array([0.5, 0.5, 0.5], dtype=np.float32)
            img = (img - mean) / std
            x = np.transpose(img, (2, 0, 1))[None, ...]
            inp = { _minifasnet_session.get_inputs()[0].name: x }
            out = _minifasnet_session.run(None, inp)[0]
            if out.ndim == 2 and out.shape[1] >= 2:
                # assume [spoof, live] logits
                logits = out[0].astype(np.float32)
                exps = np.exp(logits - np.max(logits))
                probs = exps / np.sum(exps)
                return float(probs[1])
            elif out.ndim == 2 and out.shape[1] == 1:
                p = float(out[0][0])
                return float(np.clip(p, 0.0, 1.0))
        g = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        lap = cv2.Laplacian(g, cv2.CV_32F)
        v1 = float(np.var(lap))
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        s = float(np.mean(hsv[:, :, 1])) / 255.0
        b = float(np.mean(g)) / 255.0
        x = 0.5 * (np.tanh((v1 - 150.0) / 80.0) + 1.0)
        y = 0.5 * (np.tanh((s - 0.25) / 0.15) + 1.0)
        z = 1.0 - abs(b - 0.5)
        score = float(np.clip(0.4 * x + 0.4 * y + 0.2 * z, 0.0, 1.0))
        return score
    except Exception:
        return 0.5

def _mesh_abs(crop: npt.NDArray[np.uint8], box: dict) -> list:
    if _mp_face_mesh is None:
        return []
    try:
        h, w = crop.shape[:2]
        res = _mp_face_mesh.process(crop)
        if not res.multi_face_landmarks:
            return []
        lm = res.multi_face_landmarks[0].landmark
        sx = int(box['x1']); sy = int(box['y1'])
        sw = int(box['x2'] - box['x1']); sh = int(box['y2'] - box['y1'])
        pts = []
        for p in lm:
            x = sx + int(p.x * w)
            y = sy + int(p.y * h)
            z = float(p.z)
            pts.append({'x': x, 'y': y, 'z': z})
        return pts
    except Exception:
        return []

def _read_request_image():
    try:
        if request.files:
            f = None
            if 'image' in request.files:
                f = request.files['image']
            elif 'file' in request.files:
                f = request.files['file']
            else:
                # take first file if present
                try:
                    key = next(iter(request.files.keys()))
                    f = request.files[key]
                except Exception:
                    f = None
            if f is not None:
                data = f.read()
                arr = np.frombuffer(data, dtype=np.uint8)
                bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if bgr is not None:
                    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        ctype = (request.content_type or '').lower()
        if ctype.startswith('image/'):
            arr = np.frombuffer(request.get_data(cache=False), dtype=np.uint8)
            bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if bgr is not None:
                return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if 'octet-stream' in ctype:
            arr = np.frombuffer(request.get_data(cache=False), dtype=np.uint8)
            bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if bgr is not None:
                return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if ctype.startswith('application/json'):
            data = request.get_json(silent=True) or {}
            img = data.get('image', '')
            if isinstance(img, str) and img:
                try:
                    if img.startswith('data:image'):
                        rgb = _data_uri_to_rgb(img)
                        if rgb is not None and rgb.size > 0:
                            return rgb
                    else:
                        arr = np.frombuffer(base64.b64decode(img), dtype=np.uint8)
                        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if bgr is not None:
                            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                except Exception:
                    pass
        # fallback: some clients send base64 image in form field
        if request.form:
            img = request.form.get('image') or request.form.get('file') or ''
            if isinstance(img, str) and img:
                try:
                    if img.startswith('data:image'):
                        rgb = _data_uri_to_rgb(img)
                        if rgb is not None and rgb.size > 0:
                            return rgb
                    else:
                        arr = np.frombuffer(base64.b64decode(img), dtype=np.uint8)
                        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if bgr is not None:
                            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                except Exception:
                    pass
    except Exception:
        pass
    return None

@app.post('/detect')
def detect():
    rgb = _read_request_image()
    if rgb is None:
        return jsonify({'error': 'missing or invalid image'}), 400
    mode = request.form.get('mode') or (request.get_json(silent=True) or {}).get('mode') or 'fast'
    enhancer = request.form.get('enhancer') or (request.get_json(silent=True) or {}).get('enhancer') or 'GFPGAN'
    preclean_val = request.form.get('preclean') or (request.get_json(silent=True) or {}).get('preclean')
    preclean = str(preclean_val).lower() == 'true' if isinstance(preclean_val, str) else bool(preclean_val)
    try:
        lvl_s = request.form.get('preclean_level') or (request.get_json(silent=True) or {}).get('preclean_level') or '0.4'
        lvl = float(lvl_s)
    except Exception:
        lvl = 0.4
    college_id = _scoped_college_id(request.form.get('college_id') or (request.get_json(silent=True) or {}).get('college_id') or '')
    ai_thr = 0.8
    if college_id:
        col = _find_college(college_id)
        if col is not None:
            try:
                ai_thr = float(col.get('ai_threshold', ai_thr))
            except Exception:
                ai_thr = 0.8
    if mode == 'fast':
        enhancer = 'OpenCV'
        preclean = False
        det_max_side = 720
        crop_mode = 'Face'
        gfp_up = 1
        cf_w = 0.0
        portrait_scale = 2.5
        enhance_level = 0.35
        do_mild_upscale = False
    elif mode == 'quality_plus':
        enhancer = 'GFPGAN+CodeFormer'
        preclean = False
        det_max_side = 1280
        crop_mode = 'Portrait'
        gfp_up = 2
        cf_w = 0.25  # low strength
        portrait_scale = 3.0
        enhance_level = 0.5
        do_mild_upscale = True
    else:
        det_max_side = 1280
        crop_mode = 'Portrait'
        gfp_up = 2
        cf_w = 0.5
        portrait_scale = 3.0
        enhance_level = 0.5
        enhancer = 'GFPGAN'
        preclean = False
        do_mild_upscale = False

    if do_mild_upscale:
        rgb = _mild_upscale(rgb)
    annotated, crops, df, df_emb = detect_app.detect_faces(
        image_input=rgb,
        enhancer=enhancer,
        enhance_level=enhance_level,
        gfpgan_upscale=gfp_up,
        codeformer_w=cf_w,
        compute_embeddings=False,
        crop_mode=crop_mode,
        portrait_scale=portrait_scale,
        preclean_whole=preclean,
        preclean_level=lvl,
        det_max_side=det_max_side
    )
    boxes = []
    for i in range(len(df)):
        row = df.iloc[i]
        boxes.append({'x1': int(row['x1']), 'y1': int(row['y1']), 'x2': int(row['x2']), 'y2': int(row['y2']), 'score': float(row['score'])})
    # compute embeddings for each crop and try recognition
    embeddings = []
    names = []
    thumbs = []
    meshes = []
    spoofs = []
    cand_lists = []
    for c in crops:
        v = detect_app.embedder.embed(c)
        if v.size == 0:
            v = _fallback_embed(c)
        embeddings.append(v.tolist())
        if AUTO_TRAIN:
            _maybe_auto_train()
        v_np = np.array(v, dtype=np.float32)
        picked = None
        res2 = _search(v_np, topk=2, college_id=(college_id or None))
        if res2 and res2[0]['similarity'] >= ai_thr and (len(res2) == 1 or (res2[0]['similarity'] - res2[1]['similarity'] >= 0.04)):
            picked = res2[0]['name']
        names.append(picked if picked else 'Unknown')
        # always build search candidate list for global unique assignment
        cand_lists.append(_search(v_np, topk=5, college_id=(college_id or None)))
        try:
            thumbs.append(to_data_uri(c))
        except Exception:
            thumbs.append('')
    for i, c in enumerate(crops):
        meshes.append(_mesh_abs(c, boxes[i]) if i < len(boxes) else [])
        spoofs.append(_spoof_score(c))
    # aggregate across recent shots to stabilize names
    try:
        curr_vecs = [np.array(v, dtype=np.float32) for v in embeddings]
        agg_names = names[:]
        for rec in list(_recent):
            prev_vecs = rec.get('embeddings', [])
            prev_names = rec.get('names', [])
            for i, v in enumerate(curr_vecs):
                best_name = None
                best_sim = -1.0
                for j, u in enumerate(prev_vecs):
                    sim = float(np.dot(_normalize(v), _normalize(np.array(u, dtype=np.float32))))
                    if sim > best_sim:
                        best_sim = sim
                        best_name = prev_names[j] if j < len(prev_names) else None
                if best_name and best_name != 'Unknown' and best_sim >= 0.8:
                    agg_names[i] = best_name
        names = agg_names
        _recent.append({'embeddings': curr_vecs, 'names': names})
    except Exception:
        pass
    # enforce unique name per frame using greedy assignment on cosine similarity
    try:
        uniq = _unique_assign_from_candidates(cand_lists, min_sim=float(ai_thr))
        # if a detection had no confident candidate, keep previous name if it doesn't collide
        used = set()
        for nm in uniq:
            if nm != 'Unknown':
                used.add(nm)
        for i in range(len(names)):
            if uniq[i] != 'Unknown':
                names[i] = uniq[i]
            else:
                if names[i] in used:
                    names[i] = 'Unknown'
                elif names[i] != 'Unknown':
                    used.add(names[i])
    except Exception:
        pass
    track_ids = _assign_tracks(curr_vecs)
    try:
        now = time.time()
        for i, tid in enumerate(track_ids):
            ov = _track_overrides.get(int(tid))
            if ov and now < float(ov.get('expires', 0.0)):
                names[i] = str(ov.get('name', names[i]))
    except Exception:
        pass
    image_uri = to_data_uri(annotated[0])
    try:
        portraits = []
        aug_lists = []
        for i in range(len(crops)):
            try:
                portraits.append(to_data_uri(_portrait_crop(rgb, boxes[i], scale=3.0, margin=0.5)))
            except Exception:
                portraits.append('')
            try:
                aug_lists.append(_augment_only(crops[i], count=6))
            except Exception:
                aug_lists.append([])
        cid = uuid.uuid4().hex[:12]
        rec = {'id': cid, 'ts': time.time(), 'college_id': (college_id or ''), 'names': names, 'thumbs': thumbs, 'aug_thumbs': aug_lists, 'portraits': portraits, 'image': image_uri, 'embeddings': embeddings, 'boxes': boxes, 'mesh': meshes, 'finalized': False}
        _chunks.append(rec)
        try:
            if any((n and n != 'Unknown') for n in names):
                _append_chunk_disk(rec)
        except Exception:
            pass
        if AUTO_LEARN_CHUNKS:
            try:
                for i, nm in enumerate(names):
                    if not nm or nm == 'Unknown':
                        continue
                    vec = np.array(embeddings[i], dtype=np.float32) if i < len(embeddings) else np.zeros((0,), dtype=np.float32)
                    augt = aug_lists[i] if i < len(aug_lists) else []
                    th = thumbs[i] if i < len(thumbs) else ''
                    _merge_vec_into_label(str(nm), vec, augt, thumb=th, college_id=(college_id or ''))
                _save_store()
                try:
                    _recent.clear()
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        cid = ''
    return jsonify({'boxes': boxes, 'image': image_uri, 'embeddings': embeddings, 'names': names, 'crops': thumbs, 'tracks': track_ids, 'mesh': meshes, 'spoof': spoofs, 'chunk': cid})

@app.post('/detect_quick')
def detect_quick():
    rgb = _read_request_image()
    if rgb is None:
        return jsonify({'error': 'missing or invalid image'}), 400
    college_id = _scoped_college_id(request.form.get('college_id') or (request.get_json(silent=True) or {}).get('college_id') or '')
    ai_thr = 0.8
    if college_id:
        col = _find_college(college_id)
        if col is not None:
            try:
                ai_thr = float(col.get('ai_threshold', ai_thr))
            except Exception:
                ai_thr = 0.8
    enhancer = 'OpenCV'
    det_max_side = 720
    crop_mode = 'Face'
    gfp_up = 1
    cf_w = 0.0
    portrait_scale = 2.5
    enhance_level = 0.35
    # quick mode does not upscale
    annotated, crops, df, df_emb = detect_app.detect_faces(
        image_input=rgb,
        enhancer=enhancer,
        enhance_level=enhance_level,
        gfpgan_upscale=gfp_up,
        codeformer_w=cf_w,
        compute_embeddings=False,
        crop_mode=crop_mode,
        portrait_scale=portrait_scale,
        preclean_whole=False,
        preclean_level=0.0,
        det_max_side=det_max_side
    )
    boxes = []
    for i in range(len(df)):
        row = df.iloc[i]
        boxes.append({'x1': int(row['x1']), 'y1': int(row['y1']), 'x2': int(row['x2']), 'y2': int(row['y2']), 'score': float(row['score'])})
    embeddings = []
    names = []
    thumbs = []
    meshes = []
    spoofs = []
    cand_lists = []
    for c in crops:
        v = detect_app.embedder.embed(c)
        if v.size == 0:
            v = _fallback_embed(c)
        embeddings.append(v.tolist())
        if AUTO_TRAIN:
            _maybe_auto_train()
        v_np = np.array(v, dtype=np.float32)
        picked = None
        res2 = _search(v_np, topk=2, college_id=(college_id or None))
        if res2 and res2[0]['similarity'] >= ai_thr and (len(res2) == 1 or (res2[0]['similarity'] - res2[1]['similarity'] >= 0.04)):
            picked = res2[0]['name']
        names.append(picked if picked else 'Unknown')
        cand_lists.append(_search(v_np, topk=5, college_id=(college_id or None)))
        try:
            thumbs.append(to_data_uri(c))
        except Exception:
            thumbs.append('')
    for i, c in enumerate(crops):
        meshes.append(_mesh_abs(c, boxes[i]) if i < len(boxes) else [])
        spoofs.append(_spoof_score(c))
    try:
        curr_vecs = [np.array(v, dtype=np.float32) for v in embeddings]
        _recent.append({'embeddings': curr_vecs, 'names': names})
    except Exception:
        pass
    try:
        uniq = _unique_assign_from_candidates(cand_lists, min_sim=float(ai_thr))
        used = set(nm for nm in uniq if nm != 'Unknown')
        for i in range(len(names)):
            if uniq[i] != 'Unknown':
                names[i] = uniq[i]
            else:
                if names[i] in used:
                    names[i] = 'Unknown'
                elif names[i] != 'Unknown':
                    used.add(names[i])
    except Exception:
        pass
    track_ids = _assign_tracks(curr_vecs)
    try:
        now = time.time()
        for i, tid in enumerate(track_ids):
            ov = _track_overrides.get(int(tid))
            if ov and now < float(ov.get('expires', 0.0)):
                names[i] = str(ov.get('name', names[i]))
    except Exception:
        pass
    image_uri = to_data_uri(annotated[0])
    try:
        portraits = []
        aug_lists = []
        for i in range(len(crops)):
            try:
                portraits.append(to_data_uri(_portrait_crop(rgb, boxes[i], scale=3.0, margin=0.5)))
            except Exception:
                portraits.append('')
            try:
                aug_lists.append(_augment_only(crops[i], count=6))
            except Exception:
                aug_lists.append([])
        cid = uuid.uuid4().hex[:12]
        rec = {'id': cid, 'ts': time.time(), 'college_id': (college_id or ''), 'names': names, 'thumbs': thumbs, 'aug_thumbs': aug_lists, 'portraits': portraits, 'image': image_uri, 'embeddings': embeddings, 'boxes': boxes, 'mesh': meshes, 'finalized': False}
        _chunks.append(rec)
        try:
            if any((n and n != 'Unknown') for n in names):
                _append_chunk_disk(rec)
        except Exception:
            pass
        if AUTO_LEARN_CHUNKS:
            try:
                for i, nm in enumerate(names):
                    if not nm or nm == 'Unknown':
                        continue
                    vec = np.array(embeddings[i], dtype=np.float32) if i < len(embeddings) else np.zeros((0,), dtype=np.float32)
                    augt = aug_lists[i] if i < len(aug_lists) else []
                    th = thumbs[i] if i < len(thumbs) else ''
                    _merge_vec_into_label(str(nm), vec, augt, thumb=th, college_id=(college_id or ''))
                _save_store()
                try:
                    _recent.clear()
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        cid = ''
    return jsonify({'boxes': boxes, 'image': image_uri, 'embeddings': embeddings, 'names': names, 'crops': thumbs, 'tracks': track_ids, 'mesh': meshes, 'spoof': spoofs, 'chunk': cid})

@app.get('/chunks')
def chunks():
    items = []
    try:
        mem = list(_chunks)[::-1]
        if mem:
            for c in mem:
                if not bool(c.get('finalized', False)):
                    continue
                cnt = int(len(c.get('thumbs', []))) + int(sum(len(x) for x in c.get('aug_thumbs', []) if isinstance(x, list))) + int(len(c.get('portraits', [])))
                items.append({'id': c.get('id',''), 'ts': float(c.get('ts',0.0)), 'count': cnt, 'names': list({str(n) for n in c.get('names', [])}), 'image': (c.get('image','') if STORE_THUMBS else '')})
        else:
            items = _read_chunks_log(limit=40)
    except Exception:
        items = []
    return jsonify({'items': items})

@app.get('/chunk_images')
def chunk_images():
    cid = request.args.get('id', '').strip()
    def _convert(c):
        items = c.get('thumbs', [])
        names = c.get('names', [])
        portraits = c.get('portraits', [])
        aug_lists = c.get('aug_thumbs', [])
        emb = c.get('embeddings', [])
        mesh = c.get('mesh', [])
        boxes = c.get('boxes', [])
        aug_flat, aug_names = [], []
        try:
            for i, lst in enumerate(aug_lists or []):
                if not isinstance(lst, list):
                    continue
                for im in lst:
                    aug_flat.append(im)
                    aug_names.append(names[i] if i < len(names) else '')
        except Exception:
            pass
        return {
            'items': items,
            'names': names,
            'count': int(len(items)),
            'portraits': portraits,
            'portraits_names': names,
            'augments': aug_flat,
            'augments_names': aug_names,
            'image': (c.get('image','') if STORE_THUMBS else ''),
            'embeddings': emb,
            'mesh': mesh,
            'boxes': boxes
        }
    for c in list(_chunks)[::-1]:
        if str(c.get('id','')) == cid:
            return jsonify(_convert(c))
    disk = _find_chunk_disk(cid)
    if disk is not None:
        return jsonify(_convert(disk))
    return jsonify({'items': []})

@app.post('/delete_by_chunk')
def delete_by_chunk():
    if _require_role(['SuperAdmin','CollegeAdmin','HOD']) is None:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True)
    if not data or 'id' not in data or 'name' not in data:
        return jsonify({'error': 'id and name required'}), 400
    cid = str(data['id']).strip()
    name = str(data['name']).strip()
    indices = data.get('indices', [])
    try:
        thr = float(data.get('thr', 0.995))
    except Exception:
        thr = 0.995
    if not indices or name == '' or cid == '':
        return jsonify({'error': 'invalid request'}), 400
    # find chunk in memory or disk
    chunk = None
    for c in list(_chunks)[::-1]:
        if str(c.get('id','')) == cid:
            chunk = c; break
    if chunk is None:
        chunk = _find_chunk_disk(cid)
    if chunk is None:
        return jsonify({'error': 'chunk not found'}), 404
    emb_list = chunk.get('embeddings', [])
    chunk_cid = str(chunk.get('college_id',''))
    removed = 0
    # find target label
    target = None
    for it in _store.get('items', []):
        if str(it.get('name','')).strip() == name and str(it.get('college_id','')) == chunk_cid:
            target = it; break
    if target is None:
        return jsonify({'ok': True, 'removed': 0})
    keep = []
    vecs = target.get('vecs', [])
    for r in vecs:
        try:
            rv = np.array(r['v'] if isinstance(r, dict) else r, dtype=np.float32)
            rv = _normalize(rv)
            sim_bad = False
            for idx in indices:
                try:
                    v = _normalize(np.array(emb_list[int(idx)], dtype=np.float32))
                    if v.size == rv.size and float(np.dot(rv, v)) >= thr:
                        sim_bad = True; break
                except Exception:
                    continue
            if sim_bad:
                removed += 1
            else:
                keep.append(r)
        except Exception:
            keep.append(r)
    target['vecs'] = keep
    # optional: also prune aug_vecs similarly with slightly lower thr
    try:
        pruned_aug = []
        for vv in target.get('aug_vecs', []):
            try:
                rv = _normalize(np.array(vv, dtype=np.float32))
                sim_bad = False
                for idx in indices:
                    v = _normalize(np.array(emb_list[int(idx)], dtype=np.float32))
                    if v.size == rv.size and float(np.dot(rv, v)) >= max(0.99, thr - 0.005):
                        sim_bad = True; break
                if sim_bad:
                    removed += 1
                else:
                    pruned_aug.append(vv)
            except Exception:
                pruned_aug.append(vv)
        target['aug_vecs'] = pruned_aug
    except Exception:
        pass
    _save_store()
    try:
        app.logger.info(f"[ML] cleanup: removed {removed} vectors from '{name}' via chunk {cid} indices={indices}")
        _train_classifier(max_epochs=8)
    except Exception:
        pass
    return jsonify({'ok': True, 'removed': int(removed)})

@app.post('/finalize_chunk')
def finalize_chunk():
    if _require_role(['SuperAdmin','CollegeAdmin','HOD']) is None:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True)
    if not data or 'id' not in data:
        return jsonify({'error': 'id required'}), 400
    cid = str(data['id']).strip()
    names_override = data.get('names', None)
    if isinstance(names_override, list):
        names_override = [str(x or '').strip() for x in names_override]
    # find chunk
    chunk = None
    for c in list(_chunks)[::-1]:
        if str(c.get('id','')) == cid:
            chunk = c; break
    if chunk is None:
        chunk = _find_chunk_disk(cid)
    if chunk is None:
        return jsonify({'error': 'chunk not found'}), 404
    names = names_override if (isinstance(names_override, list) and len(names_override) > 0) else chunk.get('names', [])
    embeddings = chunk.get('embeddings', [])
    aug_lists = chunk.get('aug_thumbs', [])
    thumbs = chunk.get('thumbs', [])
    college_id = str(chunk.get('college_id',''))
    added = 0
    for i, nm in enumerate(names):
        if not nm or nm == 'Unknown':
            continue
        try:
            v = np.array(embeddings[i], dtype=np.float32)
            augt = aug_lists[i] if i < len(aug_lists) else []
        except Exception:
            continue
        th = thumbs[i] if i < len(thumbs) else ''
        _merge_vec_into_label(str(nm), v, augt, thumb=th, college_id=college_id)
        added += 1
    # update in-memory chunk names so later browsing reflects reviewed labels
    try:
        if chunk is not None and isinstance(names_override, list) and len(names_override) == len(chunk.get('names', [])):
            chunk['names'] = names_override
            chunk['finalized'] = True
    except Exception:
        pass
    try:
        if chunk is not None:
            obj = dict(chunk)
            obj['names'] = names
            obj['finalized'] = True
            _append_chunk_disk(obj)
    except Exception:
        pass
    _save_store()
    try:
        app.logger.info(f"[ML] finalize: merged {added} detections from chunk {cid}")
        _train_classifier(max_epochs=12)
    except Exception:
        pass
    return jsonify({'ok': True, 'merged': int(added)})
@app.post('/label')
def label():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    if not data or 'name' not in data or 'vector' not in data:
        return jsonify({'error': 'name and vector required'}), 400
    name = str(data['name']).strip()
    vec = np.array(data['vector'], dtype=np.float32)
    college_id = _scoped_college_id(data.get('college_id',''))
    if u.get('role') != 'SuperAdmin' and college_id != str(u.get('college_id','')):
        return jsonify({'error': 'forbidden'}), 403
    if name == '' or vec.size == 0:
        return jsonify({'error': 'invalid name or vector'}), 400
    v = _normalize(vec)
    thumb = str(data.get('thumb', '') or '')
    aug_thumbs, aug_vecs = [], []
    try:
        rgb = _data_uri_to_rgb(thumb)
        aug_thumbs, aug_vecs = _augment_and_embed(rgb, count=10)
    except Exception:
        pass
    if STORE_THUMBS:
        rid = uuid.uuid4().hex[:12]
        _store['items'].append({'name': name, 'vec': v.tolist(), 'vecs': [{'id': rid, 'v': v.tolist()}], 'dim': int(v.size), 'thumb': thumb, 'aug_thumbs': aug_thumbs, 'aug_vecs': aug_vecs, 'college_id': college_id})
    else:
        rid = uuid.uuid4().hex[:12]
        _store['items'].append({'name': name, 'vec': v.tolist(), 'vecs': [{'id': rid, 'v': v.tolist()}], 'dim': int(v.size), 'aug_vecs': aug_vecs, 'college_id': college_id})
    _save_store()
    try:
        _recent.clear()
    except Exception:
        pass
    return jsonify({'ok': True, 'count': len(_store['items'])})

@app.post('/merge_label')
def merge_label():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    if not data or 'name' not in data or 'vector' not in data:
        return jsonify({'error': 'name and vector required'}), 400
    name = str(data['name']).strip()
    vec = np.array(data['vector'], dtype=np.float32)
    thumb = str(data.get('thumb', '') or '')
    track_opt = data.get('track', None)
    college_id = _scoped_college_id(data.get('college_id',''))
    if u.get('role') != 'SuperAdmin' and college_id != str(u.get('college_id','')):
        return jsonify({'error': 'forbidden'}), 403
    if name == '' or vec.size == 0:
        return jsonify({'error': 'invalid name or vector'}), 400
    v = _normalize(vec)
    found = False
    dst_idx = None
    for i, it in enumerate(_store['items']):
        if str(it.get('name','')).strip() == name and str(it.get('college_id','')) == college_id:
            dst_idx = i
            break
    if dst_idx is not None:
        it = _store['items'][dst_idx]
        it.setdefault('vecs', [])
        # deduplicate: skip if extremely similar to existing
        try:
            existing = []
            for r in it['vecs']:
                rr = np.array(r['v'] if isinstance(r, dict) else r, dtype=np.float32)
                if rr.size == v.size:
                    existing.append(_normalize(rr))
            if 'vec' in it:
                u = np.array(it['vec'], dtype=np.float32)
                if u.size == v.size:
                    existing.append(_normalize(u))
            dup = False
            for rr in existing:
                if float(np.dot(v, rr)) >= 0.995:
                    dup = True
                    break
            if not dup:
                rid = uuid.uuid4().hex[:12]
                it['vecs'].append({'id': rid, 'v': v.tolist()})
        except Exception:
            rid = uuid.uuid4().hex[:12]
            it['vecs'].append({'id': rid, 'v': v.tolist()})
        if thumb:
            it.setdefault('aug_vecs', [])
            try:
                remaining = max(0, 10 - len(it['aug_vecs']))
                if remaining > 0:
                    rgb = _data_uri_to_rgb(thumb)
                    aug_thumbs, aug_vecs = _augment_and_embed(rgb, count=remaining)
                    it['aug_vecs'].extend(aug_vecs)
                    if STORE_THUMBS:
                        it.setdefault('aug_thumbs', [])
                        it['aug_thumbs'].extend(aug_thumbs)
            except Exception:
                pass
        if STORE_THUMBS and thumb and not it.get('thumb'):
            it['thumb'] = thumb
        found = True
    if not found:
        aug_thumbs, aug_vecs = [], []
        try:
            rgb = _data_uri_to_rgb(thumb)
            aug_thumbs, aug_vecs = _augment_and_embed(rgb, count=10)
        except Exception:
            pass
        if STORE_THUMBS:
            rid = uuid.uuid4().hex[:12]
            _store['items'].append({'name': name, 'vec': v.tolist(), 'vecs': [{'id': rid, 'v': v.tolist()}], 'dim': int(v.size), 'thumb': thumb, 'aug_thumbs': aug_thumbs, 'aug_vecs': aug_vecs, 'college_id': college_id})
        else:
            rid = uuid.uuid4().hex[:12]
            _store['items'].append({'name': name, 'vec': v.tolist(), 'vecs': [{'id': rid, 'v': v.tolist()}], 'dim': int(v.size), 'aug_vecs': aug_vecs, 'college_id': college_id})
    try:
        _remove_duplicate_from_others(name, v)
    except Exception:
        pass
    _save_store()
    try:
        _recent.clear()
    except Exception:
        pass
    if TRAIN_ON_LABEL:
        try:
            app.logger.info("[ML] classifier: train requested after merge_label")
            _train_classifier(max_epochs=12)
        except Exception:
            pass
    try:
        if track_opt is not None:
            tid = int(track_opt)
            _track_overrides[tid] = {'name': name, 'expires': time.time() + 8.0}
    except Exception:
        pass
    return jsonify({'ok': True})

@app.post('/approve_match')
def approve_match():
    if _require_role(['SuperAdmin','CollegeAdmin','HOD']) is None:
        return jsonify({'error': 'forbidden'}), 403
    return merge_label()
@app.get('/labels')
def labels():
    cid = _scoped_college_id(request.args.get('college_id', ''))
    items = []
    for it in _store.get('items', []):
        if cid and str(it.get('college_id','')) != cid:
            continue
        items.append({'name': it.get('name',''), 'dim': int(it.get('dim', 0)), 'thumb': (it.get('thumb','') if STORE_THUMBS else '')})
    return jsonify({'items': items})

@app.post('/delete_label')
def delete_label():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    if not data or 'name' not in data:
        return jsonify({'error': 'name required'}), 400
    name = str(data['name']).strip()
    college_id = _scoped_college_id(data.get('college_id',''))
    # purge from chunks in memory
    try:
        mem = list(_chunks)
        for c in mem:
            c['names'] = [n for n in c.get('names', []) if str(n) != name]
    except Exception:
        pass
    # purge from chunks on disk
    try:
        if os.path.exists(CHUNKS_LOG_PATH):
            with open(CHUNKS_LOG_PATH, 'r') as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                try:
                    obj = json.loads(line)
                    if 'names' in obj:
                        obj['names'] = [n for n in obj.get('names', []) if str(n) != name]
                    new_lines.append(json.dumps(obj) + '\n')
                except Exception:
                    new_lines.append(line)
            with open(CHUNKS_LOG_PATH, 'w') as f:
                f.writelines(new_lines)
    except Exception:
        pass
    before = len(_store['items'])
    _store['items'] = [it for it in _store['items'] if not (str(it.get('name','')).strip() == name and str(it.get('college_id','')) == college_id)]
    _save_store()
    after = len(_store['items'])
    try:
        _recent.clear()
    except Exception:
        pass
    try:
        app.logger.info(f"[ML] delete_label: '{name}' removed; classifier invalidated")
        global _clf
        _clf = None
    except Exception:
        pass
    return jsonify({'ok': True, 'deleted': before - after})

@app.post('/rename_label')
def rename_label():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    if not data or 'old' not in data or 'new' not in data:
        return jsonify({'error': 'old and new required'}), 400
    old = str(data['old']).strip()
    new = str(data['new']).strip()
    if new == '':
        return jsonify({'error': 'invalid new name'}), 400
    vec_opt = np.array(data.get('vector', []), dtype=np.float32)
    thumb = str(data.get('thumb', '') or '')
    college_id = _scoped_college_id(data.get('college_id',''))
    if u.get('role') != 'SuperAdmin' and college_id != str(u.get('college_id','')):
        return jsonify({'error': 'forbidden'}), 403
    count = 0
    src_idx = None
    dst_idx = None
    cand_src = []
    for i, it in enumerate(_store['items']):
        n = str(it.get('name','')).strip()
        if n == old and str(it.get('college_id','')) == college_id:
            cand_src.append(i)
        if n == new and str(it.get('college_id','')) == college_id:
            dst_idx = i
    if vec_opt.size > 0 and cand_src:
        best_s, best_i = -1.0, None
        v = _normalize(vec_opt)
        for i in cand_src:
            it = _store['items'][i]
            vecs = []
            if 'vecs' in it and isinstance(it['vecs'], list):
                for r in it['vecs']:
                    rr = np.array(r['v'] if isinstance(r, dict) else r, dtype=np.float32)
                    if rr.size == v.size:
                        vecs.append(_normalize(rr))
            if 'vec' in it:
                u = np.array(it['vec'], dtype=np.float32)
                if u.size == v.size:
                    vecs.append(_normalize(u))
            if 'aug_vecs' in it and isinstance(it['aug_vecs'], list):
                for r in it['aug_vecs']:
                    rr = np.array(r, dtype=np.float32)
                    if rr.size == v.size:
                        vecs.append(_normalize(rr))
            if vecs:
                centroid = _normalize(np.mean(vecs, axis=0).astype(np.float32))
                s = float(np.dot(v, centroid))
                if s > best_s:
                    best_s, best_i = s, i
        src_idx = best_i
    elif cand_src:
        src_idx = cand_src[0]
    # If vector provided: move only the closest sample from source to destination
    if src_idx is not None and vec_opt.size > 0:
        v = _normalize(vec_opt)
        src = _store['items'][src_idx]
        # ensure destination exists
        if dst_idx is None:
            aug_thumbs, aug_vecs = [], []
            if thumb:
                try:
                    rgb = _data_uri_to_rgb(thumb)
                    aug_thumbs, aug_vecs = _augment_and_embed(rgb, count=10)
                except Exception:
                    pass
            rid = uuid.uuid4().hex[:12]
            if STORE_THUMBS:
                _store['items'].append({'name': new, 'vec': v.tolist(), 'vecs': [{'id': rid, 'v': v.tolist()}], 'dim': int(v.size), 'thumb': (thumb or src.get('thumb','')), 'aug_thumbs': aug_thumbs, 'aug_vecs': aug_vecs})
            else:
                _store['items'].append({'name': new, 'vec': v.tolist(), 'vecs': [{'id': rid, 'v': v.tolist()}], 'dim': int(v.size), 'aug_vecs': aug_vecs})
            dst_idx = len(_store['items']) - 1
        dst = _store['items'][dst_idx]
        dst.setdefault('vecs', [])
        # find closest in source pool
        pool = []
        ids = []
        if 'vecs' in src and isinstance(src['vecs'], list):
            for j, r in enumerate(src['vecs']):
                rr = np.array(r['v'] if isinstance(r, dict) else r, dtype=np.float32)
                if rr.size == v.size:
                    pool.append(_normalize(rr)); ids.append(('vecs', j))
        if 'vec' in src:
            rr = np.array(src['vec'], dtype=np.float32)
            if rr.size == v.size:
                pool.append(_normalize(rr)); ids.append(('vec', None))
        best_s, best_k = -1.0, None
        for k, rr in enumerate(pool):
            s = float(np.dot(v, rr))
            if s > best_s:
                best_s, best_k = s, k
        # append to destination
        rid = uuid.uuid4().hex[:12]
        dst['vecs'].append({'id': rid, 'v': v.tolist()})
        # additionally: sweep other very-similar samples from source to destination
        try:
            sweep_keep = []
            moved_more = []
            for r in src.get('vecs', []):
                rr = np.array(r['v'] if isinstance(r, dict) else r, dtype=np.float32)
                if rr.size == v.size and float(np.dot(_normalize(rr), v)) >= 0.9:
                    moved_more.append({'id': (r.get('id') if isinstance(r, dict) else uuid.uuid4().hex[:12]), 'v': (r.get('v') if isinstance(r, dict) else rr.tolist())})
                else:
                    sweep_keep.append(r)
            if moved_more:
                dst['vecs'].extend(moved_more)
            src['vecs'] = sweep_keep
            if 'vec' in src:
                rr = np.array(src['vec'], dtype=np.float32)
                if rr.size == v.size and float(np.dot(_normalize(rr), v)) >= 0.9:
                    dst['vecs'].append({'id': uuid.uuid4().hex[:12], 'v': rr.tolist()})
                    src.pop('vec', None)
        except Exception:
            pass
        if thumb:
            dst.setdefault('aug_vecs', [])
            try:
                remaining = max(0, 10 - len(dst['aug_vecs']))
                if remaining > 0:
                    rgb = _data_uri_to_rgb(thumb)
                    a_th, a_v = _augment_and_embed(rgb, count=remaining)
                    dst['aug_vecs'].extend(a_v)
                    if STORE_THUMBS:
                        dst.setdefault('aug_thumbs', [])
                        dst['aug_thumbs'].extend(a_th)
            except Exception:
                pass
        # remove from source
        if best_k is not None:
            typ, idx = ids[best_k]
            if typ == 'vecs' and idx is not None:
                try:
                    src['vecs'].pop(idx)
                except Exception:
                    pass
            elif typ == 'vec':
                src.pop('vec', None)
        # if source emptied, clean up
        if len(src.get('vecs', [])) == 0:
            src.pop('vec', None)
        if len(src.get('vecs', [])) == 0 and not src.get('vec') and len(src.get('aug_vecs', [])) == 0:
            _store['items'].pop(src_idx)
        try:
            _remove_duplicate_from_others(new, v, thr=0.9)
        except Exception:
            pass
        count = 1
    else:
        # fallback: rename or merge entire cluster as before
        if src_idx is not None and dst_idx is not None and src_idx != dst_idx:
            src = _store['items'][src_idx]
            dst = _store['items'][dst_idx]
            dst.setdefault('vecs', [])
            src_vecs = src.get('vecs', [])
            if isinstance(src_vecs, list):
                dst['vecs'].extend(src_vecs)
            if 'vec' in src:
                dst['vecs'].append(src['vec'])
            dst.setdefault('aug_vecs', [])
            src_aug = src.get('aug_vecs', [])
            if isinstance(src_aug, list):
                dst['aug_vecs'].extend(src_aug)
            if STORE_THUMBS:
                dst.setdefault('aug_thumbs', [])
                src_aug_t = src.get('aug_thumbs', [])
                if isinstance(src_aug_t, list):
                    dst['aug_thumbs'].extend(src_aug_t)
                if not dst.get('thumb') and src.get('thumb'):
                    dst['thumb'] = src.get('thumb')
            _store['items'].pop(src_idx)
            count = 1
        elif src_idx is not None:
            _store['items'][src_idx]['name'] = new
            count = 1
    _save_store()
    try:
        for rec in list(_recent):
            names = rec.get('names', [])
            rec['names'] = [new if (n == old) else n for n in names]
        _recent.clear()
    except Exception:
        pass
    if TRAIN_ON_LABEL:
        try:
            app.logger.info("[ML] classifier: train requested after rename_label")
            _train_classifier(max_epochs=12)
        except Exception:
            pass
    return jsonify({'ok': True, 'updated': count})

def _data_uri_to_rgb(uri: str) -> npt.NDArray[np.uint8]:
    try:
        if not uri or 'base64,' not in uri:
            return np.zeros((0,), dtype=np.uint8)
        b64 = uri.split('base64,', 1)[1]
        raw = base64.b64decode(b64)
        arr = np.frombuffer(raw, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            return np.zeros((0,), dtype=np.uint8)
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    except Exception:
        return np.zeros((0,), dtype=np.uint8)

def _augment_and_embed(rgb: npt.NDArray[np.uint8], count: int = 10):
    thumbs, vecs = [], []
    if rgb is None or rgb.size == 0:
        return thumbs, vecs
    try:
        rgb = rgb.copy()
        try:
            import albumentations as A
            aug = A.Compose([
                A.HorizontalFlip(p=0.5),
                A.RandomBrightnessContrast(brightness_limit=0.2, contrast_limit=0.2, p=0.6),
                A.GaussianBlur(blur_limit=3, p=0.4),
                A.Rotate(limit=15, border_mode=cv2.BORDER_REFLECT_101, p=0.6),
                A.CLAHE(p=0.4)
            ])
            for i in range(count):
                out = aug(image=rgb)['image']
                thumbs.append(to_data_uri(out))
                v = detect_app.embedder.embed(out)
                if v.size == 0:
                    v = _fallback_embed(out)
                vecs.append(_normalize(v).tolist())
        except Exception:
            h, w = rgb.shape[:2]
            for i in range(count):
                img = rgb.copy()
                if i % 2 == 0:
                    img = cv2.flip(img, 1)
                alpha = 1.0 + (np.random.rand() * 0.3 - 0.15)
                beta = (np.random.rand() * 20 - 10)
                img = cv2.convertScaleAbs(img, alpha=alpha, beta=beta)
                ang = int(np.random.rand() * 20 - 10)
                M = cv2.getRotationMatrix2D((w//2, h//2), ang, 1.0)
                img = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REFLECT_101)
                thumbs.append(to_data_uri(img))
                v = detect_app.embedder.embed(img)
                if v.size == 0:
                    v = _fallback_embed(img)
                vecs.append(_normalize(v).tolist())
    except Exception:
        pass
    return thumbs, vecs

@app.get('/label_aug')
def label_aug():
    name = request.args.get('name', '').strip()
    items = []
    if STORE_THUMBS:
        for it in _store.get('items', []):
            if str(it.get('name','')).strip() == name:
                items = it.get('aug_thumbs', [])
                # On-demand generate if missing but thumb available
                if (not items) and it.get('thumb'):
                    try:
                        rgb = _data_uri_to_rgb(it.get('thumb',''))
                        a_th, a_v = _augment_and_embed(rgb, count=10)
                        it.setdefault('aug_thumbs', [])
                        it.setdefault('aug_vecs', [])
                        it['aug_thumbs'].extend(a_th)
                        it['aug_vecs'].extend(a_v)
                        _save_store()
                        items = it.get('aug_thumbs', [])
                    except Exception:
                        pass
                break
    return jsonify({'items': items})

@app.post('/set_thumb')
def set_thumb():
    if _require_role(['SuperAdmin','CollegeAdmin','HOD']) is None:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True)
    if not data or 'name' not in data or 'thumb' not in data:
        return jsonify({'error': 'name and thumb required'}), 400
    name = str(data['name']).strip()
    thumb = str(data['thumb'] or '')
    if name == '' or thumb == '':
        return jsonify({'error': 'invalid name or thumb'}), 400
    for it in _store.get('items', []):
        if str(it.get('name','')).strip() == name:
            try:
                rgb = _data_uri_to_rgb(thumb)
                a_th, a_v = _augment_and_embed(rgb, count=10)
                it.setdefault('aug_vecs', [])
                it['aug_vecs'].extend(a_v)
                if STORE_THUMBS:
                    it['thumb'] = thumb
                    it.setdefault('aug_thumbs', [])
                    it['aug_thumbs'].extend(a_th)
                _save_store()
                try:
                    _recent.clear()
                except Exception:
                    pass
                return jsonify({'ok': True})
            except Exception:
                break
    return jsonify({'error': 'label not found'}), 404

@app.get('/vectors')
def list_vectors():
    name = request.args.get('name', '').strip()
    cid = _scoped_college_id(request.args.get('college_id', ''))
    out = []
    for it in _store.get('items', []):
        if str(it.get('name','')).strip() == name and ((not cid) or str(it.get('college_id','')) == cid):
            vecs = it.get('vecs', [])
            for r in vecs:
                if isinstance(r, dict) and 'v' in r:
                    v = np.array(r['v'], dtype=np.float32)
                    out.append({'id': r.get('id',''), 'dim': int(v.size), 'first5': list(map(float, v[:5])) if v.size >= 5 else []})
                else:
                    v = np.array(r, dtype=np.float32)
                    out.append({'id': '', 'dim': int(v.size), 'first5': list(map(float, v[:5])) if v.size >= 5 else []})
            break
    return jsonify({'items': out})

@app.post('/delete_vector')
def delete_vector():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    if not data or 'name' not in data or 'id' not in data:
        return jsonify({'error': 'name and id required'}), 400
    name = str(data['name']).strip()
    college_id = _scoped_college_id(data.get('college_id',''))
    vid = str(data['id']).strip()
    if u.get('role') != 'SuperAdmin' and college_id != str(u.get('college_id','')):
        return jsonify({'error': 'forbidden'}), 403
    for it in _store.get('items', []):
        if str(it.get('name','')).strip() == name and ((not college_id) or str(it.get('college_id','')) == college_id):
            vecs = it.get('vecs', [])
            keep = []
            removed = 0
            for r in vecs:
                if isinstance(r, dict) and r.get('id','') == vid:
                    removed += 1
                else:
                    keep.append(r)
            it['vecs'] = keep
            if len(it.get('vecs', [])) == 0 and not it.get('vec') and len(it.get('aug_vecs', [])) == 0:
                _store['items'] = [x for x in _store['items'] if x is not it]
            _save_store()
            try:
                _recent.clear()
            except Exception:
                pass
            try:
                app.logger.info(f"[ML] delete_vector: removed id={vid} from '{name}'; retraining classifier")
                _train_classifier(max_epochs=8)
            except Exception:
                pass
            return jsonify({'ok': True, 'removed': removed})
    return jsonify({'error': 'label not found'}), 404

@app.post('/move_vector')
def move_vector():
    u = _require_role(['SuperAdmin','CollegeAdmin','HOD'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    if not data or 'from' not in data or 'to' not in data or 'id' not in data:
        return jsonify({'error': 'from, to, id required'}), 400
    src = str(data['from']).strip()
    dst = str(data['to']).strip()
    vid = str(data['id']).strip()
    college_id = _scoped_college_id(data.get('college_id',''))
    if u.get('role') != 'SuperAdmin' and college_id != str(u.get('college_id','')):
        return jsonify({'error': 'forbidden'}), 403
    src_it = None
    dst_it = None
    for it in _store.get('items', []):
        n = str(it.get('name','')).strip()
        if n == src and ((not college_id) or str(it.get('college_id','')) == college_id):
            src_it = it
        if n == dst and ((not college_id) or str(it.get('college_id','')) == college_id):
            dst_it = it
    if src_it is None:
        return jsonify({'error': 'source not found'}), 404
    moved_entry = None
    keep = []
    for r in src_it.get('vecs', []):
        if isinstance(r, dict) and r.get('id','') == vid:
            moved_entry = r
        else:
            keep.append(r)
    src_it['vecs'] = keep
    if moved_entry is None:
        return jsonify({'error': 'vector not found'}), 404
    if dst_it is None:
        dst_it = {'name': dst, 'vecs': [], 'dim': len(moved_entry.get('v', [])), 'aug_vecs': []}
        _store['items'].append(dst_it)
    dst_it.setdefault('vecs', [])
    dst_it['vecs'].append(moved_entry)
    if len(src_it.get('vecs', [])) == 0 and not src_it.get('vec') and len(src_it.get('aug_vecs', [])) == 0:
        _store['items'] = [x for x in _store['items'] if x is not src_it]
    _save_store()
    try:
        _recent.clear()
    except Exception:
        pass
    return jsonify({'ok': True})
@app.post('/override_track')
def override_track():
    if _require_role(['SuperAdmin','CollegeAdmin','HOD']) is None:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(silent=True)
    if not data or 'track' not in data or 'name' not in data:
        return jsonify({'error': 'track and name required'}), 400
    try:
        tid = int(data['track'])
    except Exception:
        return jsonify({'error': 'invalid track'}), 400
    name = str(data['name']).strip()
    if name == '':
        return jsonify({'error': 'invalid name'}), 400
    vec = np.array(data.get('vector', []), dtype=np.float32)
    thumb = str(data.get('thumb', '') or '')
    _track_overrides[tid] = {'name': name, 'expires': time.time() + 8.0}
    if vec.size > 0:
        try:
            v = _normalize(vec)
            # merge similar to merge_label but minimal
            dst_idx = None
            for i, it in enumerate(_store['items']):
                if str(it.get('name','')).strip() == name:
                    dst_idx = i
                    break
            if dst_idx is None:
                aug_thumbs, aug_vecs = [], []
                if thumb:
                    try:
                        rgb = _data_uri_to_rgb(thumb)
                        aug_thumbs, aug_vecs = _augment_and_embed(rgb, count=10)
                    except Exception:
                        pass
                if STORE_THUMBS:
                    _store['items'].append({'name': name, 'vec': v.tolist(), 'vecs': [v.tolist()], 'dim': int(v.size), 'thumb': thumb, 'aug_thumbs': aug_thumbs, 'aug_vecs': aug_vecs})
                else:
                    _store['items'].append({'name': name, 'vec': v.tolist(), 'vecs': [v.tolist()], 'dim': int(v.size), 'aug_vecs': aug_vecs})
            else:
                it = _store['items'][dst_idx]
                it.setdefault('vecs', [])
                try:
                    dup = False
                    for r in it['vecs']:
                        rr = np.array(r, dtype=np.float32)
                        if rr.size == v.size and float(np.dot(_normalize(rr), v)) >= 0.995:
                            dup = True; break
                    if 'vec' in it:
                        rr = np.array(it['vec'], dtype=np.float32)
                        if rr.size == v.size and float(np.dot(_normalize(rr), v)) >= 0.995:
                            dup = True
                    if not dup:
                        it['vecs'].append(v.tolist())
                except Exception:
                    it['vecs'].append(v.tolist())
                if thumb:
                    it.setdefault('aug_vecs', [])
                    try:
                        remaining = max(0, 10 - len(it['aug_vecs']))
                        if remaining > 0:
                            rgb = _data_uri_to_rgb(thumb)
                            a_th, a_v = _augment_and_embed(rgb, count=remaining)
                            it['aug_vecs'].extend(a_v)
                            if STORE_THUMBS:
                                it.setdefault('aug_thumbs', [])
                                it['aug_thumbs'].extend(a_th)
                    except Exception:
                        pass
            try:
                _remove_duplicate_from_others(name, v)
            except Exception:
                pass
        except Exception:
            pass
    _save_store()
    try:
        _recent.clear()
    except Exception:
        pass
    return jsonify({'ok': True})

@app.post('/train_classifier')
def train_classifier_endpoint():
    if _require_role(['SuperAdmin','CollegeAdmin']) is None:
        return jsonify({'error': 'forbidden'}), 403
    ok = _train_classifier(max_epochs=20)
    return jsonify({'ok': bool(ok), 'classes': len(_clf_meta.get('names', [])), 'dim': int(_clf_meta.get('dim', 0))})

@app.get('/classifier_status')
def classifier_status():
    return jsonify({'classes': len(_clf_meta.get('names', [])), 'dim': int(_clf_meta.get('dim', 0)), 'dirty': bool(_clf_dirty), 'last_train': float(_clf_last_train)})

@app.post('/superadmin_create_user')
def superadmin_create_user():
    key = request.headers.get('X-Admin-Key','').strip()
    expect = os.getenv('SUPERADMIN_API_KEY','').strip()
    if expect == '' or key != expect:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    if not data or 'password' not in data or 'role' not in data or (('email' not in data) and ('username' not in data)):
        return jsonify({'error': 'username/email, role, password required'}), 400
    email = str(data.get('email','')).strip().lower()
    username = str(data.get('username','')).strip()
    role = str(data['role']).strip()
    college_id = str(data.get('college_id',''))
    for u in _users.get('items', []):
        if email and str(u.get('email','')).lower() == email:
            return jsonify({'error': 'email exists'}), 400
        if username and str(u.get('username','')).strip().lower() == username.lower():
            return jsonify({'error': 'email exists'}), 400
    salt = os.urandom(16)
    pw_hash = _hash_password(str(data['password']), salt)
    it = {'id': uuid.uuid4().hex[:12], 'email': email, 'username': username, 'role': role, 'college_id': college_id, 'password_salt': salt.hex(), 'password_hash': pw_hash, 'is_active': True, 'created_at': time.time()}
    _users.setdefault('items', []).append(it)
    _save_users()
    return jsonify({'ok': True, 'id': it['id']})

@app.post('/auth_login')
def auth_login():
    data = request.get_json(silent=True)
    if not data or 'password' not in data or (('email' not in data) and ('username' not in data)):
        return jsonify({'error': 'username/email and password required'}), 400
    email = str(data.get('email','')).strip().lower()
    username = str(data.get('username','')).strip().lower()
    pw = str(data['password'])
    user = None
    for u in _users.get('items', []):
        if email and str(u.get('email','')).lower() == email:
            user = u; break
        if username and str(u.get('username','')).strip().lower() == username:
            user = u; break
    if user is None or not bool(user.get('is_active', True)):
        return jsonify({'error': 'invalid credentials'}), 401
    salt = bytes.fromhex(str(user.get('password_salt','')))
    calc = _hash_password(pw, salt)
    if not hmac.compare_digest(calc, str(user.get('password_hash',''))):
        return jsonify({'error': 'invalid credentials'}), 401
    token = _make_token(user)
    return jsonify({'token': token, 'role': user.get('role',''), 'college_id': user.get('college_id','')})

@app.post('/superadmin_change_password')
def superadmin_change_password():
    u = _require_role(['SuperAdmin'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True)
    old = str(data.get('old_password',''))
    new = str(data.get('new_password',''))
    if old == '' or new == '':
        return jsonify({'error': 'old_password and new_password required'}), 400
    target = None
    for it in _users.get('items', []):
        if str(it.get('id','')) == str(u.get('id','')):
            target = it; break
    if target is None:
        return jsonify({'error': 'user not found'}), 404
    salt_old = bytes.fromhex(str(target.get('password_salt','')))
    calc = _hash_password(old, salt_old)
    if not hmac.compare_digest(calc, str(target.get('password_hash',''))):
        return jsonify({'error': 'invalid old_password'}), 400
    salt_new = os.urandom(16)
    target['password_salt'] = salt_new.hex()
    target['password_hash'] = _hash_password(new, salt_new)
    _save_users()
    return jsonify({'ok': True})
@app.get('/superadmin_bootstrap_status')
def superadmin_bootstrap_status():
    u = _require_role(['SuperAdmin'])
    if u is None:
        return jsonify({'error': 'unauthorized'}), 401
    uid = str(u.get('id',''))
    for it in _users.get('items', []):
        if str(it.get('id','')) == uid:
            return jsonify({'bootstrap': bool(it.get('is_bootstrap', False))})
    return jsonify({'bootstrap': False})

@app.get('/attendance_export_csv')
def attendance_export_csv():
    sid = request.args.get('session_id','').strip()
    if not sid:
        return jsonify({'error': 'session_id required'}), 400
    rows = [['student_id','status','confidence','timestamp']]
    for r in _attendance.get('items', []):
        if str(r.get('session_id','')) == sid:
            rows.append([str(r.get('student_id','')), str(r.get('status','')), float(r.get('confidence_score', 0.0)), float(r.get('timestamp', 0.0))])
    csv = ''
    for row in rows:
        csv += ','.join(map(lambda x: str(x), row)) + '\n'
    return jsonify({'csv': csv})

@app.get('/student_attendance')
def student_attendance():
    sid = request.args.get('student_id','').strip()
    if not sid:
        return jsonify({'error': 'student_id required'}), 400
    total = 0
    present = 0
    for r in _attendance.get('items', []):
        if str(r.get('student_id','')) == sid:
            total += 1
            if str(r.get('status','')) == 'Present':
                present += 1
    pct = (present / total) if total > 0 else 0.0
    return jsonify({'present': present, 'total': total, 'percentage': pct})

@app.get('/web/login')
def web_login():
    html = """<!doctype html><html><head><meta charset="utf-8"><title>Login</title><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="font-family:system-ui,Arial;padding:20px">
<h2>Login</h2>
<input id="email" placeholder="Email" style="display:block;margin:6px 0;padding:8px;width:260px">
<input id="password" type="password" placeholder="Password" style="display:block;margin:6px 0;padding:8px;width:260px">
<button id="login" style="padding:8px 14px">Login</button>
<div id="msg" style="margin-top:10px;color:#b00"></div>
<script>
document.getElementById('login').onclick = async function(){
  const email = document.getElementById('email').value;
  const password = document.getElementById('password').value;
  const r = await fetch('/auth_login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})});
  const j = await r.json();
  if(j.token){
    localStorage.setItem('token', j.token);
    localStorage.setItem('role', j.role||'');
    localStorage.setItem('college_id', j.college_id||'');
    let path = '/web/login';
    if(j.role==='SuperAdmin') path='/web/superadmin';
    else if(j.role==='CollegeAdmin') path='/web/college_admin';
    else if(j.role==='HOD') path='/web/hod';
    else if(j.role==='Faculty') path='/web/faculty';
    else path='/web/student';
    location.href = path;
  }else{
    document.getElementById('msg').innerText = j.error || 'Login failed';
  }
};
</script></body></html>"""
    return Response(html, mimetype='text/html')

def _web_guard(role):
    return ""

def _auth_headers_js():
    return """function authHeaders(){var t=localStorage.getItem('token')||'';return t?{'Authorization':'Bearer '+t}:{}}"""

@app.get('/web/superadmin')
def web_superadmin():
    html = """<!doctype html><html><head><meta charset="utf-8"><title>SuperAdmin</title><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:system-ui,Arial;padding:20px">"""+_web_guard('SuperAdmin')+"""
<div id="app">
<h2>SuperAdmin</h2>
<div style="margin-bottom:16px">
  <button id="overview" style="padding:6px 10px">Platform Overview</button>
  <pre id="ov" style="background:#f6f6f6;padding:10px;white-space:pre-wrap"></pre>
</div>
<div style="margin-bottom:16px">
  <h3>Create User</h3>
  <input id="email" placeholder="Email" style="display:block;margin:6px 0;padding:8px;width:260px">
  <input id="password" type="password" placeholder="Password" style="display:block;margin:6px 0;padding:8px;width:260px">
  <select id="role" style="display:block;margin:6px 0;padding:8px;width:260px">
    <option>CollegeAdmin</option><option>HOD</option><option>Faculty</option><option>Student</option>
  </select>
  <input id="college_id" placeholder="College ID" style="display:block;margin:6px 0;padding:8px;width:260px">
  <input id="admin_key" placeholder="X-Admin-Key" style="display:block;margin:6px 0;padding:8px;width:260px">
  <button id="create" style="padding:6px 10px">Create</button>
  <div id="msg" style="margin-top:8px;color:#063"></div>
</div>
<div>
  <a href="/web/login">Logout</a>
</div>
</div>
<script>"""+_auth_headers_js()+"""
document.getElementById('overview').onclick = async function(){
  const r = await fetch('/platform_overview',{headers:authHeaders()});
  const j = await r.json();
  document.getElementById('ov').textContent = JSON.stringify(j,null,2);
};
document.getElementById('create').onclick = async function(){
  const email = document.getElementById('email').value;
  const password = document.getElementById('password').value;
  const role = document.getElementById('role').value;
  const college_id = document.getElementById('college_id').value;
  const key = document.getElementById('admin_key').value;
  const r = await fetch('/superadmin_create_user',{method:'POST',headers:{'Content-Type':'application/json','X-Admin-Key':key},body:JSON.stringify({email,password,role,college_id})});
  const j = await r.json();
  document.getElementById('msg').textContent = j.ok?'Created: '+j.id:(j.error||'Error');
};
</script></body></html>"""
    return Response(html, mimetype='text/html')

@app.get('/web/college_admin')
def web_college_admin():
    html = """<!doctype html><html><head><meta charset="utf-8"><title>College Admin</title><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="font-family:system-ui,Arial;padding:20px">"""+_web_guard('CollegeAdmin')+"""
<h2>College Admin</h2>
<p>Manage departments, subjects, students, faculty, classes.</p>
<a href="/web/login">Logout</a>
</body></html>"""
    return Response(html, mimetype='text/html')

@app.get('/web/hod')
def web_hod():
    html = """<!doctype html><html><head><meta charset="utf-8"><title>HOD</title><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="font-family:system-ui,Arial;padding:20px">"""+_web_guard('HOD')+"""
<h2>HOD</h2>
<p>Manage department classes and analytics.</p>
<a href="/web/login">Logout</a>
</body></html>"""
    return Response(html, mimetype='text/html')

@app.get('/web/faculty')
def web_faculty():
    html = """<!doctype html><html><head><meta charset="utf-8"><title>Faculty</title><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="font-family:system-ui,Arial;padding:20px">"""+_web_guard('Faculty')+"""
<h2>Faculty</h2>
<p>Start sessions and capture attendance.</p>
<a href="/web/login">Logout</a>
</body></html>"""
    return Response(html, mimetype='text/html')

@app.get('/web/student')
def web_student():
    html = """<!doctype html><html><head><meta charset="utf-8"><title>Student</title><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="font-family:system-ui,Arial;padding:20px">
<h2>Student</h2>
<p>View attendance percentage and timetable.</p>
<a href="/web/login">Logout</a>
</body></html>"""
    return Response(html, mimetype='text/html')

if __name__ == '__main__':
    port = int(os.getenv('API_PORT', '5001'))
    app.run(host='0.0.0.0', port=port)
