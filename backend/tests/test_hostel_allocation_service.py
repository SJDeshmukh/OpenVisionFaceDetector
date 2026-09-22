import sqlite3

import pytest

from services.hostel_allocation_service import (
    HostelAllocationError,
    add_bed,
    allocate,
    create_building,
    create_floor,
    create_rooms,
    delete_bed,
    ensure_tables,
    get_state,
    undo_allocation_change,
    update_bed,
    update_room,
)


ADMIN = {
    "role": "administrator",
    "building_ids": None,
    "can_edit_layout": True,
    "can_allocate": True,
    "can_manage_permissions": True,
    "can_manage_buildings": True,
    "can_manage_eligibility": True,
    "can_export": True,
    "can_override_eligibility": True,
    "can_view_resident_details": True,
}


@pytest.fixture()
def hostel():
    conn = sqlite3.connect(":memory:")
    # Named rows reproduce PostgreSQL DictCursor behavior, including the risk
    # of duplicate column names in joined queries.
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE faces (
        id INTEGER PRIMARY KEY, vendor_id INTEGER NOT NULL, name TEXT,
        display_id TEXT, phone TEXT, department TEXT, custom_data TEXT
    )""")
    conn.executemany(
        "INSERT INTO faces VALUES (?,?,?,?,?,?,?)",
        [
            (1, 10, "Ananya Patil", "STU-1", "1", "Science", '{"gender":"female","academic_year":"1"}'),
            (2, 10, "Rohan Shah", "STU-2", "2", "Science", '{"gender":"male","academic_year":"2"}'),
        ],
    )
    ensure_tables(conn)
    building_id = create_building(conn, 10, {"name": "Building A", "eligibility_rules": {"gender": ["female"]}})
    floor_id = create_floor(conn, 10, building_id, {"name": "Ground Floor"})
    room_id = create_rooms(conn, 10, floor_id, {"count": 1, "start_number": 101, "capacity": 2}, ADMIN)[0]
    state = get_state(conn, 10, ADMIN)
    beds = state["buildings"][0]["floors"][0]["rooms"][0]["beds"]
    yield conn, building_id, floor_id, room_id, [bed["id"] for bed in beds]
    conn.close()


def test_assign_transfer_and_undo_are_transactional(hostel):
    conn, _building, _floor, _room, beds = hostel
    assigned = allocate(conn, 10, 1, beds[0], "admin@example.com", ADMIN)
    transferred = allocate(conn, 10, 1, beds[1], "admin@example.com", ADMIN, "Quieter bed")

    undo_allocation_change(conn, 10, transferred["history_id"], "admin@example.com", ADMIN)
    active_bed = conn.execute("SELECT bed_id FROM hostel_allocations WHERE person_id=1").fetchone()[0]
    assert active_bed == beds[0]
    assert assigned["action"] == "assigned"


def test_eligibility_and_capacity_safeguards(hostel):
    conn, _building, _floor, room, beds = hostel
    with pytest.raises(HostelAllocationError, match="gender"):
        allocate(conn, 10, 2, beds[0], "admin@example.com", ADMIN)
    with pytest.raises(HostelAllocationError, match="override reason"):
        allocate(conn, 10, 2, beds[0], "admin@example.com", ADMIN, override=True)
    allocate(conn, 10, 2, beds[0], "admin@example.com", ADMIN, override=True, override_reason="Approved exception")
    allocate(conn, 10, 1, beds[1], "admin@example.com", ADMIN)
    with pytest.raises(HostelAllocationError, match="lower than current occupancy"):
        update_room(conn, 10, room, {"capacity": 1}, ADMIN)


def test_unavailability_cannot_be_silently_replaced_by_reservation(hostel):
    conn, _building, _floor, _room, beds = hostel
    update_bed(conn, 10, beds[0], {"status": "unavailable", "reason": "maintenance"}, ADMIN)
    with pytest.raises(HostelAllocationError, match="Clear the active unavailability"):
        update_bed(conn, 10, beds[0], {"status": "reserved", "reservation_expires_at": "2099-01-01T00:00:00Z"}, ADMIN)
    state = get_state(conn, 10, ADMIN)
    bed = state["buildings"][0]["floors"][0]["rooms"][0]["beds"][0]
    assert bed["status"] == "unavailable"
    assert state["summary"]["total"] == state["summary"]["occupied"] + state["summary"]["available"] + state["summary"]["reserved"] + state["summary"]["unavailable"]


def test_custom_beds_can_be_added_renamed_and_safely_deleted(hostel):
    conn, _building, _floor, room, beds = hostel
    custom_bed = add_bed(conn, 10, room, {"bed_label": "Window Bed"}, ADMIN)
    update_bed(conn, 10, custom_bed, {"bed_label": "Balcony Bed"}, ADMIN)
    allocate(conn, 10, 1, custom_bed, "admin@example.com", ADMIN)
    with pytest.raises(HostelAllocationError, match="Remove the resident"):
        delete_bed(conn, 10, custom_bed, ADMIN)
    conn.execute("DELETE FROM hostel_allocations WHERE bed_id=?", (custom_bed,))
    conn.commit()
    delete_bed(conn, 10, custom_bed, ADMIN)
    labels = [row[0] for row in conn.execute("SELECT bed_label FROM hostel_beds WHERE room_id=? ORDER BY position_index", (room,)).fetchall()]
    assert labels == ["Bed 1", "Bed 2"]


def test_state_loading_uses_fixed_bulk_queries(hostel):
    conn, _building, floor, _room, _beds = hostel
    create_rooms(conn, 10, floor, {"count": 12, "start_number": 201, "capacity": 3}, ADMIN)
    statements = []
    conn.set_trace_callback(statements.append)

    state = get_state(conn, 10, ADMIN)

    selects = [statement for statement in statements if statement.lstrip().upper().startswith("SELECT")]
    assert len(state["buildings"][0]["floors"][0]["rooms"]) == 13
    assert len(selects) == 7
