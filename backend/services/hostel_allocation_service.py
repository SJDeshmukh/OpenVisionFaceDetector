"""Transactional building, bed, and resident allocation operations."""

from datetime import datetime, timezone
import json


ADMIN_ROLES = {"super_admin", "vendor_admin", "admin", "owner"}
EDIT_ROLES = {"administrator", "warden"}
VALID_BED_REASONS = {"maintenance", "cleaning", "out_of_service", "other"}


class HostelAllocationError(ValueError):
    def __init__(self, message, status=400, code="INVALID_REQUEST"):
        super().__init__(message)
        self.status = status
        self.code = code


def _row(row, columns=None):
    if row is None:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    return dict(zip(columns or (), row))


def _json(value, fallback=None):
    fallback = {} if fallback is None else fallback
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback


def _dump(value):
    return json.dumps(value or {}, separators=(",", ":"))


def ensure_tables(conn):
    """Create the module schema for upgraded installations at first use."""
    c = conn.cursor()
    pg = bool(getattr(conn, "_is_pg", False))
    pk = "SERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts = "TIMESTAMP" if pg else "DATETIME"
    c.execute(f"CREATE TABLE IF NOT EXISTS hostel_buildings (id {pk}, vendor_id INTEGER NOT NULL, name TEXT NOT NULL, code TEXT, sort_order INTEGER NOT NULL DEFAULT 0, eligibility_rules TEXT NOT NULL DEFAULT '{{}}', created_at {ts} DEFAULT CURRENT_TIMESTAMP, UNIQUE(vendor_id, name))")
    c.execute(f"CREATE TABLE IF NOT EXISTS hostel_floors (id {pk}, vendor_id INTEGER NOT NULL, building_id INTEGER NOT NULL, name TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0, eligibility_rules TEXT NOT NULL DEFAULT '{{}}', created_at {ts} DEFAULT CURRENT_TIMESTAMP, UNIQUE(building_id, name))")
    c.execute(f"CREATE TABLE IF NOT EXISTS hostel_rooms (id {pk}, vendor_id INTEGER NOT NULL, floor_id INTEGER NOT NULL, room_number TEXT NOT NULL, room_type TEXT NOT NULL DEFAULT 'Standard', position_index INTEGER NOT NULL DEFAULT 0, eligibility_rules TEXT NOT NULL DEFAULT '{{}}', created_at {ts} DEFAULT CURRENT_TIMESTAMP, UNIQUE(floor_id, room_number))")
    c.execute(f"CREATE TABLE IF NOT EXISTS hostel_beds (id {pk}, vendor_id INTEGER NOT NULL, room_id INTEGER NOT NULL, bed_label TEXT NOT NULL, position_index INTEGER NOT NULL DEFAULT 0, availability_status TEXT NOT NULL DEFAULT 'available', unavailable_reason TEXT, unavailable_note TEXT, unavailable_from DATE, expected_reopening_date DATE, reservation_expires_at {ts}, reserved_for_person_id INTEGER, reservation_note TEXT, updated_at {ts} DEFAULT CURRENT_TIMESTAMP, UNIQUE(room_id, bed_label))")
    c.execute(f"CREATE TABLE IF NOT EXISTS hostel_allocations (id {pk}, vendor_id INTEGER NOT NULL, person_id INTEGER NOT NULL, bed_id INTEGER NOT NULL, allocated_at {ts} DEFAULT CURRENT_TIMESTAMP, allocated_by TEXT, UNIQUE(vendor_id, person_id), UNIQUE(bed_id))")
    c.execute(f"CREATE TABLE IF NOT EXISTS hostel_allocation_history (id {pk}, vendor_id INTEGER NOT NULL, person_id INTEGER NOT NULL, action TEXT NOT NULL, previous_bed_id INTEGER, new_bed_id INTEGER, actor_username TEXT, reason TEXT, override_reason TEXT, created_at {ts} DEFAULT CURRENT_TIMESTAMP)")
    c.execute(f"CREATE TABLE IF NOT EXISTS hostel_staff_permissions (id {pk}, vendor_id INTEGER NOT NULL, username TEXT NOT NULL, building_id INTEGER, access_role TEXT NOT NULL DEFAULT 'viewer', can_export INTEGER NOT NULL DEFAULT 0, can_override_eligibility INTEGER NOT NULL DEFAULT 0, can_view_resident_details INTEGER NOT NULL DEFAULT 0, created_at {ts} DEFAULT CURRENT_TIMESTAMP, updated_at {ts} DEFAULT CURRENT_TIMESTAMP, UNIQUE(vendor_id, username, building_id))")
    conn.commit()


def access_for(conn, vendor_id, username, system_role):
    if str(system_role or "").lower() in ADMIN_ROLES:
        return {
            "role": "administrator", "building_ids": None, "can_edit_layout": True,
            "can_allocate": True, "can_manage_permissions": True, "can_export": True,
            "can_manage_buildings": True, "can_manage_eligibility": True,
            "can_override_eligibility": True, "can_view_resident_details": True,
        }
    c = conn.cursor()
    c.execute("SELECT building_id, access_role, can_export, can_override_eligibility, can_view_resident_details FROM hostel_staff_permissions WHERE vendor_id = ? AND username = ?", (vendor_id, username))
    rows = c.fetchall() or []
    if not rows:
        raise HostelAllocationError("Hostel allocation access has not been assigned", 403, "FORBIDDEN")
    mapped = [_row(row, ("building_id", "access_role", "can_export", "can_override_eligibility", "can_view_resident_details")) for row in rows]
    roles = {str(item["access_role"] or "viewer").lower() for item in mapped}
    role = "warden" if "warden" in roles else "viewer"
    return {
        "role": role,
        "building_ids": [int(item["building_id"]) for item in mapped if item.get("building_id") is not None],
        "can_edit_layout": role == "warden", "can_allocate": role == "warden",
        "can_manage_permissions": False, "can_manage_buildings": False,
        "can_manage_eligibility": False,
        "can_export": any(bool(item.get("can_export")) for item in mapped),
        "can_override_eligibility": any(bool(item.get("can_override_eligibility")) for item in mapped),
        "can_view_resident_details": any(bool(item.get("can_view_resident_details")) for item in mapped),
    }


def require_permission(access, key, building_id=None):
    if not access.get(key):
        raise HostelAllocationError("You do not have permission for this action", 403, "FORBIDDEN")
    scope = access.get("building_ids")
    if building_id is not None and scope is not None and int(building_id) not in scope:
        raise HostelAllocationError("This building is outside your assigned scope", 403, "BUILDING_SCOPE_DENIED")


def _effective_bed_status(bed, occupied=False, now=None):
    if occupied:
        return "occupied"
    if str(bed.get("availability_status") or "available") == "unavailable":
        return "unavailable"
    expiry = bed.get("reservation_expires_at")
    if expiry:
        try:
            parsed = expiry if isinstance(expiry, datetime) else datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed > (now or datetime.now(timezone.utc)):
                return "reserved"
        except (TypeError, ValueError):
            return "reserved"
    return "available"


def _person_profile(row):
    data = _row(row, ("id", "name", "display_id", "phone", "department", "custom_data"))
    custom = _json(data.pop("custom_data", None), {})
    lowered = {str(key).strip().lower().replace(" ", "_"): value for key, value in custom.items()}
    data.update({
        "resident_id": data.get("display_id") or lowered.get("student_id") or lowered.get("resident_id") or data["id"],
        "gender": lowered.get("gender") or lowered.get("sex"),
        "academic_year": lowered.get("academic_year") or lowered.get("year") or lowered.get("class_year"),
        "resident_category": lowered.get("resident_category") or lowered.get("category") or lowered.get("person_type"),
        "custom": custom,
    })
    return data


def _merge_rules(*values):
    result = {}
    for value in values:
        for key, item in _json(value, {}).items():
            if item not in (None, "", [], {}):
                result[key] = item
    return result


def _eligibility_errors(person, rules):
    errors = []
    labels = {"gender": "gender", "academic_year": "academic year", "resident_category": "resident category"}
    for key, label in labels.items():
        allowed = rules.get(key)
        if allowed in (None, "", []):
            continue
        allowed_values = [str(item).strip().lower() for item in (allowed if isinstance(allowed, list) else [allowed])]
        actual = person.get(key)
        if actual in (None, ""):
            errors.append(f"Resident {label} is missing and requires review")
        elif str(actual).strip().lower() not in allowed_values:
            errors.append(f"Restricted to {', '.join(str(item) for item in (allowed if isinstance(allowed, list) else [allowed]))} ({label})")
    return errors


def get_state(conn, vendor_id, access):
    ensure_tables(conn)
    c = conn.cursor()
    scope = access.get("building_ids")
    c.execute("SELECT id, name, code, sort_order, eligibility_rules FROM hostel_buildings WHERE vendor_id = ? ORDER BY sort_order, name", (vendor_id,))
    buildings = [_row(row, ("id", "name", "code", "sort_order", "eligibility_rules")) for row in (c.fetchall() or [])]
    if scope is not None:
        buildings = [item for item in buildings if int(item["id"]) in scope]
    building_ids = [item["id"] for item in buildings]
    for building in buildings:
        building["eligibility_rules"] = _json(building.get("eligibility_rules"), {})
        c.execute("SELECT id, name, sort_order, eligibility_rules FROM hostel_floors WHERE vendor_id = ? AND building_id = ? ORDER BY sort_order, name", (vendor_id, building["id"]))
        floors = [_row(row, ("id", "name", "sort_order", "eligibility_rules")) for row in (c.fetchall() or [])]
        building["floors"] = floors
        for floor in floors:
            floor["eligibility_rules"] = _json(floor.get("eligibility_rules"), {})
            c.execute("SELECT id, room_number, room_type, position_index, eligibility_rules FROM hostel_rooms WHERE vendor_id = ? AND floor_id = ? ORDER BY position_index, room_number", (vendor_id, floor["id"]))
            rooms = [_row(row, ("id", "room_number", "room_type", "position_index", "eligibility_rules")) for row in (c.fetchall() or [])]
            floor["rooms"] = rooms
            for room in rooms:
                room["eligibility_rules"] = _json(room.get("eligibility_rules"), {})
                room["effective_eligibility"] = _merge_rules(building["eligibility_rules"], floor["eligibility_rules"], room["eligibility_rules"])
                c.execute("""SELECT b.id AS id, b.bed_label AS bed_label, b.position_index AS position_index,
                                    b.availability_status AS availability_status, b.unavailable_reason AS unavailable_reason,
                                    b.unavailable_note AS unavailable_note, b.unavailable_from AS unavailable_from,
                                    b.expected_reopening_date AS expected_reopening_date,
                                    b.reservation_expires_at AS reservation_expires_at,
                                    b.reserved_for_person_id AS reserved_for_person_id, b.reservation_note AS reservation_note,
                                    a.id AS allocation_id, a.person_id AS person_id,
                                    a.allocated_at AS allocated_at, a.allocated_by AS allocated_by,
                                    f.name AS person_name, f.display_id AS display_id, f.phone AS phone,
                                    f.department AS department, f.custom_data AS custom_data
                             FROM hostel_beds b
                             LEFT JOIN hostel_allocations a ON a.bed_id = b.id AND a.vendor_id = b.vendor_id
                             LEFT JOIN faces f ON f.id = a.person_id AND f.vendor_id = b.vendor_id
                             WHERE b.vendor_id = ? AND b.room_id = ? ORDER BY b.position_index, b.id""", (vendor_id, room["id"]))
                beds = []
                columns = ("id", "bed_label", "position_index", "availability_status", "unavailable_reason", "unavailable_note", "unavailable_from", "expected_reopening_date", "reservation_expires_at", "reserved_for_person_id", "reservation_note", "allocation_id", "person_id", "allocated_at", "allocated_by", "person_name", "display_id", "phone", "department", "custom_data")
                for raw in c.fetchall() or []:
                    bed = _row(raw, columns)
                    occupied = bed.get("allocation_id") is not None
                    bed["status"] = _effective_bed_status(bed, occupied)
                    if occupied:
                        profile = _person_profile((bed["person_id"], bed["person_name"], bed.get("display_id"), bed.get("phone"), bed.get("department"), bed.get("custom_data")))
                        if not access.get("can_view_resident_details"):
                            profile = {"id": profile["id"], "name": profile["name"], "resident_id": profile["resident_id"]}
                        bed["resident"] = profile
                    beds.append(bed)
                room["beds"] = beds
                counts = {key: sum(1 for bed in beds if bed["status"] == key) for key in ("occupied", "available", "reserved", "unavailable")}
                room["summary"] = {"total": len(beds), **counts}
            floor["summary"] = summarize_rooms(rooms)
        building["summary"] = summarize_rooms([room for floor in floors for room in floor["rooms"]])

    visible_bed_ids = {int(bed["id"]) for building in buildings for floor in building["floors"] for room in floor["rooms"] for bed in room["beds"]}
    c.execute("SELECT id, name, display_id, phone, department, custom_data FROM faces WHERE vendor_id = ? ORDER BY name", (vendor_id,))
    residents = [_person_profile(row) for row in (c.fetchall() or [])]
    c.execute("SELECT person_id, bed_id, allocated_at FROM hostel_allocations WHERE vendor_id = ?", (vendor_id,))
    allocations = {_row(row, ("person_id", "bed_id", "allocated_at"))["person_id"]: _row(row, ("person_id", "bed_id", "allocated_at")) for row in (c.fetchall() or [])}
    if scope is not None:
        residents = [resident for resident in residents if resident["id"] not in allocations or int(allocations[resident["id"]]["bed_id"]) in visible_bed_ids]
    for resident in residents:
        resident["allocation"] = allocations.get(resident["id"])
        if not access.get("can_view_resident_details"):
            resident.pop("phone", None); resident.pop("custom", None)

    c.execute("""SELECT h.id AS id, h.person_id AS person_id, f.name AS resident_name,
                        h.action AS action, h.previous_bed_id AS previous_bed_id, h.new_bed_id AS new_bed_id,
                        h.actor_username AS actor_username, h.reason AS reason,
                        h.override_reason AS override_reason, h.created_at AS created_at
                 FROM hostel_allocation_history h LEFT JOIN faces f ON f.id = h.person_id
                 WHERE h.vendor_id = ? ORDER BY h.id DESC LIMIT 100""", (vendor_id,))
    history_columns = ("id", "person_id", "resident_name", "action", "previous_bed_id", "new_bed_id", "actor_username", "reason", "override_reason", "created_at")
    history = [_row(row, history_columns) for row in (c.fetchall() or [])]
    if scope is not None:
        history = [item for item in history if any(bed_id is not None and int(bed_id) in visible_bed_ids for bed_id in (item.get("previous_bed_id"), item.get("new_bed_id")))]
    return {"buildings": buildings, "residents": residents, "history": history, "permissions": access, "summary": summarize_rooms([room for building in buildings for floor in building["floors"] for room in floor["rooms"]])}


def summarize_rooms(rooms):
    result = {"total": 0, "occupied": 0, "available": 0, "reserved": 0, "unavailable": 0}
    for room in rooms:
        for key in result:
            result[key] += int((room.get("summary") or {}).get(key, 0))
    return result


def create_building(conn, vendor_id, data):
    name = str(data.get("name") or "").strip()
    if not name:
        raise HostelAllocationError("Building name is required")
    c = conn.cursor(); c.execute("SELECT id FROM hostel_buildings WHERE vendor_id=? AND LOWER(name)=LOWER(?)", (vendor_id, name))
    if c.fetchone(): raise HostelAllocationError("A building with this name already exists", 409, "DUPLICATE_BUILDING")
    c.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM hostel_buildings WHERE vendor_id = ?", (vendor_id,)); order = c.fetchone()[0]
    c.execute("INSERT INTO hostel_buildings (vendor_id, name, code, sort_order, eligibility_rules) VALUES (?, ?, ?, ?, ?)", (vendor_id, name, str(data.get("code") or "").strip() or None, order, _dump(data.get("eligibility_rules"))))
    building_id = c.lastrowid; conn.commit(); return building_id


def create_floor(conn, vendor_id, building_id, data):
    name = str(data.get("name") or "").strip()
    if not name: raise HostelAllocationError("Floor name is required")
    c = conn.cursor(); c.execute("SELECT id FROM hostel_buildings WHERE id = ? AND vendor_id = ?", (building_id, vendor_id))
    if not c.fetchone(): raise HostelAllocationError("Building not found", 404, "NOT_FOUND")
    c.execute("SELECT id FROM hostel_floors WHERE building_id=? AND LOWER(name)=LOWER(?)", (building_id, name))
    if c.fetchone(): raise HostelAllocationError("A floor with this name already exists", 409, "DUPLICATE_FLOOR")
    c.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM hostel_floors WHERE building_id = ?", (building_id,)); order = c.fetchone()[0]
    c.execute("INSERT INTO hostel_floors (vendor_id, building_id, name, sort_order, eligibility_rules) VALUES (?, ?, ?, ?, ?)", (vendor_id, building_id, name, order, _dump(data.get("eligibility_rules"))))
    floor_id = c.lastrowid; conn.commit(); return floor_id


def create_rooms(conn, vendor_id, floor_id, data, access=None):
    count = max(1, min(int(data.get("count") or 1), 100))
    capacity = max(1, min(int(data.get("capacity") or 1), 20))
    start = int(data.get("start_number") or 1); prefix = str(data.get("prefix") or "").strip(); room_type = str(data.get("room_type") or "Standard").strip()
    c = conn.cursor(); c.execute("SELECT building_id FROM hostel_floors WHERE id = ? AND vendor_id = ?", (floor_id, vendor_id)); row = c.fetchone()
    if not row: raise HostelAllocationError("Floor not found", 404, "NOT_FOUND")
    if access is not None: require_permission(access, "can_edit_layout", row[0])
    c.execute("SELECT COALESCE(MAX(position_index), -1) + 1 FROM hostel_rooms WHERE floor_id = ?", (floor_id,)); position = c.fetchone()[0]
    ids = []
    for offset in range(count):
        room_number = f"{prefix}{start + offset}"
        c.execute("SELECT id FROM hostel_rooms WHERE floor_id=? AND room_number=?", (floor_id, room_number))
        if c.fetchone():
            conn.rollback()
            raise HostelAllocationError(f"Room {room_number} already exists on this floor", 409, "DUPLICATE_ROOM")
        c.execute("INSERT INTO hostel_rooms (vendor_id, floor_id, room_number, room_type, position_index, eligibility_rules) VALUES (?, ?, ?, ?, ?, ?)", (vendor_id, floor_id, room_number, room_type, position + offset, _dump(data.get("eligibility_rules"))))
        room_id = c.lastrowid; ids.append(room_id)
        for bed_index in range(capacity):
            c.execute("INSERT INTO hostel_beds (vendor_id, room_id, bed_label, position_index) VALUES (?, ?, ?, ?)", (vendor_id, room_id, f"Bed {bed_index + 1}", bed_index))
    conn.commit(); return ids


def duplicate_floor(conn, vendor_id, floor_id, name, access=None):
    c = conn.cursor(); c.execute("SELECT building_id, name, eligibility_rules FROM hostel_floors WHERE id = ? AND vendor_id = ?", (floor_id, vendor_id)); source = c.fetchone()
    if not source: raise HostelAllocationError("Floor not found", 404, "NOT_FOUND")
    source = _row(source, ("building_id", "name", "eligibility_rules"))
    if access is not None: require_permission(access, "can_edit_layout", source["building_id"])
    new_id = create_floor(conn, vendor_id, source["building_id"], {"name": name or f"Copy of {source['name']}", "eligibility_rules": _json(source["eligibility_rules"], {})})
    c = conn.cursor(); c.execute("SELECT id, room_number, room_type, position_index, eligibility_rules FROM hostel_rooms WHERE floor_id = ? ORDER BY position_index", (floor_id,))
    for room_row in c.fetchall() or []:
        room = _row(room_row, ("id", "room_number", "room_type", "position_index", "eligibility_rules"))
        c.execute("INSERT INTO hostel_rooms (vendor_id, floor_id, room_number, room_type, position_index, eligibility_rules) VALUES (?, ?, ?, ?, ?, ?)", (vendor_id, new_id, room["room_number"], room["room_type"], room["position_index"], room["eligibility_rules"]))
        new_room = c.lastrowid
        c.execute("SELECT bed_label, position_index, availability_status, unavailable_reason, unavailable_note, unavailable_from, expected_reopening_date FROM hostel_beds WHERE room_id = ? ORDER BY position_index", (room["id"],))
        for bed_row in c.fetchall() or []:
            bed = _row(bed_row, ("bed_label", "position_index", "availability_status", "unavailable_reason", "unavailable_note", "unavailable_from", "expected_reopening_date"))
            c.execute("INSERT INTO hostel_beds (vendor_id, room_id, bed_label, position_index, availability_status, unavailable_reason, unavailable_note, unavailable_from, expected_reopening_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (vendor_id, new_room, bed["bed_label"], bed["position_index"], bed["availability_status"], bed["unavailable_reason"], bed["unavailable_note"], bed["unavailable_from"], bed["expected_reopening_date"]))
    conn.commit(); return new_id


def _bed_context(c, vendor_id, bed_id, lock=False):
    suffix = " FOR UPDATE" if lock else ""
    c.execute("""SELECT b.id, b.room_id, b.availability_status, b.reservation_expires_at, b.reserved_for_person_id,
                        r.floor_id, r.eligibility_rules AS room_rules, f.building_id, f.eligibility_rules AS floor_rules,
                        g.eligibility_rules AS building_rules
                 FROM hostel_beds b JOIN hostel_rooms r ON r.id = b.room_id
                 JOIN hostel_floors f ON f.id = r.floor_id JOIN hostel_buildings g ON g.id = f.building_id
                 WHERE b.id = ? AND b.vendor_id = ?""" + suffix, (bed_id, vendor_id))
    return _row(c.fetchone(), ("id", "room_id", "availability_status", "reservation_expires_at", "reserved_for_person_id", "floor_id", "room_rules", "building_id", "floor_rules", "building_rules"))


def allocate(conn, vendor_id, person_id, bed_id, actor, access, reason=None, override=False, override_reason=None):
    require_permission(access, "can_allocate")
    c = conn.cursor(); pg = bool(getattr(conn, "_is_pg", False))
    try:
        if not pg: c.execute("BEGIN IMMEDIATE")
        bed = _bed_context(c, vendor_id, bed_id, lock=pg)
        if not bed: raise HostelAllocationError("Destination bed not found", 404, "NOT_FOUND")
        require_permission(access, "can_allocate", bed["building_id"])
        c.execute("SELECT a.person_id FROM hostel_allocations a WHERE a.bed_id = ?", (bed_id,))
        if c.fetchone(): raise HostelAllocationError("This bed was allocated by another administrator", 409, "BED_ALREADY_OCCUPIED")
        status = _effective_bed_status(bed, False)
        if status != "available": raise HostelAllocationError(f"This bed is {status} and cannot accept a resident", 409, "BED_NOT_AVAILABLE")
        c.execute("SELECT id, name, display_id, phone, department, custom_data FROM faces WHERE id = ? AND vendor_id = ?", (person_id, vendor_id)); person_row = c.fetchone()
        if not person_row: raise HostelAllocationError("Resident not found", 404, "NOT_FOUND")
        person = _person_profile(person_row); rules = _merge_rules(bed["building_rules"], bed["floor_rules"], bed["room_rules"]); eligibility = _eligibility_errors(person, rules)
        if eligibility:
            if not override: raise HostelAllocationError("; ".join(eligibility), 409, "ELIGIBILITY_FAILED")
            require_permission(access, "can_override_eligibility", bed["building_id"])
            if not str(override_reason or "").strip(): raise HostelAllocationError("An override reason is required")
        c.execute("SELECT id, bed_id FROM hostel_allocations WHERE vendor_id = ? AND person_id = ?" + (" FOR UPDATE" if pg else ""), (vendor_id, person_id)); current = c.fetchone()
        current = _row(current, ("id", "bed_id"))
        previous_bed = current["bed_id"] if current else None
        if previous_bed == bed_id: raise HostelAllocationError("Resident is already assigned to this bed", 409, "ALREADY_ASSIGNED")
        if current:
            previous_context = _bed_context(c, vendor_id, previous_bed, lock=pg)
            require_permission(access, "can_allocate", previous_context["building_id"])
            c.execute("DELETE FROM hostel_allocations WHERE id = ?", (current["id"],))
        c.execute("INSERT INTO hostel_allocations (vendor_id, person_id, bed_id, allocated_by) VALUES (?, ?, ?, ?)", (vendor_id, person_id, bed_id, actor))
        action = "transferred" if previous_bed else "assigned"
        c.execute("INSERT INTO hostel_allocation_history (vendor_id, person_id, action, previous_bed_id, new_bed_id, actor_username, reason, override_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (vendor_id, person_id, action, previous_bed, bed_id, actor, str(reason or "").strip() or None, str(override_reason or "").strip() or None))
        history_id = c.lastrowid; conn.commit(); return {"history_id": history_id, "action": action, "eligibility_overridden": bool(eligibility)}
    except Exception:
        conn.rollback(); raise


def remove_allocation(conn, vendor_id, person_id, actor, access, reason=None):
    require_permission(access, "can_allocate")
    c = conn.cursor(); c.execute("""SELECT a.id AS id, a.bed_id AS bed_id, g.id AS building_id
                                    FROM hostel_allocations a JOIN hostel_beds b ON b.id = a.bed_id
                                    JOIN hostel_rooms r ON r.id = b.room_id
                                    JOIN hostel_floors f ON f.id = r.floor_id
                                    JOIN hostel_buildings g ON g.id = f.building_id
                                    WHERE a.vendor_id = ? AND a.person_id = ?""", (vendor_id, person_id)); row = c.fetchone()
    if not row: raise HostelAllocationError("Resident is not currently allocated", 404, "NOT_FOUND")
    current = _row(row, ("id", "bed_id", "building_id")); require_permission(access, "can_allocate", current["building_id"])
    c.execute("DELETE FROM hostel_allocations WHERE id = ?", (current["id"],))
    c.execute("INSERT INTO hostel_allocation_history (vendor_id, person_id, action, previous_bed_id, actor_username, reason) VALUES (?, ?, 'removed', ?, ?, ?)", (vendor_id, person_id, current["bed_id"], actor, str(reason or "").strip() or None))
    history_id = c.lastrowid; conn.commit(); return history_id


def undo_allocation_change(conn, vendor_id, history_id, actor, access):
    """Reverse the latest allocation change if its prior state is still safe."""
    require_permission(access, "can_allocate")
    c = conn.cursor(); pg = bool(getattr(conn, "_is_pg", False))
    try:
        if not pg: c.execute("BEGIN IMMEDIATE")
        c.execute("""SELECT id, person_id, action, previous_bed_id, new_bed_id
                     FROM hostel_allocation_history WHERE id=? AND vendor_id=?""" +
                  (" FOR UPDATE" if pg else ""), (history_id, vendor_id))
        item = _row(c.fetchone(), ("id", "person_id", "action", "previous_bed_id", "new_bed_id"))
        if not item: raise HostelAllocationError("Allocation history entry not found", 404, "NOT_FOUND")
        if str(item["action"]).startswith("undo_"):
            raise HostelAllocationError("An undo action cannot be undone again", 409, "UNDO_NOT_AVAILABLE")
        c.execute("SELECT id FROM hostel_allocation_history WHERE vendor_id=? AND person_id=? ORDER BY id DESC LIMIT 1", (vendor_id, item["person_id"]))
        latest = c.fetchone()
        if not latest or int(latest[0]) != int(history_id):
            raise HostelAllocationError("Only the resident's most recent change can be undone", 409, "UNDO_NOT_LATEST")
        c.execute("SELECT id, bed_id FROM hostel_allocations WHERE vendor_id=? AND person_id=?" + (" FOR UPDATE" if pg else ""), (vendor_id, item["person_id"]))
        current = _row(c.fetchone(), ("id", "bed_id"))
        expected_current = item.get("new_bed_id")
        if expected_current is None:
            if current: raise HostelAllocationError("The resident has a newer active allocation", 409, "UNDO_STATE_CHANGED")
        elif not current or int(current["bed_id"]) != int(expected_current):
            raise HostelAllocationError("The resident's allocation has changed", 409, "UNDO_STATE_CHANGED")

        previous_bed = item.get("previous_bed_id")
        if previous_bed is not None:
            target = _bed_context(c, vendor_id, previous_bed, lock=pg)
            if not target: raise HostelAllocationError("The previous bed no longer exists", 409, "UNDO_TARGET_MISSING")
            require_permission(access, "can_allocate", target["building_id"])
            c.execute("SELECT person_id FROM hostel_allocations WHERE bed_id=?", (previous_bed,))
            occupant = c.fetchone()
            if occupant and int(occupant[0]) != int(item["person_id"]):
                raise HostelAllocationError("The previous bed is now occupied", 409, "UNDO_TARGET_OCCUPIED")
            if _effective_bed_status(target, bool(occupant)) not in {"available", "occupied"}:
                raise HostelAllocationError("The previous bed is no longer available", 409, "UNDO_TARGET_UNAVAILABLE")
        if current:
            current_context = _bed_context(c, vendor_id, current["bed_id"], lock=pg)
            require_permission(access, "can_allocate", current_context["building_id"])
            c.execute("DELETE FROM hostel_allocations WHERE id=?", (current["id"],))
        if previous_bed is not None:
            c.execute("INSERT INTO hostel_allocations (vendor_id,person_id,bed_id,allocated_by) VALUES (?,?,?,?)", (vendor_id, item["person_id"], previous_bed, actor))
        c.execute("""INSERT INTO hostel_allocation_history
                     (vendor_id,person_id,action,previous_bed_id,new_bed_id,actor_username,reason)
                     VALUES (?,?,?,?,?,?,?)""",
                  (vendor_id, item["person_id"], f"undo_{item['action']}", expected_current, previous_bed, actor, f"Undo history #{history_id}"))
        undo_id = c.lastrowid; conn.commit()
        return undo_id
    except Exception:
        conn.rollback(); raise


def update_bed(conn, vendor_id, bed_id, data, access):
    c = conn.cursor(); bed = _bed_context(c, vendor_id, bed_id)
    if not bed: raise HostelAllocationError("Bed not found", 404, "NOT_FOUND")
    require_permission(access, "can_edit_layout", bed["building_id"])
    if "bed_label" in data:
        label = str(data.get("bed_label") or "").strip()
        if not label: raise HostelAllocationError("Bed label is required")
        c.execute("SELECT id FROM hostel_beds WHERE room_id=? AND LOWER(bed_label)=LOWER(?) AND id<>?", (bed["room_id"], label, bed_id))
        if c.fetchone(): raise HostelAllocationError("A bed with this label already exists in the room", 409, "DUPLICATE_BED")
        c.execute("UPDATE hostel_beds SET bed_label=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND vendor_id=?", (label, bed_id, vendor_id))
    if "status" not in data:
        conn.commit()
        return
    c.execute("SELECT person_id FROM hostel_allocations WHERE bed_id = ?", (bed_id,)); occupied = c.fetchone()
    mode = str(data.get("status") or "").lower()
    if occupied and mode != "occupied": raise HostelAllocationError("Transfer or remove the resident before changing this bed", 409, "BED_OCCUPIED")
    if mode == "unavailable":
        reason = str(data.get("reason") or "").lower()
        note = str(data.get("note") or "").strip()
        if reason not in VALID_BED_REASONS: raise HostelAllocationError("Select a valid unavailability reason")
        if reason == "other" and not note: raise HostelAllocationError("A note is required for Other")
        c.execute("UPDATE hostel_beds SET availability_status='unavailable', unavailable_reason=?, unavailable_note=?, unavailable_from=?, expected_reopening_date=?, reservation_expires_at=NULL, reserved_for_person_id=NULL, reservation_note=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?", (reason, note or None, data.get("start_date") or None, data.get("expected_reopening_date") or None, bed_id))
    elif mode == "reserved":
        if occupied: raise HostelAllocationError("An occupied bed cannot be reserved", 409)
        if str(bed.get("availability_status") or "available") == "unavailable":
            raise HostelAllocationError("Clear the active unavailability restriction before reserving this bed", 409, "BED_UNAVAILABLE")
        expiry = data.get("reservation_expires_at")
        if not expiry: raise HostelAllocationError("Reservation expiry is required")
        try:
            parsed_expiry = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
            if parsed_expiry.tzinfo is None: parsed_expiry = parsed_expiry.replace(tzinfo=timezone.utc)
            if parsed_expiry <= datetime.now(timezone.utc): raise ValueError
        except (TypeError, ValueError):
            raise HostelAllocationError("Reservation expiry must be a valid future date and time")
        intended = data.get("reserved_for_person_id") or None
        if intended:
            c.execute("SELECT id FROM faces WHERE id=? AND vendor_id=?", (intended, vendor_id))
            if not c.fetchone(): raise HostelAllocationError("Intended resident was not found", 404, "NOT_FOUND")
        c.execute("UPDATE hostel_beds SET reservation_expires_at=?, reserved_for_person_id=?, reservation_note=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (expiry, intended, str(data.get("note") or "").strip() or None, bed_id))
    elif mode == "available":
        c.execute("UPDATE hostel_beds SET availability_status='available', unavailable_reason=NULL, unavailable_note=NULL, unavailable_from=NULL, expected_reopening_date=NULL, reservation_expires_at=NULL, reserved_for_person_id=NULL, reservation_note=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?", (bed_id,))
    else: raise HostelAllocationError("Unsupported bed status")
    conn.commit()


def add_bed(conn, vendor_id, room_id, data, access):
    label = str(data.get("bed_label") or "").strip()
    if not label: raise HostelAllocationError("Bed label is required")
    c = conn.cursor()
    c.execute("""SELECT f.building_id FROM hostel_rooms r JOIN hostel_floors f ON f.id=r.floor_id
                 WHERE r.id=? AND r.vendor_id=?""", (room_id, vendor_id))
    room = c.fetchone()
    if not room: raise HostelAllocationError("Room not found", 404, "NOT_FOUND")
    require_permission(access, "can_edit_layout", room[0])
    c.execute("SELECT COUNT(*), COALESCE(MAX(position_index), -1) FROM hostel_beds WHERE room_id=? AND vendor_id=?", (room_id, vendor_id))
    count, max_position = c.fetchone()
    if int(count) >= 20: raise HostelAllocationError("A room cannot contain more than 20 beds", 409, "BED_LIMIT_REACHED")
    c.execute("SELECT id FROM hostel_beds WHERE room_id=? AND LOWER(bed_label)=LOWER(?)", (room_id, label))
    if c.fetchone(): raise HostelAllocationError("A bed with this label already exists in the room", 409, "DUPLICATE_BED")
    c.execute("INSERT INTO hostel_beds (vendor_id,room_id,bed_label,position_index) VALUES (?,?,?,?)", (vendor_id, room_id, label, int(max_position) + 1))
    bed_id = c.lastrowid; conn.commit(); return bed_id


def delete_bed(conn, vendor_id, bed_id, access):
    c = conn.cursor(); bed = _bed_context(c, vendor_id, bed_id)
    if not bed: raise HostelAllocationError("Bed not found", 404, "NOT_FOUND")
    require_permission(access, "can_edit_layout", bed["building_id"])
    c.execute("SELECT 1 FROM hostel_allocations WHERE bed_id=?", (bed_id,))
    if c.fetchone(): raise HostelAllocationError("Remove the resident before deleting this bed", 409, "BED_OCCUPIED")
    if _effective_bed_status(bed, False) != "available":
        raise HostelAllocationError("Clear the reservation or unavailability restriction before deleting this bed", 409, "BED_NOT_AVAILABLE")
    c.execute("DELETE FROM hostel_beds WHERE id=? AND vendor_id=?", (bed_id, vendor_id)); conn.commit()


def reorder_rooms(conn, vendor_id, floor_id, room_ids, access):
    c = conn.cursor(); c.execute("SELECT building_id FROM hostel_floors WHERE id=? AND vendor_id=?", (floor_id, vendor_id)); row = c.fetchone()
    if not row: raise HostelAllocationError("Floor not found", 404)
    building_id = row[0]; require_permission(access, "can_edit_layout", building_id)
    c.execute("SELECT id FROM hostel_rooms WHERE floor_id=? AND vendor_id=?", (floor_id, vendor_id)); valid = {int(row[0]) for row in (c.fetchall() or [])}
    if set(map(int, room_ids)) != valid: raise HostelAllocationError("Room order must include every room on the floor")
    for index, room_id in enumerate(room_ids): c.execute("UPDATE hostel_rooms SET position_index=? WHERE id=? AND vendor_id=?", (index, int(room_id), vendor_id))
    conn.commit()


def update_room(conn, vendor_id, room_id, data, access):
    c = conn.cursor(); c.execute("SELECT r.floor_id, f.building_id FROM hostel_rooms r JOIN hostel_floors f ON f.id=r.floor_id WHERE r.id=? AND r.vendor_id=?", (room_id, vendor_id)); row = c.fetchone()
    if not row: raise HostelAllocationError("Room not found", 404)
    building_id = row[1]; require_permission(access, "can_edit_layout", building_id)
    fields = []; params = []
    for key in ("room_number", "room_type"):
        if key in data and str(data[key]).strip(): fields.append(f"{key}=?"); params.append(str(data[key]).strip())
    if "eligibility_rules" in data:
        require_permission(access, "can_manage_eligibility", building_id)
        fields.append("eligibility_rules=?"); params.append(_dump(data["eligibility_rules"]))
    if fields: params.extend([room_id, vendor_id]); c.execute(f"UPDATE hostel_rooms SET {', '.join(fields)} WHERE id=? AND vendor_id=?", params)
    if "capacity" in data:
        capacity = max(1, min(int(data["capacity"]), 20)); c.execute("SELECT id FROM hostel_beds WHERE room_id=? ORDER BY position_index,id", (room_id,)); beds = [r[0] for r in c.fetchall() or []]
        c.execute("SELECT COUNT(*) FROM hostel_allocations a JOIN hostel_beds b ON b.id=a.bed_id WHERE b.room_id=?", (room_id,)); occupied = int(c.fetchone()[0])
        if capacity < occupied: raise HostelAllocationError("Capacity cannot be lower than current occupancy", 409)
        if capacity > len(beds):
            for index in range(len(beds), capacity): c.execute("INSERT INTO hostel_beds (vendor_id,room_id,bed_label,position_index) VALUES (?,?,?,?)", (vendor_id, room_id, f"Bed {index+1}", index))
        elif capacity < len(beds):
            for bed_id in reversed(beds[capacity:]):
                c.execute("SELECT 1 FROM hostel_allocations WHERE bed_id=?", (bed_id,)); allocation = c.fetchone(); c.execute("SELECT reservation_expires_at, availability_status FROM hostel_beds WHERE id=?", (bed_id,)); meta = c.fetchone()
                if allocation or (meta and (meta[0] or meta[1] == "unavailable")): raise HostelAllocationError("Only available, unoccupied beds can be removed", 409)
                c.execute("DELETE FROM hostel_beds WHERE id=?", (bed_id,))
    conn.commit()


def delete_room(conn, vendor_id, room_id, access):
    c = conn.cursor(); c.execute("SELECT f.building_id FROM hostel_rooms r JOIN hostel_floors f ON f.id=r.floor_id WHERE r.id=? AND r.vendor_id=?", (room_id, vendor_id)); row=c.fetchone()
    if not row: raise HostelAllocationError("Room not found",404)
    require_permission(access,"can_edit_layout",row[0]); c.execute("SELECT COUNT(*) FROM hostel_allocations a JOIN hostel_beds b ON b.id=a.bed_id WHERE b.room_id=?",(room_id,))
    if int(c.fetchone()[0]): raise HostelAllocationError("Occupied rooms cannot be deleted",409)
    c.execute("DELETE FROM hostel_beds WHERE room_id=? AND vendor_id=?",(room_id,vendor_id))
    c.execute("DELETE FROM hostel_rooms WHERE id=? AND vendor_id=?",(room_id,vendor_id)); conn.commit()


def update_building(conn, vendor_id, building_id, data, access):
    require_permission(access, "can_manage_buildings", building_id)
    c = conn.cursor(); c.execute("SELECT id FROM hostel_buildings WHERE id=? AND vendor_id=?", (building_id, vendor_id))
    if not c.fetchone(): raise HostelAllocationError("Building not found", 404, "NOT_FOUND")
    fields = []; params = []
    for key in ("name", "code"):
        if key in data and str(data.get(key) or "").strip(): fields.append(f"{key}=?"); params.append(str(data[key]).strip())
    if "eligibility_rules" in data:
        require_permission(access, "can_manage_eligibility", building_id)
        fields.append("eligibility_rules=?"); params.append(_dump(data["eligibility_rules"]))
    if fields:
        params.extend([building_id, vendor_id]); c.execute(f"UPDATE hostel_buildings SET {', '.join(fields)} WHERE id=? AND vendor_id=?", params)
    conn.commit()


def update_floor(conn, vendor_id, floor_id, data, access):
    c = conn.cursor(); c.execute("SELECT building_id FROM hostel_floors WHERE id=? AND vendor_id=?", (floor_id, vendor_id)); row = c.fetchone()
    if not row: raise HostelAllocationError("Floor not found", 404, "NOT_FOUND")
    require_permission(access, "can_edit_layout", row[0])
    fields = []; params = []
    if "name" in data and str(data.get("name") or "").strip(): fields.append("name=?"); params.append(str(data["name"]).strip())
    if "eligibility_rules" in data:
        require_permission(access, "can_manage_eligibility", row[0])
        fields.append("eligibility_rules=?"); params.append(_dump(data["eligibility_rules"]))
    if fields:
        params.extend([floor_id, vendor_id]); c.execute(f"UPDATE hostel_floors SET {', '.join(fields)} WHERE id=? AND vendor_id=?", params)
    conn.commit()


def delete_floor(conn, vendor_id, floor_id, access):
    c = conn.cursor(); c.execute("SELECT building_id FROM hostel_floors WHERE id=? AND vendor_id=?", (floor_id, vendor_id)); row = c.fetchone()
    if not row: raise HostelAllocationError("Floor not found", 404, "NOT_FOUND")
    require_permission(access, "can_edit_layout", row[0])
    c.execute("""SELECT COUNT(*) FROM hostel_allocations a JOIN hostel_beds b ON b.id=a.bed_id
                 JOIN hostel_rooms r ON r.id=b.room_id WHERE r.floor_id=?""", (floor_id,))
    if int(c.fetchone()[0]): raise HostelAllocationError("A floor with occupied rooms cannot be deleted", 409)
    c.execute("DELETE FROM hostel_beds WHERE room_id IN (SELECT id FROM hostel_rooms WHERE floor_id=?)", (floor_id,))
    c.execute("DELETE FROM hostel_rooms WHERE floor_id=? AND vendor_id=?", (floor_id, vendor_id))
    c.execute("DELETE FROM hostel_floors WHERE id=? AND vendor_id=?", (floor_id, vendor_id)); conn.commit()


def delete_building(conn, vendor_id, building_id, access):
    require_permission(access, "can_manage_buildings", building_id)
    c = conn.cursor(); c.execute("SELECT id FROM hostel_buildings WHERE id=? AND vendor_id=?", (building_id, vendor_id))
    if not c.fetchone(): raise HostelAllocationError("Building not found", 404, "NOT_FOUND")
    c.execute("""SELECT COUNT(*) FROM hostel_allocations a JOIN hostel_beds b ON b.id=a.bed_id
                 JOIN hostel_rooms r ON r.id=b.room_id JOIN hostel_floors f ON f.id=r.floor_id
                 WHERE f.building_id=?""", (building_id,))
    if int(c.fetchone()[0]): raise HostelAllocationError("A building with allocated residents cannot be deleted", 409)
    c.execute("DELETE FROM hostel_beds WHERE room_id IN (SELECT r.id FROM hostel_rooms r JOIN hostel_floors f ON f.id=r.floor_id WHERE f.building_id=?)", (building_id,))
    c.execute("DELETE FROM hostel_rooms WHERE floor_id IN (SELECT id FROM hostel_floors WHERE building_id=?)", (building_id,))
    c.execute("DELETE FROM hostel_floors WHERE building_id=? AND vendor_id=?", (building_id, vendor_id))
    c.execute("DELETE FROM hostel_staff_permissions WHERE building_id=? AND vendor_id=?", (building_id, vendor_id))
    c.execute("DELETE FROM hostel_buildings WHERE id=? AND vendor_id=?", (building_id, vendor_id)); conn.commit()
