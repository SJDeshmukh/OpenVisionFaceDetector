from flask import Blueprint, request, jsonify, send_file, g
import logging
import sqlite3
import base64
from datetime import datetime
import time

logger = logging.getLogger(__name__)

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
@vendor_required
def upload_stream_frame():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from app import latest_frames
    try:
        data = request.get_json(silent=True) or {}
        vendor_id = request.vendor_id
        image_data = data.get("image") # Base64 string
        device_id = data.get("device_id", "default")

        requested_vendor_id = data.get("vendor_id")
        if g.user_role == "super_admin":
            try:
                vendor_id = int(requested_vendor_id)
            except (ValueError, TypeError):
                return jsonify({"error": "A valid vendor_id is required"}), 400
        elif requested_vendor_id is not None:
            try:
                if int(requested_vendor_id) != int(vendor_id):
                    return jsonify({"error": "Cross-vendor stream upload is forbidden"}), 403
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid vendor_id"}), 400
        
        if not image_data:
            return jsonify({"error": "No image data"}), 400
        if not isinstance(image_data, str) or len(image_data) > 8_000_000:
            return jsonify({"error": "Image payload is too large"}), 413
            
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
        logger.warning("Stream upload error", exc_info=True)
        return jsonify({"error": "Unable to upload stream frame"}), 500


@streaming_bp.route("/stream/view", methods=["GET"])
def view_stream_frame():
    from app import get_db_connection, socketio, is_testing
    from utils import ALL_FEATURES
    from app import latest_frames
    from services.auth_service import extract_token, verify_token, authenticate_vendor_access
    auth_vendor_id, error = authenticate_vendor_access()
    if error: return error

    # Determine which vendor stream to view
    target_vendor_id = auth_vendor_id
    
    # If SuperAdmin, allow selecting vendor (default to 1)
    if not target_vendor_id:
        try:
            target_vendor_id = int(request.args.get('vendor_id', 1))
        except (ValueError, TypeError):
            target_vendor_id = 1
            
    target_device_id = request.args.get('device_id', 'default')

    vendor_frames = latest_frames.get(target_vendor_id, {})
    frame_data = vendor_frames.get(target_device_id)

    # Legacy Fallback: If no device_id specified and 'default' missing, return first available
    if not request.args.get('device_id') and not frame_data and vendor_frames:
        frame_data = next(iter(vendor_frames.values()))

    # Check if frame is stale (older than 30 seconds)
    if frame_data and frame_data.get("timestamp"):
        delta = datetime.now() - frame_data["timestamp"]
        if delta.total_seconds() > 30:
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
    from app import latest_frames
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


