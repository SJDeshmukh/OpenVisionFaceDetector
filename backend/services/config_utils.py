import json
import logging
import re

logger = logging.getLogger(__name__)

_REGISTRATION_FIELD_ALIASES = {
    'full_name': 'name',
    'employee_name': 'name',
    'mobile': 'phone',
    'mobile_number': 'phone',
    'phone_number': 'phone',
    'student_phone': 'phone',
    'contact_phone': 'phone',
    'dept': 'department',
    'work_shift': 'shift',
}


def canonical_registration_field(value):
    """Return the stable payload key used for registration validation."""
    key = re.sub(r'[^a-z0-9]+', '_', str(value or '').strip().lower()).strip('_')
    return _REGISTRATION_FIELD_ALIASES.get(key, key)


def validate_registration_values(config, core_values=None, custom_values=None):
    """
    Validate enabled required registration fields against core and dynamic data.

    Returns ``None`` when valid, otherwise a small error object suitable for an
    API 400 response.  Aliases allow older mobile clients to keep working while
    SuperAdmin labels and field names change.
    """
    if not isinstance(config, list):
        return None

    values = {}
    for source in (custom_values or {}, core_values or {}):
        if not isinstance(source, dict):
            continue
        for raw_key, raw_value in source.items():
            key = canonical_registration_field(raw_key)
            # Core columns take precedence over duplicate custom aliases.
            if key and (key not in values or source is core_values):
                values[key] = raw_value

    for item in normalize_registration_config(config):
        if not item.get('enabled', True) or not item.get('required', False):
            continue
        raw_field = item.get('field') or item.get('name')
        key = canonical_registration_field(raw_field)
        value = values.get(key)
        if isinstance(value, (list, tuple, set, dict)):
            missing = len(value) == 0
        else:
            text = str(value or '').strip()
            missing = not text or (key == 'shift' and text.casefold() == 'no shift')
        if missing:
            label = str(item.get('label') or raw_field or key).strip() or key
            return {
                'error': f'{label} is required',
                'field': str(raw_field or key),
            }
    return None


def load_registration_config(vendor_id, conn):
    """Load the same effective registration schema returned to mobile clients."""
    cursor = conn.cursor()
    cursor.execute('SELECT registration_config FROM vendors WHERE id = ?', (vendor_id,))
    row = cursor.fetchone()
    raw = row[0] if row else None
    try:
        config = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        config = []
    if not isinstance(config, list):
        config = []

    if not config:
        try:
            cursor.execute('SELECT fields FROM bulk_attendance_config WHERE vendor_id = ?', (vendor_id,))
            fallback = cursor.fetchone()
            raw_fields = fallback[0] if fallback else None
            fields = json.loads(raw_fields) if isinstance(raw_fields, str) else raw_fields
            if isinstance(fields, list):
                for item in fields:
                    if not isinstance(item, dict):
                        continue
                    field = item.get('field') or item.get('name')
                    if field:
                        config.append({
                            'field': field,
                            'label': item.get('label') or field,
                            'type': item.get('type') or 'text',
                            'required': bool(item.get('required', False)),
                            'enabled': item.get('enabled', True) is not False,
                            'options': item.get('options') or [],
                        })
        except Exception as exc:
            logger.debug('Could not load registration fallback for vendor %s: %s', vendor_id, exc)

    return hydrate_registration_config(vendor_id, normalize_registration_config(config), conn=conn)

def normalize_registration_config(config):
    """Return a deterministic registration schema with text as the default type."""
    if not isinstance(config, list):
        raise ValueError("registration configuration must be a list")
    normalized = []
    seen = set()
    for raw in config:
        if not isinstance(raw, dict):
            continue
        field = str(raw.get('field') or raw.get('key') or raw.get('name') or '').strip()
        if not field or field.lower() in seen:
            continue
        seen.add(field.lower())
        item = dict(raw)
        item['field'] = field
        item.pop('key', None)
        item['label'] = str(raw.get('label') or field).strip() or field
        item['type'] = str(raw.get('type') or 'text').strip().lower() or 'text'
        item['required'] = bool(raw.get('required', False))
        item['enabled'] = raw.get('enabled', True) is not False
        normalized.append(item)
    return normalized

def hydrate_registration_config(vendor_id, config, conn=None):
    """
    Hydrates registration configuration with dynamic data sources.
    Timetable shifts are exposed as a registration field so newly created
    shifts immediately become assignable from every registration client.
    """
    if not isinstance(config, list):
        return config

    updated_config = list(config)
    conn_internal = None
    if conn is None:
        from db_factory import get_db_connection
        conn_internal = get_db_connection()
        conn = conn_internal

    hydrated_config = []
    cached_depts = None
    cached_shifts = None
    has_shift_field = False

    for field in updated_config:
        if not isinstance(field, dict):
            hydrated_config.append(field)
            continue
            
        new_field = dict(field)
        new_field['type'] = str(new_field.get('type') or 'text').strip().lower() or 'text'
        source = new_field.get('options_source')
        field_name = str(new_field.get('field') or new_field.get('name') or '').strip()
        is_shift_field = field_name.lower().replace('-', '_').replace(' ', '_') in {
            'shift', 'work_shift'
        }
        if is_shift_field:
            has_shift_field = True
            if cached_shifts is None:
                cached_shifts = _fetch_vendor_shifts(vendor_id, conn)
            # Faces and attendance persist this core value in ``faces.shift``.
            # Keep the registration key canonical even if an older schema used
            # labels such as "Work Shift".
            new_field['field'] = 'shift'
            new_field['name'] = 'shift'
            new_field['type'] = 'select'
            new_field['options'] = list(cached_shifts)
            new_field['options_source'] = 'company_shifts'
        # Other dynamic lists are populated only when the Superadmin explicitly
        # configured their source.
        if source == 'leave_departments':
            if cached_depts is None:
                cached_depts = _fetch_vendor_departments(vendor_id, conn)
            
            # Map departments to options
            new_field['options'] = list(cached_depts) if cached_depts else []
            logger.debug(f"Hydrated field {new_field.get('field')} with {len(new_field['options'])} departments for vendor {vendor_id}")

        hydrated_config.append(new_field)

    if not has_shift_field:
        if cached_shifts is None:
            cached_shifts = _fetch_vendor_shifts(vendor_id, conn)
        if cached_shifts:
            hydrated_config.append({
                'field': 'shift',
                'name': 'shift',
                'label': 'Shift',
                'type': 'select',
                'required': False,
                'enabled': True,
                'options_source': 'company_shifts',
                'options': list(cached_shifts),
            })
    
    if conn_internal:
        conn_internal.close()
    return hydrated_config


def _fetch_vendor_shifts(vendor_id, conn=None):
    """Return the vendor's active timetable shift names in display order."""
    should_close = False
    if conn is None:
        from db_factory import get_db_connection
        conn = get_db_connection()
        should_close = True

    try:
        c = conn.cursor()
        c.execute("SELECT shifts FROM companies WHERE vendor_id = ? ORDER BY id", (vendor_id,))
        rows = c.fetchall()
        names = []
        seen = set()
        for row in rows:
            raw_shifts = row[0] if row else None
            try:
                shifts = json.loads(raw_shifts) if isinstance(raw_shifts, str) else raw_shifts
            except (TypeError, ValueError, json.JSONDecodeError):
                shifts = []
            if not isinstance(shifts, list):
                continue
            for shift in shifts:
                if not isinstance(shift, dict) or shift.get('active', True) is False:
                    continue
                name = str(shift.get('name') or '').strip()
                key = name.casefold()
                if name and key not in seen:
                    seen.add(key)
                    names.append(name)
        return names
    except Exception as exc:
        logger.debug("Could not hydrate timetable shifts for vendor %s: %s", vendor_id, exc)
        return []
    finally:
        if should_close:
            conn.close()

def _fetch_vendor_departments(vendor_id, conn=None):
    """Fetches the list of departments for a given vendor."""
    from db_factory import get_db_connection
    import sqlite3
    
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
        
    try:
        c = conn.cursor()
        # Use simple select, handle both SQLite and Postgres
        is_pg = getattr(conn, "_is_pg", False)
        if is_pg:
            c.execute("SELECT departments FROM vendors WHERE id = %s", (vendor_id,))
        else:
            c.execute("SELECT departments FROM vendors WHERE id = ?", (vendor_id,))
            
        res = c.fetchone()
        if res and res[0]:
            try:
                return json.loads(res[0])
            except Exception as e:
                logger.error(f"Error parsing departments for vendor {vendor_id}: {e}")
                return []
        return []
    except Exception as e:
        logger.error(f"Error fetching departments for vendor {vendor_id}: {e}")
        return []
    finally:
        if should_close:
            conn.close()
