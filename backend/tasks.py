import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
import sys

# --- Basic Path Setup ---
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    from celery_app import celery
    from celery.signals import task_prerun, task_postrun, task_failure, task_retry, task_received, task_revoked
except Exception:
    celery = None
    class _DummySignal:
        def connect(self, func):
            return func
    task_prerun = task_postrun = task_failure = task_retry = task_received = task_revoked = _DummySignal()

from utils import get_db_connection, log_audit, BUNDLE_FEATURES
try:
    from app import socketio
except ImportError:
    socketio = None
import json
import base64
import sqlite3
from datetime import date, timedelta, datetime

TASK_EVENTS_MAX = int(os.environ.get("TASK_EVENTS_MAX", "50000"))

if celery:
    @celery.task(name="tasks.process_vendor_creation")
    def process_vendor_creation_task(payload):
        vendor_id = payload["vendor_id"]
        company_name = payload["company_name"]
        frontend_bundle_id = payload.get("frontend_bundle_id", "default_attendance")
        admin_username = payload["admin_username"]
        admin_password = payload["admin_password"]
        user_username = payload["user_username"]
        user_password = payload["user_password"]
        conn2 = get_db_connection()
        c2 = conn2.cursor()
        start_date = payload.get("start_date") or date.today().isoformat()
        end_date = payload.get("end_date") or (date.today() + timedelta(days=14)).isoformat()
        max_users = payload.get("max_users") or 5
        max_employees = payload.get("max_employees") or 50
        max_mobile_devices = payload.get("max_mobile_devices") or max_users
        try:
            max_web_sessions = int(payload.get("max_web_sessions") or 1)
        except Exception:
            max_web_sessions = 1
        if max_web_sessions < 1:
            max_web_sessions = 1
        cost_per_user = payload.get("cost_per_user") or 0
        cost_per_employee = payload.get("cost_per_employee") or 0
        features = payload.get("features") or BUNDLE_FEATURES.get(frontend_bundle_id, [])
        features_json = json.dumps(features)
        c2.execute("""INSERT INTO subscriptions (vendor_id, plan_type, start_date, end_date, max_users, max_employees, max_mobile_devices, max_web_sessions, cost_per_user, cost_per_employee, setup_fee, features)
                      VALUES (?, 'custom', ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                   (vendor_id, start_date, end_date, max_users, max_employees, max_mobile_devices, max_web_sessions, cost_per_user, cost_per_employee, features_json))
        try:
            c2.execute("""INSERT INTO system_users (username, password, role, vendor_id)
                          VALUES (?, ?, 'vendor_admin', ?)""",
                       (admin_username, admin_password, vendor_id))
        except sqlite3.IntegrityError:
            pass
        try:
            c2.execute("""INSERT INTO system_users (username, password, role, vendor_id)
                          VALUES (?, ?, 'user', ?)""",
                       (user_username, user_password, vendor_id))
        except sqlite3.IntegrityError:
            pass
        c2.execute("INSERT INTO companies (name, shifts, draft_timetable, live_timetable, vendor_id) VALUES (?, ?, ?, ?, ?)", 
                   (company_name, '[]', '[]', '[]', vendor_id))
        conn2.commit()
        conn2.close()
        log_audit('create_vendor', details={'company_name': company_name}, target_vendor_id=vendor_id, actor="system")
        if socketio:
            socketio.emit('vendor_updated', {'vendor_id': vendor_id}, room='super_admin')

def ensure_task_events_table():
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""
            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                name TEXT,
                queue TEXT,
                worker TEXT,
                status TEXT,
                received_at DATETIME,
                started_at DATETIME,
                finished_at DATETIME,
                runtime REAL,
                retries INTEGER,
                eta DATETIME,
                args TEXT,
                kwargs TEXT,
                result TEXT,
                error TEXT,
                trace TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_task_events_status ON task_events(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_task_events_name ON task_events(name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_task_events_queue ON task_events(queue)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_task_events_finished ON task_events(finished_at)")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()

def _store_task_event(payload):
    ensure_task_events_table()
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("""INSERT INTO task_events (task_id, name, queue, worker, status, received_at, started_at, finished_at, runtime, retries, eta, args, kwargs, result, error, trace)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            payload.get("task_id"), payload.get("name"), payload.get("queue"), payload.get("worker"),
            payload.get("status"), payload.get("received_at"), payload.get("started_at"), payload.get("finished_at"),
            payload.get("runtime"), payload.get("retries"), payload.get("eta"), payload.get("args"),
            payload.get("kwargs"), payload.get("result"), payload.get("error"), payload.get("trace")
        ))
        c.execute("SELECT COUNT(*) FROM task_events")
        row = c.fetchone()
        total = row[0] if row else 0
        if total and int(total) > TASK_EVENTS_MAX:
            to_delete = int(total) - TASK_EVENTS_MAX
            c.execute("DELETE FROM task_events WHERE id IN (SELECT id FROM task_events ORDER BY id ASC LIMIT ?)", (to_delete,))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()

@task_received.connect
def _on_task_received(sender=None, headers=None, body=None, **kwargs):
    try:
        _store_task_event({
            "task_id": headers.get("id") if headers else None,
            "name": headers.get("task") if headers else None,
            "queue": headers.get("queue") if headers else None,
            "worker": sender,
            "status": "received",
            "received_at": datetime.utcnow().isoformat(),
            "retries": headers.get("retries", 0) if headers else 0,
            "eta": headers.get("eta") if headers else None,
            "args": json.dumps(body.get("args", [])) if body else None,
            "kwargs": json.dumps(body.get("kwargs", {})) if body else None
        })
    except Exception:
        pass

@task_prerun.connect
def _on_task_prerun(task=None, **kwargs):
    try:
        _store_task_event({
            "task_id": getattr(task.request, "id", None),
            "name": task.name,
            "queue": getattr(task.request, "delivery_info", {}).get("queue"),
            "worker": getattr(task.request, "hostname", None),
            "status": "started",
            "started_at": datetime.utcnow().isoformat(),
            "args": json.dumps(getattr(task.request, "args", [])),
            "kwargs": json.dumps(getattr(task.request, "kwargs", {}))
        })
    except Exception:
        pass

@task_postrun.connect
def _on_task_postrun(task=None, retval=None, state=None, **kwargs):
    try:
        _store_task_event({
            "task_id": getattr(task.request, "id", None),
            "name": task.name,
            "queue": getattr(task.request, "delivery_info", {}).get("queue"),
            "worker": getattr(task.request, "hostname", None),
            "status": state or "success",
            "finished_at": datetime.utcnow().isoformat(),
            "runtime": getattr(task.request, "runtime", None),
            "result": json.dumps(retval) if retval is not None else None
        })
    except Exception:
        pass

@task_failure.connect
def _on_task_failure(task_id=None, exception=None, traceback=None, einfo=None, sender=None, **kwargs):
    try:
        _store_task_event({
            "task_id": task_id,
            "name": getattr(sender, "name", None),
            "worker": getattr(sender.request, "hostname", None) if hasattr(sender, "request") else None,
            "status": "failure",
            "finished_at": datetime.utcnow().isoformat(),
            "error": str(exception) if exception else None,
            "trace": str(traceback) if traceback else None
        })
    except Exception:
        pass

@task_retry.connect
def _on_task_retry(request=None, reason=None, einfo=None, **kwargs):
    try:
        _store_task_event({
            "task_id": getattr(request, "id", None),
            "name": getattr(request, "task", None),
            "worker": getattr(request, "hostname", None),
            "status": "retry",
            "finished_at": datetime.utcnow().isoformat(),
            "retries": getattr(request, "retries", 1),
            "error": str(reason) if reason else None
        })
    except Exception:
        pass

def process_class_batch_items(batch_id, vendor_id, params):
    from services.face_service import _detect_faces_from_bytes
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get pending items
    c.execute("SELECT id, image_b64 FROM class_batch_items WHERE batch_id = ? AND status = 'pending' ORDER BY seq ASC", (batch_id,))
    items = c.fetchall()
    
    for item in items:
        item_id, img_b64 = item[0], item[1]
        try:
            # Update status to processing
            c.execute("UPDATE class_batch_items SET status = 'processing' WHERE id = ?", (item_id,))
            conn.commit()
            
            # Decode image
            header, encoded = img_b64.split(',', 1) if ',' in img_b64 else ('', img_b64)
            raw = base64.b64decode(encoded)
            
            # Detect faces
            faces, annotated_b64 = _detect_faces_from_bytes(raw, params, vendor_id)
            
            # Update item with results
            c.execute(
                "UPDATE class_batch_items SET faces_json = ?, annotated_b64 = ?, status = 'done' WHERE id = ?",
                (json.dumps(faces), annotated_b64, item_id)
            )
            conn.commit()
        except Exception as e:
            # Mark as failed
            c.execute(
                "UPDATE class_batch_items SET status = 'failed', faces_json = '[]', annotated_b64 = ? WHERE id = ?",
                (f"Error: {str(e)}", item_id)
            )
            conn.commit()
    
    # Check if all items are done/failed, then mark batch completed
    c.execute("SELECT COUNT(*) FROM class_batch_items WHERE batch_id = ? AND status IN ('pending', 'processing')", (batch_id,))
    if c.fetchone()[0] == 0:
        c.execute("UPDATE class_batches SET status = 'completed' WHERE id = ?", (batch_id,))
        conn.commit()
        
    conn.close()

# Tasks are registered via decorators or manual wrapping at the end of the file if needed.

def refresh_class_batch_items(batch_id, vendor_id, params):
    from services.face_service import _detect_faces_from_bytes
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, image_b64 FROM class_batch_items WHERE batch_id = ? ORDER BY seq ASC", (batch_id,))
    items = c.fetchall()
    for item in items:
        item_id, img_b64 = item[0], item[1]
        try:
            c.execute("UPDATE class_batch_items SET status = 'processing' WHERE id = ?", (item_id,))
            conn.commit()
            header, encoded = img_b64.split(',', 1) if ',' in img_b64 else ('', img_b64)
            raw = base64.b64decode(encoded)
            faces, annotated_b64 = _detect_faces_from_bytes(raw, params, vendor_id)
            c.execute(
                "UPDATE class_batch_items SET faces_json = ?, annotated_b64 = ?, status = 'done' WHERE id = ?",
                (json.dumps(faces), annotated_b64, item_id)
            )
            conn.commit()
        except Exception as e:
            c.execute(
                "UPDATE class_batch_items SET status = 'failed', faces_json = '[]', annotated_b64 = ? WHERE id = ?",
                (f"Error: {str(e)}", item_id)
            )
            conn.commit()
    conn.close()

if celery:
    # Ensure they are registered with the correct names
    if not hasattr(process_class_batch_items, 'delay'):
        process_class_batch_items = celery.task(name="tasks.process_class_batch_items")(process_class_batch_items)
    if not hasattr(refresh_class_batch_items, 'delay'):
        refresh_class_batch_items = celery.task(name="tasks.refresh_class_batch_items")(refresh_class_batch_items)

@celery.task(name="tasks.search_embedding_task")
def search_embedding_task(image_b64, params, vendor_id):
    import numpy as np
    import cv2
    import base64
    from services.face_service import _ensure_vendor_emb_cache, _normalize_vec, _suggest_from_cache, _decode_data_uri_to_rgb
    
    # decode image
    parts = image_b64.split(',', 1)
    payload = parts[1] if len(parts) == 2 else parts[0]
    file_bytes = base64.b64decode(payload)
    arr = np.frombuffer(file_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Invalid image")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    
    from multiple_face_detection import app as mfd_app
    
    data = params
    lr = False  # Keep it simple or match config
    det_bound = 1280
    
    enhancer = data.get('enhancer') or "GFPGAN"
    crop_mode = data.get('crop_mode') or "Portrait"
    gfp_up = int(data.get('gfpgan_upscale') or 2)
    preclean_whole = True
    preclean_level = 0.4

    annotated, crops, df, df_emb = mfd_app.detect_faces(
        image_input=rgb,
        enhancer=enhancer,
        enhance_level=0.5,
        gfpgan_upscale=gfp_up,
        codeformer_w=0.5,
        compute_embeddings=True,
        crop_mode=crop_mode,
        portrait_scale=3.0,
        preclean_whole=preclean_whole,
        preclean_level=preclean_level,
        det_max_side=det_bound
    )
    
    class_year = data.get('class_year')
    division = data.get('division')
    branch = data.get('branch')
    vcache = _ensure_vendor_emb_cache(vendor_id, class_year=class_year, division=division, branch=branch)
    topk = int(data.get('topk', 5))
    
    faces_out = []
    if isinstance(annotated, tuple) and len(annotated) == 2:
        img_rgb, anns = annotated
        jq = 85
        for i, (box, score_str) in enumerate(anns or []):
            if i >= len(crops): continue
            crop_rgb = crops[i]
            x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
            
            ih, iw = img_rgb.shape[:2]
            if df is not None and hasattr(df, 'iloc') and i < len(df):
                row = df.iloc[i]
                bx1, by1, bx2, by2 = int(row['x1']), int(row['y1']), int(row['x2']), int(row['y2'])
            else:
                bx1, by1, bx2, by2 = x1, y1, x2, y2
                
            bx1 = max(0, bx1); by1 = max(0, by1)
            bx2 = min(iw, bx2); by2 = min(ih, by2)
            pure_face = img_rgb[by1:by2, bx1:bx2]
            
            try:
                ok, buf = cv2.imencode('.jpg', cv2.cvtColor(pure_face, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, jq])
                face_b64 = base64.b64encode(buf.tobytes()).decode('ascii') if ok else ''
            except Exception:
                face_b64 = ''
                
            emb_vec_b64 = ''
            struct_vec_b64 = ''
            landmarks_3d = []
            struct_vec_val = None
            try:
                emb = mfd_app.get_embedder().embed(pure_face)
                emb_norm = _normalize_vec(emb)
                if emb_norm.size > 0:
                    emb_vec_b64 = base64.b64encode(emb_norm.astype(np.float32).tobytes()).decode('ascii')
                
                # --- 3DDFA-V3 Integration for search task ---
                from services.face_service import get_realtime_engine, _extract_structural_vector
                engine = get_realtime_engine()
                if engine is not None:
                    try:
                        # Use a 1.5x padded box for 3D context
                        c3x1, c3y1, c3x2, c3y2 = mfd_app._compute_portrait_box(bx1, by1, bx2, by2, img_rgb.shape[1], img_rgb.shape[0], scale=1.5, margin=0.2)
                        face_for_3d = img_rgb[c3y1:c3y2, c3x1:c3x2]
                        if face_for_3d.size > 0:
                            lmks_list = engine.extract_landmarks(face_for_3d)
                            if lmks_list and len(lmks_list) > 0:
                                lmks = lmks_list[0]
                                landmarks_3d = lmks.tolist()
                                struct_vec_val = _extract_structural_vector(lmks)
                                if struct_vec_val.size > 0:
                                    struct_vec_b64 = base64.b64encode(struct_vec_val.astype(np.float32).tobytes()).decode('ascii')
                    except Exception:
                        pass

                sugg = _suggest_from_cache(emb, vcache, topk=topk, struct_vec=struct_vec_val)
            except Exception:
                sugg = []
                
            faces_out.append({
                "index": i,
                "box": [bx1, by1, bx2, by2],
                "score": float(score_str) if score_str else None,
                "suggestions": sugg,
                "face_thumb": f"data:image/jpeg;base64,{face_b64}" if face_b64 else None,
                "emb_vec": emb_vec_b64,
                "struct_vec": struct_vec_b64,
                "landmarks_3d": landmarks_3d
            })
            
    # Resolve thumbs for top matches
    try:
        pid_set = set()
        for f in faces_out:
            for s in f.get("suggestions") or []:
                try:
                    pid_set.add(int(s.get("person_id")))
                except Exception: pass
        if pid_set:
            conn = get_db_connection()
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            ph = ",".join(["?"] * len(pid_set))
            c.execute(f"SELECT id, face_image FROM faces WHERE id IN ({ph})", list(pid_set))
            rows = c.fetchall() or []
            conn.close()
            tmap = {}
            for r in rows:
                pid = r["id"]
                uri = r["face_image"]
                # just pass raw back to frontend if it is a url
                if uri and str(uri).startswith("http"):
                    tmap[pid] = uri
                elif uri and str(uri).startswith("data:image"):
                    tmap[pid] = uri
            for f in faces_out:
                for s in f.get("suggestions") or []:
                    pid = int(s.get("person_id"))
                    if pid in tmap:
                        s["face_thumb"] = tmap[pid]
    except Exception:
        pass
        
    return {"faces": faces_out, "count": len(faces_out)}

if celery:
    @celery.task(name="tasks.process_import_employees")
    def process_import_employees_task(vendor_id, csv_data):
        import csv
        import io
        from utils import get_db_connection, _run, log_audit
        f = io.StringIO(csv_data)
        reader = csv.DictReader(f)
        conn = get_db_connection()
        c = conn.cursor()
        try:
            count = 0
            for row in reader:
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                phone = row.get("phone")
                department = row.get("department")
                designation = row.get("designation")
                shift = row.get("shift")
                try:
                    daily_wage = float(row.get("daily_wage") or 0)
                except Exception:
                    daily_wage = 0
                custom_data = row.get("custom_data")
                _run(c, """INSERT INTO faces (name, phone, department, designation, shift, daily_wage, vendor_id, custom_data)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (name, phone, department, designation, shift, daily_wage, vendor_id, custom_data))
                count += 1
            conn.commit()
            log_audit("employees_import", {"count": count}, target_vendor_id=vendor_id, actor="system")
            return {"success": True, "imported": count}
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return {"error": str(e)}
        finally:
            conn.close()

    @celery.task(name="tasks.process_delete_vendor")
    def process_delete_vendor_task(vendor_id):
        from utils import get_db_connection, _run, log_audit
        conn = get_db_connection()
        c = conn.cursor()
        try:
            # Ensure archive table exists
            _run(c, """CREATE TABLE IF NOT EXISTS archive_objects (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        vendor_id INTEGER,
                        table_name TEXT,
                        row_json TEXT,
                        archived_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )""")
            
            # Check vendor
            _run(c, "SELECT * FROM vendors WHERE id = ?", (vendor_id,))
            vendor_row = c.fetchone()
            if not vendor_row:
                log_audit("vendor_delete", {"error": "Not Found"}, target_vendor_id=vendor_id, status="failed", actor="system")
                return {"error": "Vendor not found"}

            def archive_table(table, key="vendor_id"):
                _run(c, f"SELECT * FROM {table} WHERE {key} = ?", (vendor_id,))
                cols = [d[0] for d in c.description] if hasattr(c, "description") and c.description else []
                rows = c.fetchall()
                for r in rows:
                    if isinstance(r, dict):
                        row_dict = r
                    else:
                        row_dict = {cols[i]: r[i] for i in range(len(cols))}
                    _run(c, "INSERT INTO archive_objects (vendor_id, table_name, row_json) VALUES (?, ?, ?)", (vendor_id, table, json.dumps(row_dict)))

            tables = ["subscriptions", "invoices", "system_users", "companies", "faces", "attendance", "active_sessions"]
            for t in tables:
                archive_table(t)
            
            # Archive vendor itself
            vcols = [d[0] for d in c.description] if hasattr(c, "description") and c.description else []
            vdict = vendor_row if isinstance(vendor_row, dict) else {vcols[i]: vendor_row[i] for i in range(len(vcols))}
            _run(c, "INSERT INTO archive_objects (vendor_id, table_name, row_json) VALUES (?, ?, ?)", (vendor_id, "vendors", json.dumps(vdict)))

            # Hard delete
            for t in tables:
                _run(c, f"DELETE FROM {t} WHERE vendor_id = ?", (vendor_id,))
            _run(c, "DELETE FROM vendors WHERE id = ?", (vendor_id,))
            
            conn.commit()
            log_audit("vendor_delete", {"message": "Archived and deleted"}, target_vendor_id=vendor_id, status="success", actor="system")
            return {"success": True}
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            log_audit("vendor_delete", {"error": str(e)}, target_vendor_id=vendor_id, status="failed", actor="system")
            return {"error": str(e)}
        finally:
            conn.close()

    @celery.task(name="tasks.bulk_vendor_action")
    def bulk_vendor_action_task(vendor_ids, action, payload):
        from utils import get_db_connection, _run, log_audit
        conn = get_db_connection()
        c = conn.cursor()
        results = []
        try:
            if action in ("suspend", "activate"):
                new_status = 'suspended' if action == 'suspend' else 'active'
                for vid in vendor_ids:
                    _run(c, "UPDATE vendors SET status = ? WHERE id = ?", (new_status, vid))
                    log_audit(f"vendor_{action}", {}, target_vendor_id=vid, actor="system")
                    results.append(vid)
            elif action == "toggle_feature":
                feature = payload.get("feature")
                enabled = payload.get("enabled", True)
                for vid in vendor_ids:
                    _run(c, "SELECT features FROM subscriptions WHERE vendor_id = ?", (vid,))
                    row = c.fetchone()
                    feats = json.loads(row[0]) if row and row[0] else []
                    if enabled and feature not in feats:
                        feats.append(feature)
                    elif not enabled:
                        feats = [f for f in feats if f != feature]
                    _run(c, "UPDATE subscriptions SET features = ? WHERE vendor_id = ?", (json.dumps(feats), vid))
                    log_audit("vendor_toggle_feature", {"feature": feature, "enabled": enabled}, target_vendor_id=vid, actor="system")
                    results.append(vid)
            conn.commit()
            return {"success": True, "processed": results}
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return {"error": str(e)}
        finally:
            conn.close()

    @celery.task(name="tasks.send_alert")
    def send_alert_task(tokens, ev):
        import requests, os, json
        server_key = os.getenv("FCM_SERVER_KEY", "")
        if not server_key or not tokens:
            return {"error": "Skipping: no key or tokens"}
        
        payload = {
            "registration_ids": tokens,
            "notification": {
                "title": f"{ev.get('name', '')} {ev.get('status', '')}",
                "body": f"{ev.get('timestamp', '')} {ev.get('activity', '')}"
            },
            "data": ev
        }
        headers = {
            "Content-Type": "application/json", 
            "Authorization": "key=" + server_key
        }
        try:
            resp = requests.post("https://fcm.googleapis.com/fcm/send", headers=headers, data=json.dumps(payload), timeout=10)
            return {"status": resp.status_code, "resp": resp.text[:200]}
        except Exception as e:
            return {"error": str(e)}

