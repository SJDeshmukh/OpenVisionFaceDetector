from flask import Blueprint, request, jsonify, send_file
import sqlite3
import base64
from datetime import datetime
import time

# Mock auth decorators for streaming
def vendor_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        from services.auth_service import authenticate_vendor_access
        vendor_id, err = authenticate_vendor_access()
        if err: return err
        request.vendor_id = vendor_id
        return f(*args, **kwargs)
    return decorated

def track_metrics(endpoint_name):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*inner_args, **inner_kwargs):
            return f(*inner_args, **inner_kwargs)
        return decorated
    return decorator

streaming_bp = Blueprint('streaming_bp', __name__)

@streaming_bp.route("/stream/upload", methods=["POST"])
def upload_stream_frame():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from app import latest_frames, client_counts, device_status
    from services.auth_service import extract_token, verify_token
    try:
        # 1. Identify Vendor from Auth Token
        vendor_id = 1 # Default to Vendor 1 (Legacy/Unauth)
        
        auth_header = request.headers.get('Authorization')
        if auth_header:
            try:
                token = auth_header.split(" ")[1]
                user_data = verify_token(token)
                if user_data:
                    conn_auth = get_db_connection()
                    c_auth = conn_auth.cursor()
                    c_auth.execute("SELECT vendor_id FROM system_users WHERE username = ?", (user_data['username'],))
                    u_row = c_auth.fetchone()
                    conn_auth.close()
                    if u_row and u_row[0]:
                        vendor_id = u_row[0]
            except:
                pass

        data = request.json
        image_data = data.get("image") # Base64 string
        device_id = data.get("device_id", "default")
        
        # 2. Check for explicit vendor_id in body (Override)
        if data.get("vendor_id"):
            try:
                vendor_id = int(data.get("vendor_id"))
            except:
                pass
        
        if not image_data:
            return jsonify({"error": "No image data"}), 400
            
        if vendor_id not in latest_frames:
            latest_frames[vendor_id] = {}
            
        latest_frames[vendor_id][device_id] = {
            "data": image_data,
            "timestamp": datetime.now(),
            "source_ip": request.headers.get('X-Forwarded-For', request.remote_addr),
            "device_name": data.get("device_name", f"Device {device_id}"),
            "battery_level": data.get("battery_level")
        }
        payload = {
            "vendor_id": vendor_id,
            "device_id": str(device_id),
            "device_name": data.get("device_name", f"Device {device_id}"),
            "image": image_data
        }
        socketio.emit('frame_update', payload, room=f"stream_{vendor_id}")
        socketio.emit('frame_update', payload, room=f"vendor_{vendor_id}")
        socketio.emit('frame_update', payload, room='super_admin')
        
        return jsonify({"status": "success"})
    except Exception as e:
        pass # print(f"Stream Upload Error: {e}")
        return jsonify({"error": str(e)}), 500


@streaming_bp.route("/stream/view", methods=["GET"])
def view_stream_frame():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from app import latest_frames, client_counts, device_status
    from services.auth_service import extract_token, verify_token, authenticate_vendor_access
    auth_vendor_id, error = authenticate_vendor_access()
    if error: return error

    # Determine which vendor stream to view
    target_vendor_id = auth_vendor_id
    
    # If SuperAdmin, allow selecting vendor (default to 1)
    if not target_vendor_id:
        try:
            target_vendor_id = int(request.args.get('vendor_id', 1))
        except:
            target_vendor_id = 1
            
    target_device_id = request.args.get('device_id', 'default')

    vendor_frames = latest_frames.get(target_vendor_id, {})
    frame_data = vendor_frames.get(target_device_id)

    # Legacy Fallback: If no device_id specified and 'default' missing, return first available
    if not request.args.get('device_id') and not frame_data and vendor_frames:
        frame_data = next(iter(vendor_frames.values()))

    # Check if frame is stale (older than 10 seconds)
    if frame_data and frame_data.get("timestamp"):
        delta = datetime.now() - frame_data["timestamp"]
        if delta.total_seconds() > 10:
            return jsonify({"status": "offline", "image": None})
            
    if frame_data and frame_data.get("data"):
        return jsonify({
            "status": "online", 
            "image": frame_data["data"],
            "source_ip": frame_data.get("source_ip", "Unknown"),
            "timestamp": frame_data.get("timestamp").isoformat()
        })
    else:
        return jsonify({"status": "offline", "image": None})


@streaming_bp.route("/stream/active-devices", methods=["GET"])
def list_active_devices():
    from app import get_db_connection, socketio, is_testing, ALL_FEATURES
    from app import latest_frames, client_counts, device_status
    from services.auth_service import extract_token, verify_token, authenticate_vendor_access
    """
    Returns a list of active devices (streams) for the authenticated vendor 
    or all vendors if SuperAdmin.
    """
    auth_vendor_id, error = authenticate_vendor_access()
    if error: return error
    
    active_list = []
    
    # If SuperAdmin (auth_vendor_id is None), return all
    # If Vendor Admin, return only theirs
    
    target_vendors = [auth_vendor_id] if auth_vendor_id else latest_frames.keys()
    
    for vid in target_vendors:
        if vid in latest_frames:
            devices = latest_frames[vid]
            for did, data in devices.items():
                # Filter out stale devices (> 30 seconds)
                if (datetime.now() - data['timestamp']).total_seconds() < 30:
                    active_list.append({
                        "vendor_id": vid,
                        "device_id": did,
                        "device_name": data.get("device_name", f"Device {did}"),
                        "last_seen": data['timestamp'].isoformat(),
                        "source_ip": data.get("source_ip"),
                        "battery_level": data.get("battery_level")
                    })
                    
    return jsonify({"devices": active_list})



