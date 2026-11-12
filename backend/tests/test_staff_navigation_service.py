import json

import pytest

from services.staff_navigation_service import (
    DEFAULT_STAFF_NAV_ITEMS,
    load_staff_nav_items,
    normalize_staff_nav_items,
    serialize_staff_nav_items,
    staff_can_access,
)


def test_legacy_staff_receives_safe_navigation_default():
    assert normalize_staff_nav_items(None) == list(DEFAULT_STAFF_NAV_ITEMS)
    assert staff_can_access(None, "leave_management") is True
    assert staff_can_access(None, "hostel_allocation") is False


def test_navigation_is_canonical_and_leave_management_is_required():
    result = normalize_staff_nav_items(["reports", "dashboard", "reports"])
    assert result == ["dashboard", "reports", "leave_management"]
    assert json.loads(serialize_staff_nav_items(result)) == result


def test_unknown_navigation_item_is_rejected():
    with pytest.raises(ValueError, match="Unknown navigation item"):
        normalize_staff_nav_items(["dashboard", "vendor_database"])


def test_corrupt_persisted_navigation_fails_closed_to_default():
    assert load_staff_nav_items("not-json") == list(DEFAULT_STAFF_NAV_ITEMS)
    assert staff_can_access("not-json", "hostel_allocation") is False
