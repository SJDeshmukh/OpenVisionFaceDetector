import os
import json
import threading
import logging
import time

logger = logging.getLogger("notifications")

# --- FCM v1 (firebase-admin SDK) ---
# Set GOOGLE_APPLICATION_CREDENTIALS=/path/to/serviceAccountKey.json
# OR set FIREBASE_CREDENTIALS_JSON='{ ... full JSON ... }' as an env var
# Then set FIREBASE_PROJECT_ID to your Firebase project ID.
#
# --- FCM Legacy fallback (deprecated by Google, June 2024) ---
# Set FIREBASE_SERVER_KEY=<key from Firebase Console → Project Settings → Cloud Messaging>
# Only used if firebase-admin is NOT configured.

FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "")
FIREBASE_SERVER_KEY = os.environ.get("FIREBASE_SERVER_KEY", "")  # legacy fallback

_firebase_app = None
_firebase_init_attempted = False


def _try_init_firebase():
    global _firebase_app, _firebase_init_attempted
    if _firebase_init_attempted:
        return _firebase_app
    _firebase_init_attempted = True
    if not FIREBASE_PROJECT_ID:
        return None
    try:
        import firebase_admin
        from firebase_admin import credentials as fb_creds

        if firebase_admin._apps:
            _firebase_app = firebase_admin.get_app()
            return _firebase_app

        # Priority 1: inline JSON env var (good for Railway/Render secrets)
        inline_json = os.environ.get("FIREBASE_CREDENTIALS_JSON", "").strip()
        if inline_json:
            cred = fb_creds.Certificate(json.loads(inline_json))
        else:
            # Priority 2: file path via GOOGLE_APPLICATION_CREDENTIALS (standard ADC)
            path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "firebase-credentials.json")
            if not os.path.isfile(path):
                logger.warning("FCM v1: No credentials found. Set FIREBASE_CREDENTIALS_JSON or GOOGLE_APPLICATION_CREDENTIALS.")
                return None
            cred = fb_creds.Certificate(path)

        _firebase_app = firebase_admin.initialize_app(cred)
        logger.info("FCM v1: firebase-admin initialized for project '%s'", FIREBASE_PROJECT_ID)
        return _firebase_app
    except ImportError:
        logger.warning("FCM v1: firebase-admin not installed. Run: pip install firebase-admin")
    except Exception as e:
        logger.warning("FCM v1: init failed — %s", e)
    return None


def _send_fcm_v1(fcm_token: str, title: str, body: str, data: dict = None) -> bool:
    """Send via FCM v1 API using firebase-admin SDK."""
    app = _try_init_firebase()
    if not app:
        return False
    try:
        from firebase_admin import messaging
        android_config = messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id="parent_attendance_alert",
                sound="default",
                priority="max",
                visibility="public",
                tag="attendance_alert",
            ),
        )
        # Send as combined message: system auto-shows when app is closed,
        # onMessageReceived fires when app is foreground.
        msg = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            android=android_config,
            data={str(k): str(v) for k, v in (data or {}).items()} | {
                "type": "attendance",
                "channel_id": "parent_attendance_alert",
            },
            token=fcm_token,
        )
        response = messaging.send(msg)
        logger.info("FCM v1 sent: %s → %s...", response, fcm_token[:10])
        return True
    except Exception as e:
        logger.warning("FCM v1 send failed: %s", e)
        return False


def _send_fcm_legacy(fcm_token: str, title: str, body: str, data: dict = None) -> bool:
    """Legacy FCM HTTP API fallback (Google shut it down June 2024; use v1 if possible)."""
    if not FIREBASE_SERVER_KEY:
        return False
    try:
        import requests as _req
        payload = {
            "to": fcm_token,
            "priority": "high",
            "time_to_live": 3600,
            "notification": {
                "title": title,
                "body": body,
                "sound": "default",
                "tag": "attendance_alert",
                "android_channel_id": "parent_attendance_alert",
            },
            "android": {
                "priority": "high",
                "notification": {
                    "channel_id": "parent_attendance_alert",
                    "sound": "default",
                    "priority": "max",
                    "visibility": "public",
                    "tag": "attendance_alert",
                },
            },
            "data": {
                "type": "attendance",
                "channel_id": "parent_attendance_alert",
                **{str(k): str(v) for k, v in (data or {}).items()},
            },
        }
        resp = _req.post(
            "https://fcm.googleapis.com/fcm/send",
            headers={
                "Authorization": f"key={FIREBASE_SERVER_KEY}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=8,
        )
        ok = resp.status_code == 200
        if not ok:
            logger.warning("FCM legacy failure %s: %s", resp.status_code, resp.text[:200])
        else:
            logger.info("FCM legacy sent to %s...", fcm_token[:10])
        return ok
    except Exception as e:
        logger.warning("FCM legacy send failed: %s", e)
        return False


def send_fcm_notification(fcm_token: str, title: str, body: str, data: dict = None) -> bool:
    """Send FCM push notification. Tries v1 API first, falls back to legacy."""
    if not fcm_token:
        return False
    # v1 API preferred (works even when app is fully closed)
    if FIREBASE_PROJECT_ID:
        return _send_fcm_v1(fcm_token, title, body, data)
    # Legacy fallback
    if FIREBASE_SERVER_KEY:
        return _send_fcm_legacy(fcm_token, title, body, data)
    logger.warning("FCM: No credentials configured. Set FIREBASE_PROJECT_ID + FIREBASE_CREDENTIALS_JSON (v1) or FIREBASE_SERVER_KEY (legacy).")
    return False


def notify_parent_async(person_id, vendor_id, title: str, body: str, data: dict = None):
    """Fire-and-forget notification to parent(s) linked to the student.

    Delivery layers:
      1. Socket.IO  — instant when app is open / service running
      2. FCM push   — reaches device even when app is fully closed (requires Firebase setup)
    """
    def _worker():
        try:
            try:
                from utils import get_db_connection
            except ImportError:
                from .utils import get_db_connection
            conn = get_db_connection()
            c = conn.cursor()
            is_pg = getattr(conn, "_is_pg", False)
            ph = "%s" if is_pg else "?"

            # Find parents linked to this student
            c.execute(f"""
                SELECT pu.id, pu.fcm_token, pu.student_number
                FROM student_parents sp
                JOIN parent_users pu ON pu.id = sp.parent_id
                WHERE sp.person_id = {ph} AND sp.vendor_id = {ph}
            """, (person_id, vendor_id))
            links = c.fetchall() or []

            # Self-healing: if no explicit link, look up by student_number in faces
            if not links:
                c.execute(f"SELECT phone, custom_data FROM faces WHERE id = {ph}", (person_id,))
                found = c.fetchone()
                if found:
                    s_cd = found[1] if isinstance(found, (list, tuple)) else found.get("custom_data")
                    try:
                        from utils import extract_student_number_from_custom_data
                    except ImportError:
                        from .utils import extract_student_number_from_custom_data
                    s_num = extract_student_number_from_custom_data(s_cd, search_term=None)
                    if s_num:
                        c.execute(
                            f"SELECT id, fcm_token, student_number FROM parent_users WHERE vendor_id = {ph} AND student_number = {ph}",
                            (vendor_id, s_num),
                        )
                        links = c.fetchall() or []

            parent_ids, fcm_tokens, student_numbers = [], [], []
            for row in links:
                pid   = row[0] if isinstance(row, (list, tuple)) else row.get("id")
                token = row[1] if isinstance(row, (list, tuple)) else row.get("fcm_token")
                sn    = row[2] if isinstance(row, (list, tuple)) else row.get("student_number")
                if pid:   parent_ids.append(pid)
                if token: fcm_tokens.append(token)
                if sn:    student_numbers.append(sn)

            conn.close()

            # Layer 1 — Socket.IO (instant, requires app process to be running)
            try:
                try:
                    from app import socketio
                except ImportError:
                    from .app import socketio
                payload = {
                    "title": title,
                    "body": body,
                    "data": data or {},
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for pid in set(parent_ids):
                    socketio.emit("new_notification", payload, room=f"parent_{pid}")
                for sn in set(student_numbers):
                    socketio.emit("new_notification", payload, room=f"student_{vendor_id}_{sn}")
                logger.info("Socket notification emitted to %d parents", len(parent_ids))
            except Exception as se:
                logger.debug("Socket emission skipped/failed: %s", se)

            # Layer 2 — FCM push (works even when app is fully closed)
            for token in set(fcm_tokens):
                send_fcm_notification(token, title, body, data)

        except Exception as e:
            logger.warning("notify_parent_async error: %s", e)

    threading.Thread(target=_worker, daemon=True).start()
