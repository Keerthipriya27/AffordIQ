"""
Deterministic output validation and schema compliance checker.
"""
from pathlib import Path
from decimal import Decimal
from typing import List, Tuple
import csv
from code.models import OutputRow
from code.config import setup_logging

logger = setup_logging(__name__)

REQUIRED_OUTPUT_HEADERS = [
    "request_id", "amount_safe_to_pay", "affordability_status",
    "recommended_payment_method", "payment_plan",
    "earliest_date_for_full_payment", "spending_changes_needed",
    "decision_explanation"
]

class OutputValidator:
    @staticmethod
    def validate_rows(rows: List[OutputRow]) -> Tuple[bool, int, List[str]]:
        """
        Validates all generated output rows against business logic invariants.
        Returns: (is_all_valid, failure_count, error_messages)
        """
        errors = []
        failure_count = 0

        for r in rows:
            row_errors = []
            
            # 1. Decision enum
            if r.decision not in ["BUY_NOW", "WAIT", "DO_NOT_BUY"]:
                row_errors.append(f"Invalid decision: {r.decision}")

            # 2. Schema specifics for BUY_NOW & WAIT
            if r.decision in ["BUY_NOW", "WAIT"]:
                if r.recommended_option_id in ["", "NONE", None]:
                    row_errors.append("Missing recommended_option_id for approved plan")
                if r.installments_count < 1:
                    row_errors.append(f"Invalid installments_count: {r.installments_count}")
                if r.total_cost <= Decimal("0.00"):
                    row_errors.append(f"Invalid total_cost: {r.total_cost}")
                
                # Arithmetic check
                calc_total = r.installments_count * r.installment_amount
                # Difference should be <= 0.05 due to roundings
                if abs(calc_total - r.total_cost) > Decimal("0.10"):
                    row_errors.append(
                        f"Arithmetic mismatch: count({r.installments_count}) * amt({r.installment_amount}) "
                        f"= {calc_total} != total_cost({r.total_cost})"
                    )

            # 3. Schema specifics for DO_NOT_BUY
            if r.decision == "DO_NOT_BUY":
                if r.recommended_option_id not in ["NONE", "", None]:
                    row_errors.append(f"DO_NOT_BUY should not have option_id: {r.recommended_option_id}")

            # 4. Explanation length
            if len(r.explanation) == 0 or len(r.explanation) > 300:
                row_errors.append(f"Invalid explanation length: {len(r.explanation)}")

            if row_errors:
                failure_count += 1
                errors.append(f"Request {r.request_id}: {'; '.join(row_errors)}")

        is_valid = failure_count == 0
        return is_valid, failure_count, errors

    @staticmethod
    def validate_csv_file(file_path: Path) -> Tuple[bool, int, List[str]]:
        if not file_path.exists():
            return False, 1, [f"File {file_path} does not exist"]

        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header or header != REQUIRED_OUTPUT_HEADERS:
                return False, 1, [f"Invalid CSV header. Expected {REQUIRED_OUTPUT_HEADERS}, got {header}"]

        return True, 0, []
