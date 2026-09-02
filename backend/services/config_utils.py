import json
import logging

logger = logging.getLogger(__name__)

def normalize_registration_config(config):
    """Return a deterministic registration schema with text as the default type."""
    if not isinstance(config, list):
        raise ValueError("registration configuration must be a list")
    normalized = []
    seen = set()
    for raw in config:
        if not isinstance(raw, dict):
            continue
        field = str(raw.get('field') or raw.get('key') or '').strip()
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
    Currently supports mapping 'leave_departments' to options.
    """
    if not isinstance(config, list):
        return config

    # The stored list is authoritative. Feature flags must not silently inject
    # fields that the Superadmin did not configure.
    updated_config = list(config)
    from db_factory import get_db_connection
    conn_internal = None
    if conn is None:
        conn_internal = get_db_connection()
        conn = conn_internal

    hydrated_config = []
    cached_depts = None

    for field in updated_config:
        if not isinstance(field, dict):
            hydrated_config.append(field)
            continue
            
        new_field = dict(field)
        new_field['type'] = str(new_field.get('type') or 'text').strip().lower() or 'text'
        source = new_field.get('options_source')
        # Dynamic options are populated only when the Superadmin explicitly
        # configured a source. Field names alone must never pull in unrelated
        # business data or alter a static list.
        if source == 'leave_departments':
            if cached_depts is None:
                cached_depts = _fetch_vendor_departments(vendor_id, conn)
            
            # Map departments to options
            new_field['options'] = list(cached_depts) if cached_depts else []
            logger.debug(f"Hydrated field {new_field.get('field')} with {len(new_field['options'])} departments for vendor {vendor_id}")

        hydrated_config.append(new_field)
    
    if conn_internal:
        conn_internal.close()
    return hydrated_config

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
