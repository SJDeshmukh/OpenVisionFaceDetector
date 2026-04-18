import json
import logging

logger = logging.getLogger(__name__)

def hydrate_registration_config(vendor_id, config, conn=None):
    """
    Hydrates registration configuration with dynamic data sources.
    Currently supports mapping 'leave_departments' to options.
    """
    if not isinstance(config, list):
        return config

    # Ensure a dynamic department field exists if leave management is enabled
    updated_config = list(config)
    from db_factory import get_db_connection
    conn_internal = None
    if conn is None:
        conn_internal = get_db_connection()
        conn = conn_internal

    try:
        # Check features
        is_pg = getattr(conn, "_is_pg", False)
        c = conn.cursor()
        if is_pg:
            c.execute("SELECT features FROM subscriptions WHERE vendor_id = %s", (vendor_id,))
        else:
            c.execute("SELECT features FROM subscriptions WHERE vendor_id = ?", (vendor_id,))
        
        sub_row = c.fetchone()
        features = []
        if sub_row:
            try:
                features = json.loads(sub_row[0] or '[]')
            except:
                pass
        
        has_leave = 'leave_management' in features
        
        if has_leave:
            # Check if any field already uses the department/branch keys or is dynamic
            has_relevant_field = False
            for f in updated_config:
                if not isinstance(f, dict): continue
                key = (f.get('field') or f.get('key') or "").lower()
                source = f.get('options_source')
                if key in ['department', 'branch'] or source == 'leave_departments':
                    has_relevant_field = True
                    break
            
            if not has_relevant_field:
                # Automagically add the field
                updated_config.append({
                    "field": "department",
                    "label": "Branch / Subject",
                    "type": "select",
                    "options_source": "leave_departments",
                    "required": True,
                    "enabled": True
                })
                logger.info(f"Automatically added Department field for vendor {vendor_id} (Leave Management active)")
    except Exception as e:
        logger.error(f"Error checking features for auto-config: {e}")
    finally:
        if conn_internal:
            conn_internal.close()

    hydrated_config = []
    cached_depts = None

    for field in updated_config:
        if not isinstance(field, dict):
            hydrated_config.append(field)
            continue
            
        new_field = dict(field)
        source = new_field.get('options_source')
        field_key = (new_field.get('field') or new_field.get('key') or "").lower()
        
        # 1. Dynamic Dropdown (Leave Departments Source)
        if source == 'leave_departments':
            if cached_depts is None:
                cached_depts = _fetch_vendor_departments(vendor_id, conn)
            
            # Map departments to options
            new_field['options'] = list(cached_depts) if cached_depts else []
            logger.debug(f"Hydrated field {new_field.get('field')} with {len(new_field['options'])} departments for vendor {vendor_id}")
            
        # 2. Smart Sync for Static Dropdowns (Key based matching)
        elif field_key in ['department', 'branch'] and new_field.get('type') in ['select', 'multiselect', 'dropdown']:
            if cached_depts is None:
                cached_depts = _fetch_vendor_departments(vendor_id, conn)
            
            if cached_depts:
                existing_options = new_field.get('options', [])
                if not isinstance(existing_options, list):
                    existing_options = []
                
                # Case-insensitive comparison for duplicates
                existing_lower = {str(opt).strip().lower() for opt in existing_options}
                added_any = False
                for dept in cached_depts:
                    if str(dept).strip().lower() not in existing_lower:
                        existing_options.append(dept)
                        added_any = True
                
                if added_any:
                    new_field['options'] = existing_options
                    logger.info(f"Smart Sync: Appended {len(cached_depts)} depts to '{field_key}' for vendor {vendor_id}")

        hydrated_config.append(new_field)
    
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
