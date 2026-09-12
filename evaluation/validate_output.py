"""Independent validation helpers for the strict eight-column output."""

from __future__ import annotations

import csv
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

OUTPUT_HEADERS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]

ALLOWED_STATUSES = {
    "affordable",
    "affordable_with_delay",
    "affordable_with_spending_changes",
    "affordable_with_delay_and_spending_changes",
    "partially_affordable",
    "not_affordable",
}
ALLOWED_METHODS = {
    "full_payment",
    "partial_payment",
    "installments",
    "wait",
    "not_recommended",
}

FULL_RE = re.compile(
    r"^Full payment of (\d+\.\d{2}) ([A-Z]{3}) on (\d{4}-\d{2}-\d{2}) \(Option: ([^)]+)\)$"
)
INSTALLMENT_RE = re.compile(
    r"^(\d+) installments of (\d+\.\d{2}) ([A-Z]{3}) starting (\d{4}-\d{2}-\d{2}) \(Total: (\d+\.\d{2}) [A-Z]{3}, Option: ([^)]+)\)$"
)
PARTIAL_RE = re.compile(
    r"^2 payments: (\d+\.\d{2}) ([A-Z]{3}) on (\d{4}-\d{2}-\d{2}), (\d+\.\d{2}) [A-Z]{3} on (\d{4}-\d{2}-\d{2}) \(Total: (\d+\.\d{2}) [A-Z]{3}, Option: ([^)]+)\)$"
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SPENDING_RE = re.compile(r"^reduce_flexible_expenses_by_(\d+)%$")


def read_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames or [], list(reader)


def decimal(value: str) -> Optional[Decimal]:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _date_is_valid(value: str) -> bool:
    if not DATE_RE.match(value):
        return False
    try:
        from datetime import date

        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def validate_plan(row: Mapping[str, str], request: Optional[Mapping[str, str]] = None) -> List[str]:
    """Return precise plan errors for one serialized output row."""
    errors: List[str] = []
    method = row.get("recommended_payment_method", "")
    plan = row.get("payment_plan", "")
    requested_amount = decimal((request or {}).get("amount", ""))
    request_date = (request or {}).get("request_date", "")
    completion_date = (request or {}).get("desired_completion_date", "")

    if method == "not_recommended":
        if plan != "NONE":
            errors.append("not_recommended plan must be NONE")
        return errors

    match = FULL_RE.match(plan) if method in {"full_payment", "wait"} else None
    if method == "partial_payment":
        match = PARTIAL_RE.match(plan)
    elif method == "installments":
        match = INSTALLMENT_RE.match(plan)
    elif method not in {"full_payment", "wait"}:
        errors.append("unknown payment method")

    if not match:
        errors.append("payment_plan syntax is invalid for method")
        return errors

    groups = match.groups()
    if method == "partial_payment":
        first, _, first_date, second, second_date, total, _ = groups
        amounts = [Decimal(first), Decimal(second)]
        dates = [first_date, second_date]
        if len(amounts) != 2:
            errors.append("partial payment must contain exactly two payments")
        if requested_amount is not None and sum(amounts) != requested_amount:
            errors.append("partial payments do not sum to requested amount")
        if Decimal(total) != sum(amounts):
            errors.append("partial payment total is incorrect")
    elif method == "installments":
        count, amount, _, start_date, total, _ = groups
        count_value = int(count)
        installment_amount = Decimal(amount)
        total_value = Decimal(total)
        if count_value < 2:
            errors.append("installment count must be at least two")
        if installment_amount <= 0 or total_value <= 0:
            errors.append("installment amounts must be positive")
        if (installment_amount * count_value).quantize(Decimal("0.01")) != total_value:
            errors.append("installment total is incorrect")
        dates = [start_date]
        amounts = [installment_amount]
    else:
        amount, _, due_date, _ = groups
        dates = [due_date]
        amounts = [Decimal(amount)]
        if Decimal(amount) <= 0:
            errors.append("payment amount must be positive")

    if any(not _date_is_valid(value) for value in dates):
        errors.append("payment date is invalid")
    if request_date and dates[0] < request_date:
        errors.append("payment date precedes request date")
    if completion_date and max(dates) > completion_date:
        errors.append("payment completion date exceeds requested completion date")
    if any(amount <= 0 for amount in amounts):
        errors.append("payment amount must be positive")
    return errors


def validate_rows(
    headers: List[str],
    rows: Iterable[Mapping[str, str]],
    requests: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> Dict[str, object]:
    rows = list(rows)
    request_map = requests or {}
    ids = [row.get("request_id", "") for row in rows]
    duplicates = sorted(key for key, count in Counter(ids).items() if key and count > 1)
    missing_ids = sorted(key for key in request_map if key not in set(ids))
    unexpected_ids = sorted(key for key in set(ids) if key and key not in request_map)
    blank_ids = [str(index + 2) for index, key in enumerate(ids) if not key]
    invalid_statuses = [row.get("request_id", "") for row in rows if row.get("affordability_status") not in ALLOWED_STATUSES]
    invalid_methods = [row.get("request_id", "") for row in rows if row.get("recommended_payment_method") not in ALLOWED_METHODS]
    malformed_plans = []
    arithmetic_errors = []
    amount_errors = []
    earliest_errors = []
    spending_errors = []
    explanation_errors = []

    for row in rows:
        request = request_map.get(row.get("request_id", ""))
        plan_errors = validate_plan(row, request)
        if plan_errors:
            malformed_plans.append({"request_id": row.get("request_id", ""), "errors": plan_errors})
            if any("total" in error or "sum" in error for error in plan_errors):
                arithmetic_errors.append(row.get("request_id", ""))

        amount = decimal(row.get("amount_safe_to_pay", ""))
        requested = decimal((request or {}).get("amount", ""))
        if amount is None:
            amount_errors.append(row.get("request_id", ""))
        elif amount < 0 or (requested is not None and amount > requested):
            amount_errors.append(row.get("request_id", ""))

        earliest = row.get("earliest_date_for_full_payment", "")
        if earliest != "NONE" and not _date_is_valid(earliest):
            earliest_errors.append(row.get("request_id", ""))

        spending = row.get("spending_changes_needed", "")
        if spending != "none" and (not SPENDING_RE.match(spending) or int(SPENDING_RE.match(spending).group(1)) > 100):
            spending_errors.append(row.get("request_id", ""))

        explanation = row.get("decision_explanation", "")
        status = row.get("affordability_status", "")
        method = row.get("recommended_payment_method", "")
        expected_phrase = "Partially affordable" if method == "partial_payment" else "Not recommended" if method == "not_recommended" else "Wait" if method == "wait" else "Affordable"
        if not explanation or expected_phrase.lower() not in explanation.lower():
            explanation_errors.append(row.get("request_id", ""))

    return {
        "schema_valid": headers == OUTPUT_HEADERS,
        "expected_headers": OUTPUT_HEADERS,
        "actual_headers": headers,
        "rows": len(rows),
        "duplicate_request_ids": duplicates,
        "missing_request_ids": missing_ids,
        "unexpected_request_ids": unexpected_ids,
        "blank_request_ids": blank_ids,
        "invalid_statuses": invalid_statuses,
        "invalid_payment_methods": invalid_methods,
        "malformed_plans": malformed_plans,
        "arithmetic_errors": sorted(set(arithmetic_errors)),
        "safe_amount_errors": amount_errors,
        "safety_errors": amount_errors,
        "earliest_date_errors": earliest_errors,
        "spending_change_errors": spending_errors,
        "explanation_errors": explanation_errors,
    }