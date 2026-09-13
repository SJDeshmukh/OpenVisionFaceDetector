import os
import re
import json
import logging
import threading
import requests
from datetime import datetime

logger = logging.getLogger("evolution_whatsapp")

EVOLUTION_API_URL = os.environ.get("EVOLUTION_API_URL", "http://localhost:8080").rstrip("/")
EVOLUTION_API_KEY = os.environ.get("EVOLUTION_API_KEY", "YOUR_SECURE_GLOBAL_API_KEY_2026")


def _headers():
    return {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }


def get_instance_name(vendor_id):
    """Generates standardized Evolution API instance name per vendor."""
    return f"tapinx_vendor_{vendor_id}"


def clean_phone_number(phone):
    """Sanitizes phone numbers for WhatsApp delivery."""
    if not phone:
        return None
    cleaned = "".join(filter(str.isdigit, str(phone)))
    if not cleaned:
        return None
    # If 10 digits (e.g. Indian mobile number), prepend 91
    if len(cleaned) == 10:
        cleaned = "91" + cleaned
    return cleaned


def get_db():
    from utils import get_db_connection
    return get_db_connection()


def get_or_create_settings(vendor_id):
    """Fetches or initializes the vendor_whatsapp_settings record."""
    conn = get_db()
    c = conn.cursor()
    instance_name = get_instance_name(vendor_id)
    try:
        c.execute("""
            SELECT id, vendor_id, instance_name, phone_number, status, 
                   auto_punch_alerts, auto_leave_alerts, auto_advance_alerts, auto_late_alerts, 
                   last_connected_at 
            FROM vendor_whatsapp_settings 
            WHERE vendor_id = ?
        """, (vendor_id,))
        row = c.fetchone()
        if not row:
            c.execute("""
                INSERT INTO vendor_whatsapp_settings 
                (vendor_id, instance_name, status, auto_punch_alerts, auto_leave_alerts, auto_advance_alerts, auto_late_alerts, created_at, updated_at)
                VALUES (?, ?, 'disconnected', 1, 1, 1, 0, ?, ?)
            """, (vendor_id, instance_name, datetime.utcnow(), datetime.utcnow()))
            conn.commit()
            c.execute("""
                SELECT id, vendor_id, instance_name, phone_number, status, 
                       auto_punch_alerts, auto_leave_alerts, auto_advance_alerts, auto_late_alerts, 
                       last_connected_at 
                FROM vendor_whatsapp_settings 
                WHERE vendor_id = ?
            """, (vendor_id,))
            row = c.fetchone()
        
        # Convert row to dict
        keys = ['id', 'vendor_id', 'instance_name', 'phone_number', 'status', 
                'auto_punch_alerts', 'auto_leave_alerts', 'auto_advance_alerts', 'auto_late_alerts', 
                'last_connected_at']
        if hasattr(row, 'keys'):
            return dict(row)
        return dict(zip(keys, row))
    except Exception as e:
        logger.error(f"Error fetching/creating vendor whatsapp settings: {e}")
        return None
    finally:
        conn.close()


def update_settings(vendor_id, data):
    """Updates operational notification preferences or phone number."""
    conn = get_db()
    c = conn.cursor()
    try:
        fields = []
        params = []
        for key in ['phone_number', 'status', 'auto_punch_alerts', 'auto_leave_alerts', 'auto_advance_alerts', 'auto_late_alerts']:
            if key in data:
                fields.append(f"{key} = ?")
                val = data[key]
                if isinstance(val, bool):
                    val = 1 if val else 0
                params.append(val)
        
        if 'last_connected_at' in data:
            fields.append("last_connected_at = ?")
            params.append(data['last_connected_at'])

        fields.append("updated_at = ?")
        params.append(datetime.utcnow())
        params.append(vendor_id)

        sql = f"UPDATE vendor_whatsapp_settings SET {', '.join(fields)} WHERE vendor_id = ?"
        c.execute(sql, tuple(params))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating vendor whatsapp settings: {e}")
        return False
    finally:
        conn.close()


# --- Evolution API Operations ---

def ensure_instance(vendor_id):
    """Creates the Baileys instance in Evolution API if it doesn't already exist."""
    instance_name = get_instance_name(vendor_id)
    url = f"{EVOLUTION_API_URL}/instance/create"
    payload = {
        "instanceName": instance_name,
        "token": f"token_{vendor_id}",
        "qrcode": True,
        "integration": "WHATSAPP-BAILEYS"
    }
    try:
        res = requests.post(url, json=payload, headers=_headers(), timeout=10)
        logger.info(f"Evolution API instance creation response for {instance_name}: {res.status_code}")
        return res.json()
    except Exception as e:
        logger.warning(f"Failed to call instance/create (instance may already exist): {e}")
        return {"error": str(e)}


def fetch_qr_code(vendor_id):
    """Requests connection QR code from Evolution API."""
    ensure_instance(vendor_id)
    instance_name = get_instance_name(vendor_id)
    url = f"{EVOLUTION_API_URL}/instance/connect/{instance_name}"
    try:
        res = requests.get(url, headers=_headers(), timeout=10)
        data = res.json()
        qr_b64 = data.get("base64")
        pairing_code = data.get("pairingCode") or data.get("code")
        
        # Also update status to 'connecting'
        update_settings(vendor_id, {"status": "connecting"})
        
        return {
            "success": True,
            "qr_code": qr_b64,
            "pairing_code": pairing_code,
            "instance_name": instance_name
        }
    except Exception as e:
        logger.error(f"Error fetching QR code from Evolution API: {e}")
        return {"success": False, "error": str(e)}


def sync_connection_state(vendor_id):
    """Checks the live instance connection state in Evolution API and updates DB."""
    instance_name = get_instance_name(vendor_id)
    url = f"{EVOLUTION_API_URL}/instance/connectionState/{instance_name}"
    try:
        res = requests.get(url, headers=_headers(), timeout=6)
        if res.status_code == 200:
            data = res.json()
            state = data.get("instance", {}).get("state", "disconnected")
            
            # Map Evolution API states ('open', 'connecting', 'close')
            normalized_status = "connected" if state == "open" else ("connecting" if state == "connecting" else "disconnected")
            updates = {"status": normalized_status}
            
            # If connected, attempt to fetch instance profile to resolve the phone number
            if normalized_status == "connected":
                updates["last_connected_at"] = datetime.utcnow()
                try:
                    fetch_url = f"{EVOLUTION_API_URL}/instance/fetchInstances?instanceName={instance_name}"
                    f_res = requests.get(fetch_url, headers=_headers(), timeout=5)
                    if f_res.status_code == 200:
                        inst_list = f_res.json()
                        inst_data = inst_list[0] if isinstance(inst_list, list) and len(inst_list) > 0 else (inst_list.get("instance", {}) if isinstance(inst_list, dict) else {})
                        owner_jid = inst_data.get("owner") or inst_data.get("number") or ""
                        if owner_jid:
                            detected_number = owner_jid.split("@")[0]
                            updates["phone_number"] = detected_number
                except Exception as ex:
                    logger.debug(f"Could not resolve instance owner JID: {ex}")

            update_settings(vendor_id, updates)
            settings = get_or_create_settings(vendor_id)
            return {"success": True, "settings": settings}
        else:
            update_settings(vendor_id, {"status": "disconnected"})
            settings = get_or_create_settings(vendor_id)
            return {"success": True, "settings": settings}
    except Exception as e:
        logger.error(f"Error checking Evolution API connection state: {e}")
        settings = get_or_create_settings(vendor_id)
        return {"success": False, "error": str(e), "settings": settings}


def disconnect_instance(vendor_id):
    """Logs out and disconnects the WhatsApp Web instance."""
    instance_name = get_instance_name(vendor_id)
    url = f"{EVOLUTION_API_URL}/instance/logout/{instance_name}"
    try:
        requests.delete(url, headers=_headers(), timeout=8)
    except Exception as e:
        logger.warning(f"Error sending logout to Evolution API: {e}")
    
    update_settings(vendor_id, {
        "status": "disconnected"
    })
    return {"success": True, "message": "WhatsApp instance disconnected"}


def send_whatsapp_text(vendor_id, to_phone, message_text):
    """Dispatches a text message via Evolution API."""
    clean_phone = clean_phone_number(to_phone)
    if not clean_phone:
        logger.warning(f"Cannot send WhatsApp: invalid phone {to_phone}")
        return {"success": False, "error": "Invalid phone number"}

    instance_name = get_instance_name(vendor_id)
    url = f"{EVOLUTION_API_URL}/message/sendText/{instance_name}"
    payload = {
        "number": clean_phone,
        "text": message_text
    }
    try:
        res = requests.post(url, json=payload, headers=_headers(), timeout=10)
        logger.info(f"Evolution API message dispatch to {clean_phone}: {res.status_code}")
        return res.json()
    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {e}")
        return {"success": False, "error": str(e)}


# --- Automated Operational Event Dispatchers (Async Background Threads) ---

def notify_punch_event_async(vendor_id, person_id, punch_type, timestamp, is_late=0, location="Kiosk"):
    """Background thread worker to send attendance punch alert."""
    def worker():
        try:
            settings = get_or_create_settings(vendor_id)
            if not settings or not settings.get('auto_punch_alerts') or settings.get('status') != 'connected':
                return

            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT name, phone, department FROM faces WHERE id = ? AND vendor_id = ?", (person_id, vendor_id))
            person = c.fetchone()
            if not person:
                conn.close()
                return
            
            p_name = person[0] if not hasattr(person, 'keys') else person['name']
            p_phone = person[1] if not hasattr(person, 'keys') else person['phone']
            p_dept = person[2] if not hasattr(person, 'keys') else person['department']

            # Format timestamp nicely
            if isinstance(timestamp, str):
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', ''))
                    ts_label = dt.strftime('%I:%M %p, %d-%b-%Y')
                except Exception:
                    ts_label = timestamp
            elif hasattr(timestamp, 'strftime'):
                ts_label = timestamp.strftime('%I:%M %p, %d-%b-%Y')
            else:
                ts_label = str(timestamp)

            action_label = "Checked In" if str(punch_type).upper() in ("CHECK_IN", "IN", "PUNCH IN") else "Checked Out"
            late_text = "\n⚠️ *Notice: Late mark recorded.*" if is_late else ""

            msg = (
                f"✅ *TapInX Attendance Verified*\n\n"
                f"👤 *Person:* {p_name}\n"
                f"🏢 *Department:* {p_dept or 'General'}\n"
                f"🕒 *Time:* {ts_label}\n"
                f"📍 *Status:* {action_label}{late_text}\n\n"
                f"_Automated notification from TapInX Biometric System._"
            )

            # 1. Send to Employee
            if p_phone:
                send_whatsapp_text(vendor_id, p_phone, msg)

            # 2. Check if Parent Alert is needed (Student/Campus vertical)
            c.execute("SELECT parent_phone FROM student_parents WHERE student_id = ? AND vendor_id = ?", (person_id, vendor_id))
            parent_row = c.fetchone()
            if parent_row:
                parent_phone = parent_row[0] if not hasattr(parent_row, 'keys') else parent_row['parent_phone']
                if parent_phone:
                    parent_msg = (
                        f"🏫 *Campus Attendance Alert*\n\n"
                        f"Dear Parent,\n"
                        f"Your ward *{p_name}* has {action_label.lower()} at *{ts_label}*.\n\n"
                        f"_TapInX Campus Safety Monitoring._"
                    )
                    send_whatsapp_text(vendor_id, parent_phone, parent_msg)

            conn.close()
        except Exception as e:
            logger.error(f"Error in notify_punch_event_async worker: {e}", exc_info=True)

    threading.Thread(target=worker, daemon=True).start()


def notify_leave_event_async(vendor_id, leave_request_id, status_update):
    """Background thread worker for leave & gate-pass updates."""
    def worker():
        try:
            settings = get_or_create_settings(vendor_id)
            if not settings or not settings.get('auto_leave_alerts') or settings.get('status') != 'connected':
                return

            conn = get_db()
            c = conn.cursor()
            c.execute("""
                SELECT lr.leave_type, lr.start_date, lr.end_date, lr.reason, lr.final_status,
                       f.name, f.phone, f.department
                FROM leave_requests lr
                LEFT JOIN faces f ON f.id = lr.student_id
                WHERE lr.id = ? AND lr.vendor_id = ?
            """, (leave_request_id, vendor_id))
            row = c.fetchone()
            if not row:
                conn.close()
                return

            l_type = row[0] if not hasattr(row, 'keys') else row['leave_type']
            s_date = row[1] if not hasattr(row, 'keys') else row['start_date']
            e_date = row[2] if not hasattr(row, 'keys') else row['end_date']
            p_name = row[5] if not hasattr(row, 'keys') else row['name']
            p_phone = row[6] if not hasattr(row, 'keys') else row['phone']

            status_label = str(status_update).upper()
            status_icon = "✅" if status_label == "APPROVED" else ("❌" if status_label == "REJECTED" else "ℹ️")

            msg = (
                f"{status_icon} *Leave Request Update: {status_label}*\n\n"
                f"👤 *Employee / Student:* {p_name}\n"
                f"📝 *Type:* {str(l_type).title()}\n"
                f"📅 *Duration:* {s_date} to {e_date}\n"
                f"📊 *Status:* {status_label}\n\n"
                f"_TapInX Workforce Portal._"
            )

            if p_phone:
                send_whatsapp_text(vendor_id, p_phone, msg)

            conn.close()
        except Exception as e:
            logger.error(f"Error in notify_leave_event_async worker: {e}", exc_info=True)

    threading.Thread(target=worker, daemon=True).start()


def notify_advance_event_async(vendor_id, advance_id, status_update):
    """Background thread worker for Owner Advance updates."""
    def worker():
        try:
            settings = get_or_create_settings(vendor_id)
            if not settings or not settings.get('auto_advance_alerts') or settings.get('status') != 'connected':
                return

            conn = get_db()
            c = conn.cursor()
            c.execute("""
                SELECT a.amount, a.reason, a.status, f.name, f.phone
                FROM advances a
                LEFT JOIN faces f ON f.id = a.person_id
                WHERE a.id = ? AND a.vendor_id = ?
            """, (advance_id, vendor_id))
            row = c.fetchone()
            if not row:
                conn.close()
                return

            amount = row[0] if not hasattr(row, 'keys') else row['amount']
            reason = row[1] if not hasattr(row, 'keys') else row['reason']
            p_name = row[3] if not hasattr(row, 'keys') else row['name']
            p_phone = row[4] if not hasattr(row, 'keys') else row['phone']

            status_label = str(status_update).upper()
            status_icon = "💰" if status_label == "APPROVED" else "ℹ️"

            msg = (
                f"{status_icon} *Salary Advance Request: {status_label}*\n\n"
                f"👤 *Employee:* {p_name}\n"
                f"💵 *Amount:* ₹{amount:,.2f}\n"
                f"📝 *Note:* {reason or 'Personal advance'}\n"
                f"📊 *Status:* {status_label}\n\n"
                f"_TapInX Executive Finance Management._"
            )

            if p_phone:
                send_whatsapp_text(vendor_id, p_phone, msg)

            conn.close()
        except Exception as e:
            logger.error(f"Error in notify_advance_event_async worker: {e}", exc_info=True)

    threading.Thread(target=worker, daemon=True).start()
