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

def register_socket_handlers(socketio):
    @socketio.on('join_super_admin')
    def handle_join_super_admin():
        try:
            join_room('super_admin')
            return {'status': 'joined', 'room': 'super_admin'}
        except Exception as e:
            return {'error': str(e)}, 500

    @socketio.on('join_vendor')
    def handle_join_vendor(data=None):
        try:
            vendor_id = None
            if data and isinstance(data, dict):
                vendor_id = data.get('vendor_id')
            if not vendor_id:
                auth_header = request.headers.get('Authorization')
                if auth_header:
                    try:
                        token = auth_header.split(" ")[1]
                        user_data = verify_token(token)
                        if user_data:
                            conn = get_db_connection()
                            c = conn.cursor()
                            c.execute("SELECT vendor_id FROM system_users WHERE username = ?", (user_data['username'],))
                            row = c.fetchone()
                            conn.close()
                            vendor_id = row[0] if row else None
                    except Exception:
                        pass
            if not vendor_id:
                return {'error': 'vendor_id required'}, 400
            join_room(f"vendor_{vendor_id}")
            return {'status': 'joined', 'room': f'vendor_{vendor_id}'}
        except Exception as e:
            return {'error': str(e)}, 500

    @socketio.on('join_stream')
    def handle_join_stream(data=None):
        try:
            vendor_id = None
            if data and isinstance(data, dict):
                vendor_id = data.get('vendor_id')
            if vendor_id is None:
                return {'error': 'vendor_id required'}, 400
            try:
                vendor_id = int(vendor_id)
            except Exception:
                return {'error': 'invalid vendor_id'}, 400
            join_room(f"stream_{vendor_id}")
            return {'status': 'joined', 'room': f"stream_{vendor_id}"}
        except Exception as e:
            return {'error': str(e)}, 500

    @socketio.on('leave_stream')
    def handle_leave_stream(data=None):
        try:
            vendor_id = None
            if data and isinstance(data, dict):
                vendor_id = data.get('vendor_id')
            if vendor_id is None:
                return {'error': 'vendor_id required'}, 400
            try:
                vendor_id = int(vendor_id)
            except Exception:
                return {'error': 'invalid vendor_id'}, 400
            leave_room(f"stream_{vendor_id}")
            return {'status': 'left', 'room': f"stream_{vendor_id}"}
        except Exception as e:
            return {'error': str(e)}, 500

    @socketio.on('stream_frame')
    def handle_stream_frame(data=None):
        try:
            if not data or not isinstance(data, dict):
                return {'error': 'invalid payload'}, 400
            image_data = data.get('image')
            if not image_data:
                return {'error': 'image required'}, 400

            vendor_id = data.get('vendor_id')
            device_id = data.get('device_id') or 'default'
            device_name = data.get('device_name') or f"Device {device_id}"

            try:
                vendor_id = int(vendor_id) if vendor_id is not None else 1
            except Exception:
                vendor_id = 1
            if vendor_id <= 0:
                vendor_id = 1

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
        except Exception as e:
            return {'error': str(e)}, 500

    @socketio.on('webrtc_signal')
    def handle_webrtc_signal(data=None):
        try:
            if not data or not isinstance(data, dict):
                return {'error': 'invalid payload'}, 400
            target_room = data.get('target_room')
            if not target_room:
                 return {'error': 'target_room required'}, 400
            socketio.emit('webrtc_signal', data, room=target_room)
            return {'status': 'ok'}
        except Exception as e:
            return {'error': str(e)}, 500

    @socketio.on('join_parent')
    def handle_join_parent(data=None):
        try:
            parent_id = None
            if data and isinstance(data, dict):
                parent_id = data.get('parent_id')
            if not parent_id:
                auth_header = request.headers.get('Authorization')
                if auth_header:
                    try:
                        token = auth_header.split(" ")[1]
                        user_data = verify_token(token)
                        if user_data and user_data.get('role') == 'parent':
                            conn = get_db_connection()
                            c = conn.cursor()
                            c.execute("SELECT id FROM parent_users WHERE username = ?", (user_data['username'],))
                            row = c.fetchone()
                            conn.close()
                            parent_id = row[0] if row else None
                    except Exception:
                        pass
            if not parent_id:
                return {'error': 'parent_id required'}, 400
            join_room(f"parent_{parent_id}")
            return {'status': 'joined', 'room': f'parent_{parent_id}'}
        except Exception as e:
            return {'error': str(e)}, 500

    @socketio.on('join_student_number')
    def handle_join_student_number(data=None):
        try:
            student_number = None
            if data and isinstance(data, dict):
                student_number = str(data.get('student_number') or '').strip()
            if not student_number:
                return {'error': 'student_number required'}, 400
            join_room(f"student_{student_number}")
            try:
                fcm_token = None
                vendor_id = None
                if data and isinstance(data, dict):
                    fcm_token = str(data.get('fcm_token') or '').strip()
                    vendor_id = data.get('vendor_id')
                if fcm_token:
                    conn = get_db_connection()
                    c = conn.cursor()
                    if not vendor_id:
                        c.execute("SELECT vendor_id, custom_data FROM faces WHERE custom_data IS NOT NULL")
                        rows = c.fetchall()
                        for r in rows:
                            try:
                                cd = json.loads(r[1])
                                sn = str(cd.get('student_number') or cd.get('roll_number') or cd.get('admission_number') or '').strip()
                                if sn == student_number:
                                    vendor_id = r[0]
                                    break
                            except Exception:
                                pass
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
            return {'status': 'joined', 'room': f'student_{student_number}'}
        except Exception as e:
            return {'error': str(e)}, 500

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
