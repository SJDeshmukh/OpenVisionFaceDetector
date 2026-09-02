import os
import json
import uuid
import time
import threading
from datetime import datetime, timedelta
from flask import request, jsonify
from flask_socketio import join_room, leave_room
from utils import get_db_connection, _run, parse_db_datetime
from services.auth_service import verify_token

# In-memory storage for the latest frames
# Structure: { vendor_id: { device_id: { "data": ..., "timestamp": ..., "source_ip": ... } } }
latest_frames = {}
client_counts = {}
device_status = {}
socket_identities = {}
MAX_STREAM_FRAME_CHARS = 8_000_000

def _socket_token(auth=None, data=None):
    if isinstance(auth, dict) and auth.get('token'):
        return str(auth['token'])
    if isinstance(data, dict) and data.get('token'):
        return str(data['token'])
    header = request.headers.get('Authorization', '')
    parts = header.strip().split()
    if len(parts) == 2 and parts[0].lower() in ('bearer', 'token'):
        return parts[1]
    return request.args.get('token') or request.cookies.get('token')

def _resolve_socket_identity(auth=None, data=None):
    token = _socket_token(auth, data)
    payload = verify_token(token) if token else None
    if not payload or not payload.get('username'):
        return None
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT vendor_id, role FROM system_users WHERE username = ?", (payload['username'],))
        row = c.fetchone()
        parent_id = None
        if not row and payload.get('role') == 'parent':
            c.execute("SELECT vendor_id, id FROM parent_users WHERE username = ?", (payload['username'],))
            parent = c.fetchone()
            if parent:
                row = (parent[0], 'parent')
                parent_id = parent[1]
        if not row:
            return None
        vendor_id = row['vendor_id'] if hasattr(row, 'keys') else row[0]
        role = row['role'] if hasattr(row, 'keys') else row[1]
        if payload.get('platform') in ('mobile', 'kiosk') or role == 'faculty':
            c.execute("SELECT 1 FROM active_sessions WHERE token = ? LIMIT 1", (token,))
            if not c.fetchone():
                return None
        return {'username': payload['username'], 'role': role, 'vendor_id': vendor_id, 'parent_id': parent_id}
    except Exception:
        return None
    finally:
        conn.close()

def _socket_identity(data=None):
    identity = socket_identities.get(request.sid)
    if identity is None:
        identity = _resolve_socket_identity(data=data)
        if identity:
            socket_identities[request.sid] = identity
    return identity

def register_socket_handlers(socketio):
    @socketio.on('connect')
    def handle_connect(auth=None):
        identity = _resolve_socket_identity(auth=auth)
        if identity is None:
            return False
        socket_identities[request.sid] = identity
        return True

    @socketio.on('disconnect')
    def handle_disconnect(reason=None):
        socket_identities.pop(request.sid, None)

    @socketio.on('join_super_admin')
    def handle_join_super_admin():
        identity = _socket_identity()
        if not identity or identity['role'] != 'super_admin':
            return {'error': 'forbidden'}, 403
        join_room('super_admin')
        return {'status': 'joined', 'room': 'super_admin'}

    @socketio.on('join_vendor')
    def handle_join_vendor(data=None):
        identity = _socket_identity(data)
        if not identity:
            return {'error': 'unauthorized'}, 401
        requested = (data or {}).get('vendor_id')
        vendor_id = requested if identity['role'] == 'super_admin' and requested else identity['vendor_id']
        if vendor_id is None:
            return {'error': 'vendor_id required'}, 400
        if identity['role'] != 'super_admin' and requested is not None and str(requested) != str(vendor_id):
            return {'error': 'forbidden'}, 403
        join_room(f"vendor_{vendor_id}")
        return {'status': 'joined', 'room': f'vendor_{vendor_id}'}

    @socketio.on('join_stream')
    def handle_join_stream(data=None):
        identity = _socket_identity(data)
        if not identity:
            return {'error': 'unauthorized'}, 401
        requested = (data or {}).get('vendor_id')
        vendor_id = requested if identity['role'] == 'super_admin' and requested else identity['vendor_id']
        if vendor_id is None or (identity['role'] != 'super_admin' and requested is not None and str(requested) != str(vendor_id)):
            return {'error': 'forbidden'}, 403
        join_room(f"stream_{vendor_id}")
        return {'status': 'joined', 'room': f"stream_{vendor_id}"}

    @socketio.on('leave_stream')
    def handle_leave_stream(data=None):
        identity = _socket_identity(data)
        if not identity:
            return {'error': 'unauthorized'}, 401
        requested = (data or {}).get('vendor_id')
        vendor_id = requested if identity['role'] == 'super_admin' and requested else identity['vendor_id']
        if vendor_id is None or (identity['role'] != 'super_admin' and requested is not None and str(requested) != str(vendor_id)):
            return {'error': 'forbidden'}, 403
        leave_room(f"stream_{vendor_id}")
        return {'status': 'left', 'room': f"stream_{vendor_id}"}

    @socketio.on('stream_frame')
    def handle_stream_frame(data=None):
        try:
            identity = _socket_identity(data)
            if not identity:
                return {'error': 'unauthorized'}, 401
            if not data or not isinstance(data, dict):
                return {'error': 'invalid payload'}, 400
            image_data = data.get('image')
            if not isinstance(image_data, str) or not image_data:
                return {'error': 'image required'}, 400
            if len(image_data) > MAX_STREAM_FRAME_CHARS:
                return {'error': 'image payload too large'}, 413

            requested_vendor_id = data.get('vendor_id')
            vendor_id = requested_vendor_id if identity['role'] == 'super_admin' and requested_vendor_id else identity['vendor_id']
            if vendor_id is None or (identity['role'] != 'super_admin' and requested_vendor_id is not None and str(requested_vendor_id) != str(vendor_id)):
                return {'error': 'forbidden'}, 403
            device_id = data.get('device_id') or 'default'
            device_name = data.get('device_name') or f"Device {device_id}"
            vendor_id = int(vendor_id)

            if vendor_id not in latest_frames:
                latest_frames[vendor_id] = {}

            latest_frames[vendor_id][str(device_id)] = {
                "data": image_data,
                "timestamp": datetime.now(),
                "source_ip": request.headers.get('X-Forwarded-For', request.remote_addr),
                "device_name": device_name
            }

            payload = {
                "vendor_id": vendor_id,
                "device_id": str(device_id),
                "device_name": device_name,
                "image": image_data
            }
            socketio.emit('frame_update', payload, room=f"stream_{vendor_id}")
            socketio.emit('frame_update', payload, room=f"vendor_{vendor_id}")
            socketio.emit('frame_update', payload, room='super_admin')
            return {'status': 'ok'}
        except Exception:
            return {'error': 'unable to process frame'}, 500

    @socketio.on('webrtc_signal')
    def handle_webrtc_signal(data=None):
        identity = _socket_identity(data)
        if not identity or not isinstance(data, dict):
            return {'error': 'unauthorized'}, 401
        target_room = str(data.get('target_room') or '')
        allowed = {'super_admin'} if identity['role'] != 'super_admin' else set()
        if identity['vendor_id'] is not None:
            allowed.update({f"vendor_{identity['vendor_id']}", f"stream_{identity['vendor_id']}"})
        if identity['role'] != 'super_admin' and target_room not in allowed:
            return {'error': 'forbidden'}, 403
        if identity['role'] == 'super_admin' and not (target_room == 'super_admin' or target_room.startswith(('vendor_', 'stream_'))):
            return {'error': 'forbidden'}, 403
        socketio.emit('webrtc_signal', data, room=target_room)
        return {'status': 'ok'}

    @socketio.on('join_parent')
    def handle_join_parent(data=None):
        identity = _socket_identity(data)
        if not identity or identity['role'] != 'parent' or not identity.get('parent_id'):
            return {'error': 'forbidden'}, 403
        parent_id = identity['parent_id']
        join_room(f"parent_{parent_id}")
        return {'status': 'joined', 'room': f'parent_{parent_id}'}

    @socketio.on('join_student_number')
    def handle_join_student_number(data=None):
        try:
            identity = _socket_identity(data)
            if not identity or identity.get('vendor_id') is None:
                return {'error': 'unauthorized'}, 401
            student_number = None
            if data and isinstance(data, dict):
                student_number = str(data.get('student_number') or '').strip()
            if not student_number:
                return {'error': 'student_number required'}, 400
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT custom_data FROM faces WHERE vendor_id = ? AND custom_data IS NOT NULL", (identity['vendor_id'],))
            found = False
            for row in c.fetchall():
                try:
                    raw = row['custom_data'] if hasattr(row, 'keys') else row[0]
                    custom = json.loads(raw or '{}')
                    candidate = str(custom.get('student_number') or custom.get('roll_number') or custom.get('admission_number') or custom.get('student_id') or '').strip()
                    if candidate == student_number:
                        found = True
                        break
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
            conn.close()
            if not found:
                return {'error': 'student not found'}, 404
            join_room(f"student_{identity['vendor_id']}_{student_number}")
            try:
                fcm_token = None
                vendor_id = identity['vendor_id']
                if data and isinstance(data, dict):
                    fcm_token = str(data.get('fcm_token') or '').strip()
                if fcm_token:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute("""CREATE TABLE IF NOT EXISTS parent_tokens
                                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                                  vendor_id INTEGER,
                                  student_number TEXT,
                                  token TEXT UNIQUE,
                                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
                    if vendor_id:
                        try:
                            c.execute("INSERT OR IGNORE INTO parent_tokens (vendor_id, student_number, token) VALUES (?, ?, ?)", (vendor_id, student_number, fcm_token))
                            conn.commit()
                        except Exception:
                            pass
                    conn.close()
            except Exception:
                pass
            return {'status': 'joined', 'room': f'student_{identity["vendor_id"]}_{student_number}'}
        except Exception:
            return {'error': 'unable to join student channel'}, 500

def start_socket_background_tasks(socketio):
    """Background tasks for Socket.IO that need the socketio instance."""
    
    def cleanup_inactive_streams():
        """Background task to remove stale streams and update stats."""
        last_active_count = -1
        while True:
            socketio.sleep(5) # Sleep 5 seconds
            try:
                current_time = datetime.now()
                stale_threshold = timedelta(seconds=30)
                vendors_to_remove = []
                active_count = 0
                for v_id in list(latest_frames.keys()):
                    devices = latest_frames[v_id]
                    devices_to_remove = []
                    for d_id, data in devices.items():
                        ts = data['timestamp']
                        if isinstance(ts, str):
                            try:
                                ts = datetime.fromisoformat(ts)
                            except Exception:
                                ts = current_time
                        if current_time - ts > stale_threshold:
                            devices_to_remove.append(d_id)
                        else:
                            active_count += 1
                    for d_id in devices_to_remove:
                        del devices[d_id]
                    if not devices:
                        vendors_to_remove.append(v_id)
                for v_id in vendors_to_remove:
                    del latest_frames[v_id]
                if active_count != last_active_count:
                    last_active_count = active_count
                    socketio.emit('active_devices_update', {'count': active_count}, room='super_admin')
            except Exception as e:
                pass

    def check_subscriptions_periodically():
        """Background task to proactively logout vendors with expired plans."""
        from utils import check_vendor_status
        while True:
            socketio.sleep(60) # Check every 1 minute
            try:
                # This would need a list of active vendor IDs to check.
                # For now, let's just use the ones in latest_frames as a proxy
                active_vendor_ids = list(latest_frames.keys())
                for v_id in active_vendor_ids:
                    is_allowed, reason = check_vendor_status(v_id)
                    if not is_allowed:
                        socketio.emit('force_logout', {'vendor_id': v_id, 'reason': reason}, room=f"vendor_{v_id}")
            except Exception:
                pass

    socketio.start_background_task(cleanup_inactive_streams)
    socketio.start_background_task(check_subscriptions_periodically)
