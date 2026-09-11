"""Vendor-scoped XChat token metering and credit enforcement."""

import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


logger = logging.getLogger(__name__)
VALID_BILLING_MODES = {"fixed", "payg"}


class XChatQuotaExceeded(RuntimeError):
    pass


def _db():
    from db_factory import get_db_connection
    return get_db_connection()


def _as_non_negative_int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def normalize_billing_mode(value):
    normalized = str(value or "payg").strip().lower().replace("-", "_")
    if normalized in {"pay_as_you_go", "payasyougo"}:
        normalized = "payg"
    if normalized in {"limited", "credit", "credits", "token_limit"}:
        normalized = "fixed"
    if normalized not in VALID_BILLING_MODES:
        raise ValueError("xchat_billing_mode must be fixed or payg")
    return normalized


def _status(mode, limit, used, input_tokens=0, output_tokens=0):
    mode = normalize_billing_mode(mode)
    limit = _as_non_negative_int(limit)
    used = _as_non_negative_int(used)
    remaining = max(0, limit - used) if mode == "fixed" else None
    return {
        "billing_mode": mode,
        "token_limit": limit,
        "tokens_used": used,
        "input_tokens": _as_non_negative_int(input_tokens),
        "output_tokens": _as_non_negative_int(output_tokens),
        "remaining_tokens": remaining,
        "blocked": mode == "fixed" and remaining <= 0,
    }


def calculate_token_charge(tokens_used, tokens_billed, price_per_1k_tokens):
    used = _as_non_negative_int(tokens_used)
    billed = min(used, _as_non_negative_int(tokens_billed))
    unbilled = max(0, used - billed)
    try:
        rate = Decimal(str(price_per_1k_tokens or 0))
        if not rate.is_finite() or rate < 0:
            rate = Decimal("0")
    except (InvalidOperation, TypeError, ValueError):
        rate = Decimal("0")
    charge = (Decimal(unbilled) * rate / Decimal(1000)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    lifetime_value = (Decimal(used) * rate / Decimal(1000)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "tokens_used": used,
        "tokens_billed": billed,
        "unbilled_tokens": unbilled,
        "price_per_1k_tokens": float(rate),
        "unbilled_charge": float(charge),
        "usage_value": float(lifetime_value),
    }


def get_credit_status(vendor_id, connection_factory=None):
    conn = (connection_factory or _db)()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT xchat_billing_mode, xchat_token_limit, xchat_tokens_used,
                       xchat_input_tokens, xchat_output_tokens,
                       xchat_tokens_billed, xchat_price_per_1k_tokens
                FROM subscriptions WHERE vendor_id = ? LIMIT 1
            """, (vendor_id,))
            row = cursor.fetchone()
        except Exception as exc:
            # During a rolling deployment, an old schema remains usable as PAYG
            # until the startup migration adds the metering columns.
            error_text = str(exc).lower()
            missing_metering_column = "xchat_" in error_text and any(
                marker in error_text
                for marker in ("no such column", "does not exist", "unknown column", "undefined column")
            )
            try:
                conn.rollback()
            except Exception:
                pass
            if not missing_metering_column:
                raise
            logger.warning("XChat metering columns are unavailable for vendor %s", vendor_id)
            return _status("payg", 0, 0)
        if not row:
            return _status("fixed", 0, 0)
        status = _status(row[0], row[1], row[2], row[3], row[4])
        status.update(calculate_token_charge(row[2], row[5], row[6]))
        return status
    finally:
        conn.close()


def require_available_credit(vendor_id, connection_factory=None):
    status = get_credit_status(vendor_id, connection_factory)
    if status["blocked"]:
        raise XChatQuotaExceeded("XChat token credits are exhausted. Please contact your administrator.")
    return status


def normalize_usage(usage):
    usage = usage if isinstance(usage, dict) else {}
    input_tokens = _as_non_negative_int(usage.get("input_tokens", usage.get("prompt_tokens")))
    output_tokens = _as_non_negative_int(usage.get("output_tokens", usage.get("completion_tokens")))
    total_tokens = _as_non_negative_int(usage.get("total_tokens"))
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def record_usage(
    vendor_id, username, conversation_id, model, usage, connection_factory=None,
    usage_type="chat", billable=True,
):
    normalized = normalize_usage(usage)
    if normalized["total_tokens"] <= 0:
        return get_credit_status(vendor_id, connection_factory)
    conn = (connection_factory or _db)()
    try:
        cursor = conn.cursor()
        clean_usage_type = str(usage_type or "chat").strip().lower()[:40]
        if clean_usage_type not in {"chat", "spreadsheet_mapping"}:
            clean_usage_type = "other"
        cursor.execute("""
            INSERT INTO xchat_token_usage (
                vendor_id, username, conversation_id, model, usage_type,
                input_tokens, output_tokens, total_tokens
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            vendor_id, str(username or "")[:255], conversation_id, str(model or "unknown")[:255],
            clean_usage_type, normalized["input_tokens"], normalized["output_tokens"], normalized["total_tokens"],
        ))
        if billable:
            cursor.execute("""
                UPDATE subscriptions
                SET xchat_tokens_used = COALESCE(xchat_tokens_used, 0) + ?,
                    xchat_input_tokens = COALESCE(xchat_input_tokens, 0) + ?,
                    xchat_output_tokens = COALESCE(xchat_output_tokens, 0) + ?
                WHERE vendor_id = ?
            """, (
                normalized["total_tokens"], normalized["input_tokens"],
                normalized["output_tokens"], vendor_id,
            ))
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Unable to persist XChat token usage for vendor %s", vendor_id)
        raise
    finally:
        conn.close()
    return get_credit_status(vendor_id, connection_factory)
