import os
import json
import threading
import logging

logger = logging.getLogger("notifications")

FIREBASE_SERVER_KEY = os.environ.get("FIREBASE_SERVER_KEY", "")


def send_fcm_notification(fcm_token: str, title: str, body: str, data: dict = None) -> bool:
    """Send a high-priority FCM push notification.
    Requires FIREBASE_SERVER_KEY env var (Firebase Console → Project Settings → Cloud Messaging).
    """
    if not FIREBASE_SERVER_KEY or not fcm_token:
        return False
    try:
        import requests as _req
        payload = {
            "to": fcm_token,
            "priority": "high",
            "notification": {
                "title": title,
                "body": body,
                "sound": "default",
                "click_action": "FLUTTER_NOTIFICATION_CLICK"
            },
            "android": {
                "priority": "high",
                "notification": {
                    "channel_id": "parent_attendance",
                    "sound": "default",
                    "priority": "max",
                    "visibility": "public"
                }
            }
        }
        if data:
            payload["data"] = {str(k): str(v) for k, v in data.items()}

        resp = _req.post(
            "https://fcm.googleapis.com/fcm/send",
            headers={
                "Authorization": f"key={FIREBASE_SERVER_KEY}",
                "Content-Type": "application/json"
            },
            data=json.dumps(payload),
            timeout=6
        )
        if resp.status_code != 200:
            logger.warning("FCM response %s: %s", resp.status_code, resp.text[:200])
        return resp.status_code == 200
    except Exception as e:
        logger.warning("FCM send failed: %s", e)
        return False


def notify_parent_async(person_id, vendor_id, title: str, body: str, data: dict = None):
    """Fire-and-forget FCM notification to the parent linked to person_id."""
    def _worker():
        try:
            from utils import get_db_connection
            conn = get_db_connection()
            c = conn.cursor()
            # student_parents links a student (person_id) to their parent record
            c.execute("""
                SELECT pu.fcm_token
                FROM student_parents sp
                JOIN parent_users pu ON pu.id = sp.parent_id
                WHERE sp.person_id = ? AND sp.vendor_id = ?
                  AND pu.fcm_token IS NOT NULL AND pu.fcm_token != ''
            """, (person_id, vendor_id))
            rows = c.fetchall() or []
            conn.close()
            for row in rows:
                token = row[0] if isinstance(row, (list, tuple)) else row.get('fcm_token')
                if token:
                    send_fcm_notification(token, title, body, data)
        except Exception as e:
            logger.warning("notify_parent_async error: %s", e)
    threading.Thread(target=_worker, daemon=True).start()
