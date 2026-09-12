"""Compare strict predictions with any overlapping expected sample rows."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, Mapping


def _decimal(value: str):
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _expected_status(row: Mapping[str, str]):
    if row.get("affordability_status"):
        return row["affordability_status"]
    return {
        "BUY_NOW": "affordable",
        "WAIT": "affordable_with_delay",
        "DO_NOT_BUY": "not_affordable",
    }.get(row.get("decision", ""))


def _expected_method(row: Mapping[str, str]):
    if row.get("recommended_payment_method"):
        return row["recommended_payment_method"]
    return {
        "FULL": "full_payment",
        "INSTALLMENTS": "installments",
        "DEFERRED": "wait",
        "FINANCING": "installments",
        "NONE": "not_recommended",
    }.get(row.get("payment_type", ""))


def compare_predictions(
    predictions: Iterable[Mapping[str, str]],
    expected: Iterable[Mapping[str, str]],
) -> Dict[str, object]:
    predicted = {row.get("request_id", ""): row for row in predictions}
    expected_map = {row.get("request_id", ""): row for row in expected}
    ids = sorted(set(predicted) & set(expected_map))

    status_matches = method_matches = 0
    safe_errors = []
    earliest_matches = spending_matches = 0
    comparable = {"safe_amount": 0, "earliest_date": 0, "spending_changes": 0}

    for request_id in ids:
        actual = predicted[request_id]
        truth = expected_map[request_id]
        expected_status = _expected_status(truth)
        expected_method = _expected_method(truth)
        if expected_status is not None and actual.get("affordability_status") == expected_status:
            status_matches += 1
        if expected_method is not None and actual.get("recommended_payment_method") == expected_method:
            method_matches += 1

        expected_amount = truth.get("amount_safe_to_pay")
        if expected_amount not in (None, ""):
            actual_amount = _decimal(actual.get("amount_safe_to_pay"))
            expected_decimal = _decimal(expected_amount)
            if actual_amount is not None and expected_decimal is not None:
                safe_errors.append(abs(actual_amount - expected_decimal))
                comparable["safe_amount"] += 1

        expected_date = truth.get("earliest_date_for_full_payment")
        if expected_date not in (None, ""):
            comparable["earliest_date"] += 1
            earliest_matches += int(actual.get("earliest_date_for_full_payment") == expected_date)

        expected_spending = truth.get("spending_changes_needed")
        if expected_spending not in (None, ""):
            comparable["spending_changes"] += 1
            spending_matches += int(actual.get("spending_changes_needed") == expected_spending)

    def accuracy(matches, denominator):
        return round(matches / denominator, 4) if denominator else None

    return {
        "comparable_requests": len(ids),
        "prediction_ids": len(predicted),
        "expected_ids": len(expected_map),
        "status_accuracy": accuracy(status_matches, len(ids)),
        "payment_method_accuracy": accuracy(method_matches, len(ids)),
        "safe_amount_mean_absolute_error": round(float(sum(safe_errors) / len(safe_errors)), 4) if safe_errors else None,
        "safe_amount_comparable_requests": comparable["safe_amount"],
        "earliest_date_accuracy": accuracy(earliest_matches, comparable["earliest_date"]),
        "spending_change_accuracy": accuracy(spending_matches, comparable["spending_changes"]),
        "comparable_fields": comparable,
    }


if __name__ == "__main__":
    print("Use evaluate.py to compare prediction and expected CSV files.")