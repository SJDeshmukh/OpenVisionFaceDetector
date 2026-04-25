import os
import json
import threading
import logging
import time

logger = logging.getLogger("notifications")

FIREBASE_SERVER_KEY = os.environ.get("FIREBASE_SERVER_KEY", "")


def send_fcm_notification(fcm_token: str, title: str, body: str, data: dict = None) -> bool:
    """Send a high-priority FCM push notification.
    Requires FIREBASE_SERVER_KEY env var (Firebase Console → Project Settings → Cloud Messaging).
    """
    if not FIREBASE_SERVER_KEY:
        logger.warning("FCM: FIREBASE_SERVER_KEY is missing in environment. Cannot send notification.")
        return False
    if not fcm_token:
        logger.warning("FCM: Target token is missing. Cannot send.")
        return False
        
    try:
        import requests as _req
        # Standard FCM Legacy payload for both Foreground and Background delivery
        payload = {
            "to": fcm_token,
            "priority": "high",
            "time_to_live": 0, # Immediate delivery
            "notification": {
                "title": title,
                "body": body,
                "sound": "default",
                "tag": "attendance_alert",
                "click_action": "FLUTTER_NOTIFICATION_CLICK"
            },
            "android": {
                "priority": "high",
                "notification": {
                    "channel_id": "parent_attendance",
                    "sound": "default",
                    "priority": "max",
                    "visibility": "public",
                    "tag": "attendance_alert"
                }
            },
            "data": {
                "click_action": "FLUTTER_NOTIFICATION_CLICK",
                "status": "done",
                "channel_id": "parent_attendance"
            }
        }
        if data:
            # Merge custom data into the data block
            for k, v in data.items():
                payload["data"][str(k)] = str(v)

        resp = _req.post(
            "https://fcm.googleapis.com/fcm/send",
            headers={
                "Authorization": f"key={FIREBASE_SERVER_KEY}",
                "Content-Type": "application/json"
            },
            data=json.dumps(payload),
            timeout=8
        )
        if resp.status_code != 200:
            logger.warning("FCM failure %s: %s", resp.status_code, resp.text[:200])
        else:
            logger.info("FCM success: Notification sent to %s...", fcm_token[:10])
        return resp.status_code == 200
    except Exception as e:
        logger.warning("FCM send failed: %s", e)
        return False


def notify_parent_async(person_id, vendor_id, title: str, body: str, data: dict = None):
    """Fire-and-forget notification to the parent.
    Prioritizes Socket.io for immediate app delivery and falls back to FCM.
    """
    def _worker():
        try:
            try:
                from utils import get_db_connection
            except ImportError:
                from .utils import get_db_connection
            conn = get_db_connection()
            c = conn.cursor()
            
            # 1. Find the parent linked to this student
            c.execute("""
                SELECT pu.id, pu.fcm_token, pu.student_number
                FROM student_parents sp
                JOIN parent_users pu ON pu.id = sp.parent_id
                WHERE sp.person_id = ? AND sp.vendor_id = ?
            """, (person_id, vendor_id))
            links = c.fetchall() or []
            
            # --- SELF-HEALING: If no explicit link, try finding by student_number ---
            parent_ids = []
            fcm_tokens = []
            student_numbers = []
            
            if not links:
                c.execute("SELECT phone, custom_data FROM faces WHERE id = ?", (person_id,))
                found = c.fetchone()
                if found:
                    s_cd = found[1] if isinstance(found, (list, tuple)) else found.get('custom_data')
                    try:
                        from utils import extract_student_number_from_custom_data
                    except ImportError:
                        from .utils import extract_student_number_from_custom_data
                    s_num = extract_student_number_from_custom_data(s_cd, search_term=None)
                    if s_num:
                        c.execute("SELECT id, fcm_token, student_number FROM parent_users WHERE vendor_id = ? AND student_number = ?", (vendor_id, s_num))
                        links = c.fetchall() or []
            
            for row in links:
                pid = row[0] if isinstance(row, (list, tuple)) else row.get('id')
                token = row[1] if isinstance(row, (list, tuple)) else row.get('fcm_token')
                sn = row[2] if isinstance(row, (list, tuple)) else row.get('student_number')
                if pid: parent_ids.append(pid)
                if token: fcm_tokens.append(token)
                if sn: student_numbers.append(sn)
            
            conn.close()

            # 2. Socket.io Delivery (Primary)
            try:
                try:
                    from app import socketio
                except ImportError:
                    from .app import socketio
                
                socket_payload = {
                    "title": title,
                    "body": body,
                    "data": data or {},
                    "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
                }
                # Emit to specific parent rooms and student rooms
                for pid in set(parent_ids):
                    socketio.emit('new_notification', socket_payload, room=f"parent_{pid}")
                for sn in set(student_numbers):
                    socketio.emit('new_notification', socket_payload, room=f"student_{sn}")
                logger.info("Socket notification emitted to %d parents", len(parent_ids))
            except Exception as se:
                logger.debug("Socket emission skipped/failed: %s", se)

            # 3. FCM Delivery (Optional Fallback)
            if FIREBASE_SERVER_KEY:
                for token in set(fcm_tokens):
                    send_fcm_notification(token, title, body, data)
                    
        except Exception as e:
            logger.warning("notify_parent_async error: %s", e)
            
    threading.Thread(target=_worker, daemon=True).start()
