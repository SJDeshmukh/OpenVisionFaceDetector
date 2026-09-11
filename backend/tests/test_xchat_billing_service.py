import sqlite3
import sys
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services import xchat_billing_service as billing


@pytest.fixture()
def billing_db(tmp_path):
    path = tmp_path / "billing.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE subscriptions (
            vendor_id INTEGER PRIMARY KEY,
            xchat_billing_mode TEXT DEFAULT 'payg',
            xchat_token_limit INTEGER DEFAULT 0,
            xchat_tokens_used INTEGER DEFAULT 0,
            xchat_input_tokens INTEGER DEFAULT 0,
            xchat_output_tokens INTEGER DEFAULT 0,
            xchat_tokens_billed INTEGER DEFAULT 0,
            xchat_price_per_1k_tokens REAL DEFAULT 0
        );
        CREATE TABLE xchat_token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            conversation_id TEXT,
            model TEXT,
            usage_type TEXT DEFAULT 'chat',
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.executemany(
        "INSERT INTO subscriptions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(1, "fixed", 1000, 900, 700, 200, 800, 2.5), (2, "payg", 0, 5000, 4000, 1000, 4500, 1.0)],
    )
    conn.commit()
    conn.close()
    return path, lambda: sqlite3.connect(path)


def test_fixed_credit_status_and_exhaustion(billing_db):
    path, factory = billing_db
    status = billing.require_available_credit(1, factory)
    assert status["remaining_tokens"] == 100
    assert status["blocked"] is False

    conn = sqlite3.connect(path)
    conn.execute("UPDATE subscriptions SET xchat_tokens_used = 1000 WHERE vendor_id = 1")
    conn.commit()
    conn.close()

    with pytest.raises(billing.XChatQuotaExceeded, match="exhausted"):
        billing.require_available_credit(1, factory)


def test_payg_tracks_usage_without_blocking(billing_db):
    _, factory = billing_db
    before = billing.require_available_credit(2, factory)
    assert before["remaining_tokens"] is None
    assert before["blocked"] is False

    after = billing.record_usage(
        2, "vendor-admin", "conversation-1", "nvidia.nemotron-nano-3-30b",
        {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}, factory,
    )

    assert after["tokens_used"] == 5150
    assert after["input_tokens"] == 4120
    assert after["output_tokens"] == 1030
    assert after["remaining_tokens"] is None

    conn = factory()
    row = conn.execute(
        "SELECT username, model, usage_type, input_tokens, output_tokens, total_tokens FROM xchat_token_usage"
    ).fetchone()
    conn.close()
    assert row == ("vendor-admin", "nvidia.nemotron-nano-3-30b", "chat", 120, 30, 150)


def test_nonbillable_mapping_usage_is_ledgered_without_consuming_chat_credits(billing_db):
    _, factory = billing_db
    before = billing.get_credit_status(1, factory)
    after = billing.record_usage(
        1, "vendor-admin", "spreadsheet:1", "nvidia.nemotron-nano-3-30b",
        {"input_tokens": 40, "output_tokens": 10, "total_tokens": 50}, factory,
        usage_type="spreadsheet_mapping", billable=False,
    )
    assert after["tokens_used"] == before["tokens_used"] == 900
    conn = factory()
    assert conn.execute("SELECT usage_type, total_tokens FROM xchat_token_usage").fetchone() == (
        "spreadsheet_mapping", 50,
    )
    conn.close()


def test_unbilled_token_charge_is_calculated_once_per_watermark():
    result = billing.calculate_token_charge(12345, 10000, 2.75)
    assert result == {
        "tokens_used": 12345,
        "tokens_billed": 10000,
        "unbilled_tokens": 2345,
        "price_per_1k_tokens": 2.75,
        "unbilled_charge": 6.45,
        "usage_value": 33.95,
    }


def test_usage_falls_back_to_input_plus_output_total():
    assert billing.normalize_usage({"input_tokens": 25, "output_tokens": 5}) == {
        "input_tokens": 25, "output_tokens": 5, "total_tokens": 30,
    }


@pytest.mark.parametrize(("value", "expected"), [
    ("fixed", "fixed"), ("credits", "fixed"), ("pay-as-you-go", "payg"), (None, "payg"),
])
def test_billing_mode_normalization(value, expected):
    assert billing.normalize_billing_mode(value) == expected


def test_invalid_billing_mode_is_rejected():
    with pytest.raises(ValueError):
        billing.normalize_billing_mode("unlimited-free")
