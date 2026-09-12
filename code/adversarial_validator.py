import re
import copy
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Set, Tuple, Any

from .models import PurchaseRequest, PaymentOption, Profile, Event, PaymentSchedule
from .financial_state import ReconstructedFinancialState
from .simulator import BalanceSimulator, SimulationResult, is_event_active_on_date
from .currency import CurrencyConverter
from .optimizer import (
    OptimizerOutputRow,
    OptimizedCandidatePlan,
    METHOD_FULL_PAYMENT,
    METHOD_PARTIAL_PAYMENT,
    METHOD_INSTALLMENTS,
    METHOD_WAIT,
    METHOD_NOT_RECOMMENDED,
    STATUS_AFFORDABLE,
    STATUS_AFFORDABLE_WITH_DELAY,
    STATUS_AFFORDABLE_WITH_SPENDING_CHANGES,
    STATUS_AFFORDABLE_WITH_DELAY_AND_SPENDING_CHANGES,
    STATUS_PARTIALLY_AFFORDABLE,
    STATUS_NOT_AFFORDABLE,
    ALLOWED_AFFORDABILITY_STATUSES,
    ALLOWED_RECOMMENDED_METHODS
)

logger = logging.getLogger(__name__)


class FatalValidationError(Exception):
    """Raised when an output row fails validation, cannot be repaired, and fallback is rejected."""
    pass


@dataclass
class InvariantViolation:
    rule_name: str
    message: str


@dataclass
class ValidationStatistics:
    total_validated: int = 0
    passed_first_pass: int = 0
    repaired_count: int = 0
    fallen_back_count: int = 0
    final_valid: int = 0
    violations_detected: Dict[str, int] = field(default_factory=dict)
    repairs_applied: List[Dict[str, Any]] = field(default_factory=list)
    fallbacks_applied: List[Dict[str, Any]] = field(default_factory=list)

    def record_violation(self, rule_name: str):
        self.violations_detected[rule_name] = self.violations_detected.get(rule_name, 0) + 1

    def record_repair(self, request_id: str, rule_name: str, action: str):
        self.repaired_count += 1
        self.repairs_applied.append({
            "request_id": request_id,
            "rule": rule_name,
            "action": action
        })

    def record_fallback(self, request_id: str, reason: str):
        self.fallen_back_count += 1
        self.fallbacks_applied.append({
            "request_id": request_id,
            "reason": reason
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_validated": self.total_validated,
            "passed_first_pass": self.passed_first_pass,
            "repaired_count": self.repaired_count,
            "fallen_back_count": self.fallen_back_count,
            "final_valid": self.final_valid,
            "initial_failure_rate_pct": round(
                ((self.total_validated - self.passed_first_pass) / max(1, self.total_validated)) * 100.0, 2
            ),
            "final_success_rate_pct": round(
                (self.final_valid / max(1, self.total_validated)) * 100.0, 2
            ),
            "violations_detected_by_rule": self.violations_detected,
            "number_of_repairs": len(self.repairs_applied),
            "number_of_fallbacks": len(self.fallbacks_applied),
            "repairs_sample": self.repairs_applied[:10],
            "fallbacks_sample": self.fallbacks_applied[:10]
        }


class StrictAdversarialValidator:
    """
    Strict adversarial validation layer for the Buy or Wait Financial Engine.
    Executes 21 adversarial invariants before writing rows to output.csv / output_optimizer.csv.
    Enforces deterministic repair and safest valid fallback.
    """

    FULL_PAYMENT_PATTERN = re.compile(
        r"^Full payment of (\d+\.\d{2}) ([A-Z]{3}) on (\d{4}-\d{2}-\d{2}) \(Option: ([^\)]+)\)$"
    )
    INSTALLMENT_PATTERN = re.compile(
        r"^(\d+) installments of (\d+\.\d{2}) ([A-Z]{3}) starting (\d{4}-\d{2}-\d{2}) \(Total: (\d+\.\d{2}) [A-Z]{3}, Option: ([^\)]+)\)$"
    )
    PARTIAL_PATTERN = re.compile(
        r"^2 payments: (\d+\.\d{2}) ([A-Z]{3}) on (\d{4}-\d{2}-\d{2}), (\d+\.\d{2}) [A-Z]{3} on (\d{4}-\d{2}-\d{2}) \(Total: (\d+\.\d{2}) [A-Z]{3}, Option: ([^\)]+)\)$"
    )
    SPENDING_CHANGES_PATTERN = re.compile(r"^reduce_flexible_expenses_by_(\d+)%$")
    RECURRING_FREQUENCIES = frozenset({
        "daily", "weekly", "bi-weekly", "biweekly", "monthly", "quarterly", "annual"
    })

    def __init__(
        self,
        simulator: BalanceSimulator,
        currency_converter: CurrencyConverter,
        available_options_by_request: Dict[str, List[PaymentOption]]
    ):
        self.simulator = simulator
        self.converter = currency_converter
        self.available_options = available_options_by_request
        self.stats = ValidationStatistics()

    def validate_and_repair(
        self,
        row: OptimizerOutputRow,
        request: PurchaseRequest,
        state: ReconstructedFinancialState
    ) -> OptimizerOutputRow:
        """
        Validates the output row against all 21 adversarial invariants.
        If violations are detected, attempts deterministic repair and revalidates.
        If still invalid, applies safest valid fallback.
        Raises FatalValidationError if even the fallback fails.
        """
        self.stats.total_validated += 1
        row = copy.deepcopy(row)

        # 1. Initial validation pass
        violations = self._run_all_invariants(row, request, state)

        if not violations:
            self.stats.passed_first_pass += 1
            self.stats.final_valid += 1
            return row

        # Record violations detected
        for v in violations:
            self.stats.record_violation(v.rule_name)
            logger.info(f"[{request.request_id}] Adversarial violation detected: {v.rule_name} - {v.message}")

        # 2. Attempt deterministic repair
        repaired_row, repair_actions = self._attempt_deterministic_repair(row, violations, request, state)
        for rule_name, action in repair_actions:
            self.stats.record_repair(request.request_id, rule_name, action)
            logger.info(f"[{request.request_id}] Applied deterministic repair: {action}")

        # 3. Revalidate after repair
        revalidation_violations = self._run_all_invariants(repaired_row, request, state)
        if not revalidation_violations:
            self.stats.final_valid += 1
            logger.info(f"[{request.request_id}] Successfully repaired row; all invariants passed.")
            return repaired_row

        # 4. If still invalid, apply safest valid fallback
        logger.warning(
            f"[{request.request_id}] Row remains invalid after repair ({len(revalidation_violations)} violations). "
            f"Applying safest valid fallback (not_recommended)."
        )
        fallback_row = self._apply_safest_fallback(repaired_row, request, state, revalidation_violations)
        self.stats.record_fallback(
            request.request_id,
            f"Failed invariants after repair: {[v.rule_name for v in revalidation_violations]}"
        )

        # 5. Validate the fallback
        fallback_violations = self._run_all_invariants(fallback_row, request, state)
        if fallback_violations:
            err_msg = (
                f"FATAL: Safest fallback for request {request.request_id} failed validation invariants: "
                f"{[v.rule_name + ': ' + v.message for v in fallback_violations]}"
            )
            logger.error(err_msg)
            raise FatalValidationError(err_msg)

        self.stats.final_valid += 1
        return fallback_row

    # =========================================================================
    # 21 Adversarial Invariant Checks
    # =========================================================================

    def _run_all_invariants(
        self,
        row: OptimizerOutputRow,
        request: PurchaseRequest,
        state: ReconstructedFinancialState
    ) -> List[InvariantViolation]:
        violations: List[InvariantViolation] = []

        # Rule 1: request_id exists
        if not row.request_id or row.request_id.strip() == "" or row.request_id != request.request_id:
            violations.append(InvariantViolation(
                "request_id_exists",
                f"request_id '{row.request_id}' is empty or does not match request '{request.request_id}'"
            ))

        # Rule 2: amount_safe_to_pay is numeric
        amount_safe = None
        try:
            amount_safe = Decimal(str(row.amount_safe_to_pay))
        except (InvalidOperation, TypeError, ValueError):
            violations.append(InvariantViolation(
                "amount_safe_to_pay_is_numeric",
                f"amount_safe_to_pay '{row.amount_safe_to_pay}' is not numeric"
            ))

        # Rule 3: 0 <= amount_safe_to_pay <= requested_amount
        if amount_safe is not None:
            if amount_safe < Decimal("0.00") or amount_safe > request.amount:
                violations.append(InvariantViolation(
                    "amount_safe_to_pay_bounds",
                    f"amount_safe_to_pay {amount_safe} not in range [0.00, {request.amount}]"
                ))

        # Rule 4: affordability_status is one of the allowed values
        if row.affordability_status not in ALLOWED_AFFORDABILITY_STATUSES:
            violations.append(InvariantViolation(
                "affordability_status_allowed",
                f"affordability_status '{row.affordability_status}' not in allowed values: {ALLOWED_AFFORDABILITY_STATUSES}"
            ))

        # Rule 5: recommended_payment_method is one of the allowed values
        if row.recommended_payment_method not in ALLOWED_RECOMMENDED_METHODS:
            violations.append(InvariantViolation(
                "recommended_payment_method_allowed",
                f"recommended_payment_method '{row.recommended_payment_method}' not in allowed values: {ALLOWED_RECOMMENDED_METHODS}"
            ))

        # Rule 6: payment_plan has correct syntax
        syntax_ok = self._verify_payment_plan_syntax(row)
        if not syntax_ok:
            violations.append(InvariantViolation(
                "payment_plan_syntax",
                f"payment_plan '{row.payment_plan}' does not match syntax for method '{row.recommended_payment_method}'"
            ))

        # Extract schedule from winning_plan if present
        sched = row.winning_plan.schedule if (row.winning_plan and row.winning_plan.schedule) else None

        # Rule 7: payment_plan dates are chronological
        if sched and row.recommended_payment_method != METHOD_NOT_RECOMMENDED:
            if not sched.due_dates or len(sched.due_dates) != len(sched.due_amounts):
                violations.append(InvariantViolation("payment_plan_dates_chronological", "due_dates is empty"))
            else:
                for d in sched.due_dates:
                    if d < request.request_date:
                        violations.append(InvariantViolation(
                            "payment_plan_dates_chronological",
                            f"due date {d} is before request date {request.request_date}"
                        ))
                for i in range(len(sched.due_dates) - 1):
                    if sched.due_dates[i] > sched.due_dates[i + 1]:
                        violations.append(InvariantViolation(
                            "payment_plan_dates_chronological",
                            f"due dates are not chronological: {sched.due_dates[i]} > {sched.due_dates[i + 1]}"
                        ))
                if row.recommended_payment_method == METHOD_PARTIAL_PAYMENT and len(sched.due_dates) == 2:
                    if sched.due_dates[0] >= sched.due_dates[1]:
                        violations.append(InvariantViolation(
                            "payment_plan_dates_chronological",
                            f"partial payment dates must be strictly increasing: {sched.due_dates[0]} >= {sched.due_dates[1]}"
                        ))

        # Rule 8: payment amounts are valid
        if sched and row.recommended_payment_method != METHOD_NOT_RECOMMENDED:
            for i, amt in enumerate(sched.due_amounts):
                try:
                    numeric_amt = Decimal(str(amt))
                except (InvalidOperation, TypeError, ValueError):
                    violations.append(InvariantViolation(
                        "payment_amounts_valid",
                        f"payment amount {i} ({amt}) is not numeric"
                    ))
                    continue
                if numeric_amt <= Decimal("0.00"):
                    violations.append(InvariantViolation(
                        "payment_amounts_valid",
                        f"payment amount {i} ({amt}) is <= 0.00"
                    ))
                if numeric_amt.as_tuple().exponent < -2:
                    violations.append(InvariantViolation(
                        "payment_amounts_valid",
                        f"payment amount {i} ({amt}) has more than 2 decimal places"
                    ))

        # Rule 9: payment-plan totals are correct
        if sched and row.recommended_payment_method != METHOD_NOT_RECOMMENDED:
            try:
                total_due = sum(Decimal(str(amount)) for amount in sched.due_amounts)
                total_nominal_cost = Decimal(str(sched.total_nominal_cost))
            except (InvalidOperation, TypeError, ValueError):
                total_due = None
                total_nominal_cost = None
            if total_due is not None and abs(total_due - total_nominal_cost) > Decimal("0.05"):
                violations.append(InvariantViolation(
                    "payment_plan_totals_correct",
                    f"sum of due amounts ({total_due}) does not equal total_nominal_cost ({total_nominal_cost})"
                ))

            if sched.installments_count != len(sched.due_amounts):
                violations.append(InvariantViolation(
                    "payment_amounts_valid",
                    f"installments_count {sched.installments_count} does not match {len(sched.due_amounts)} due amounts"
                ))

        # Rule 10: partial-payment plans contain exactly two payments
        if row.recommended_payment_method == METHOD_PARTIAL_PAYMENT:
            if not sched or len(sched.due_amounts) != 2 or len(sched.due_dates) != 2:
                violations.append(InvariantViolation(
                    "partial_payment_exactly_two_payments",
                    f"partial payment plan does not contain exactly two payments (found {len(sched.due_amounts) if sched else 0})"
                ))

        # Rule 11: partial-payment payments sum exactly to requested_amount
        if row.recommended_payment_method == METHOD_PARTIAL_PAYMENT:
            if sched and len(sched.due_amounts) == 2:
                total_partial = sched.due_amounts[0] + sched.due_amounts[1]
                if abs(total_partial - request.amount) > Decimal("0.01"):
                    violations.append(InvariantViolation(
                        "partial_payment_sums_to_requested",
                        f"partial payments sum to {total_partial}, expected requested amount {request.amount}"
                    ))

        # Rule 12: installment plans exactly match a supplied payment option
        if row.recommended_payment_method == METHOD_INSTALLMENTS:
            matched_opt = self._find_matching_option(row, request)
            if not matched_opt:
                violations.append(InvariantViolation(
                    "installment_matches_supplied_option",
                    f"installment plan does not match any supplied payment option for request {request.request_id}"
                ))

        # Rule 13: spending_changes_needed references only flexible recurring events
        if row.spending_changes_needed != "none":
            match = self.SPENDING_CHANGES_PATTERN.match(row.spending_changes_needed)
            if not match:
                violations.append(InvariantViolation(
                    "spending_changes_flexible_only",
                    f"spending_changes_needed '{row.spending_changes_needed}' does not match allowed format"
                ))
            else:
                pct = int(match.group(1))
                if pct <= 0 or pct > 100:
                    violations.append(InvariantViolation(
                        "spending_changes_flexible_only",
                        f"spending change percentage {pct}% outside range (0, 100]"
                    ))
                else:
                    flexible_recurring = self._flexible_recurring_events(state)
                    if not flexible_recurring:
                        violations.append(InvariantViolation(
                            "spending_changes_flexible_only",
                            "spending reduction requested but no flexible recurring events exist in state"
                        ))
                    if row.winning_plan and row.winning_plan.diagnostics:
                        diag = row.winning_plan.diagnostics
                        if not diag.spending_changes_affect_only_flexible:
                            violations.append(InvariantViolation(
                                "spending_changes_flexible_only",
                                "spending changes must affect only flexible recurring events"
                            ))
                        expected_pct = int(diag.spending_reduction_pct * Decimal("100"))
                        if expected_pct != pct:
                            violations.append(InvariantViolation(
                                "spending_changes_flexible_only",
                                f"spending_changes_needed {pct}% does not match plan diagnostics {expected_pct}%"
                            ))

        # Rule 14: no event is both stopped and reduced
        conflict_events = self._check_stopped_and_reduced_events(state, row)
        if conflict_events:
            violations.append(InvariantViolation(
                "no_event_both_stopped_and_reduced",
                f"events both stopped and reduced in state: {conflict_events}"
            ))

        # Rule 15: affordable_now implies earliest_date_for_full_payment == request_date
        if row.affordability_status in [STATUS_AFFORDABLE, STATUS_AFFORDABLE_WITH_SPENDING_CHANGES, "affordable_now"]:
            req_date_str = request.request_date.isoformat()
            if row.earliest_date_for_full_payment != req_date_str:
                violations.append(InvariantViolation(
                    "affordable_now_earliest_date",
                    f"affordability_status '{row.affordability_status}' requires earliest_date_for_full_payment to be '{req_date_str}', but got '{row.earliest_date_for_full_payment}'"
                ))

        # Rule 16: not-safe plans never violate minimum_balance_to_keep
        # Any plan recommended as approved must keep projected balance >= minimum_balance_to_keep
        if row.recommended_payment_method != METHOD_NOT_RECOMMENDED:
            if not row.winning_plan or not row.winning_plan.simulation.is_safe:
                violations.append(InvariantViolation(
                    "approved_plan_must_be_safe",
                    f"recommended method '{row.recommended_payment_method}' is marked unsafe or breaches minimum balance"
                ))

        # Rule 17: requested completion date is respected
        if request.desired_completion_date and row.recommended_payment_method != METHOD_NOT_RECOMMENDED:
            if sched and sched.due_dates:
                last_due = max(sched.due_dates)
                if last_due > request.desired_completion_date:
                    violations.append(InvariantViolation(
                        "completion_date_respected",
                        f"payment plan completion date {last_due} exceeds desired completion date {request.desired_completion_date}"
                    ))

        # Rule 18: no unsupported income/expense/payment option is invented
        unsupported_events = self._check_unsupported_events(state)
        if unsupported_events:
            violations.append(InvariantViolation(
                "no_unsupported_financial_event",
                f"active financial events are unsupported or unavailable: {unsupported_events}"
            ))

        invented_option = self._check_invented_payment_option(row, request)
        if invented_option:
            violations.append(InvariantViolation(
                "no_unsupported_payment_option",
                invented_option
            ))

        # Rule 19: no cancelled/failed/pending credit is incorrectly treated as available
        invalid_inflows = [
            ev.event_id for ev in state.active_inflows
            if ev.status in ("cancelled", "failed", "pending")
        ]
        if invalid_inflows:
            violations.append(InvariantViolation(
                "no_cancelled_credit_available",
                f"cancelled, failed, or pending credits present in active inflows: {invalid_inflows}"
            ))

        # Rule 20: currency conversions use supplied dated exchange rates
        missing_rates = self._check_currency_rates(state, request, row)
        if missing_rates:
            violations.append(InvariantViolation(
                "currency_conversions_supplied_rates",
                f"missing supplied exchange rates for pairs: {missing_rates}"
            ))

        # Rule 21: payment plans remain safe throughout the 90-day forecast
        # Re-run full independent 90-day simulation to verify daily balances >= minimum_balance_to_keep
        if row.recommended_payment_method != METHOD_NOT_RECOMMENDED and sched and row.winning_plan:
            spending_pct = Decimal("0.00")
            if row.winning_plan.diagnostics:
                spending_pct = row.winning_plan.diagnostics.spending_reduction_pct

            re_sim = self.simulator.simulate(
                state=state,
                request_date=request.request_date,
                plan_schedule=sched,
                flexible_reduction_pct=spending_pct
            )
            if not re_sim.is_safe:
                violations.append(InvariantViolation(
                    "payment_plan_safe_throughout_90_days",
                    f"independent 90-day re-simulation failed: cushion breached on day {re_sim.failed_on_day} with cushion {re_sim.min_cushion_observed} < {state.profile.minimum_balance_to_keep}"
                ))

        return violations

    # =========================================================================
    # Invariant Helpers
    # =========================================================================

    def _verify_payment_plan_syntax(self, row: OptimizerOutputRow) -> bool:
        plan_str = row.payment_plan
        method = row.recommended_payment_method

        if method == METHOD_NOT_RECOMMENDED:
            return plan_str == "NONE"

        if method == METHOD_FULL_PAYMENT:
            match = self.FULL_PAYMENT_PATTERN.match(plan_str)
            if not match:
                return False
            amount, currency, due_date, option_id = match.groups()
            sched = row.winning_plan.schedule if row.winning_plan else None
            if not sched:
                return True
            return (
                currency == sched.currency
                and option_id == sched.option_id
                and len(sched.due_dates) == 1
                and due_date == sched.due_dates[0].isoformat()
                and Decimal(amount) == Decimal(str(sched.due_amounts[0]))
            )

        if method == METHOD_INSTALLMENTS:
            match = self.INSTALLMENT_PATTERN.match(plan_str)
            if not match:
                return False
            count, amount, currency, start_date, total, option_id = match.groups()
            sched = row.winning_plan.schedule if row.winning_plan else None
            if not sched:
                return True
            return (
                int(count) == sched.installments_count
                and currency == sched.currency
                and amount == f"{sched.installment_amount:.2f}"
                and start_date == sched.start_date.isoformat()
                and Decimal(total) == sched.total_nominal_cost
                and option_id == sched.option_id
            )

        if method == METHOD_PARTIAL_PAYMENT:
            match = self.PARTIAL_PATTERN.match(plan_str)
            if not match:
                return False
            amount_one, currency_one, date_one, amount_two, date_two, total, option_id = match.groups()
            sched = row.winning_plan.schedule if row.winning_plan else None
            if not sched:
                return True
            return (
                currency_one == sched.currency
                and currency_one == sched.currency
                and option_id == "NONE"
                and len(sched.due_amounts) == 2
                and date_one == sched.due_dates[0].isoformat()
                and date_two == sched.due_dates[1].isoformat()
                and Decimal(amount_one) == Decimal(str(sched.due_amounts[0]))
                and Decimal(amount_two) == Decimal(str(sched.due_amounts[1]))
                and Decimal(total) == sched.total_nominal_cost
            )

        if method == METHOD_WAIT:
            return bool(self.FULL_PAYMENT_PATTERN.match(plan_str) or self.INSTALLMENT_PATTERN.match(plan_str))

        return False

    def _find_matching_option(self, row: OptimizerOutputRow, request: PurchaseRequest) -> Optional[PaymentOption]:
        options = self.available_options.get(request.request_id, [])
        sched = row.winning_plan.schedule if row.winning_plan else None
        if not sched:
            return None

        from .plan_generator import PaymentPlanGenerator

        for opt in options:
            if opt.option_id != sched.option_id:
                continue
            if opt.installments_count != sched.installments_count:
                continue
            expected = PaymentPlanGenerator.build_schedule(
                opt, request.amount, sched.start_date,
                amount_currency=request.currency,
                currency_converter=self.currency_converter,
            )
            if (
                expected.payment_type == sched.payment_type
                and expected.installment_amount == sched.installment_amount
                and expected.total_nominal_cost == sched.total_nominal_cost
                and expected.due_dates == sched.due_dates
                and expected.due_amounts == sched.due_amounts
                and expected.currency == sched.currency
            ):
                return opt

        return None

    def _flexible_recurring_events(self, state: ReconstructedFinancialState) -> List[Event]:
        return [
            ev for ev in state.active_flexible_expenses
            if (ev.frequency or "one-time").lower() in self.RECURRING_FREQUENCIES
        ]

    def _check_invented_payment_option(
        self,
        row: OptimizerOutputRow,
        request: PurchaseRequest
    ) -> Optional[str]:
        if row.recommended_payment_method == METHOD_NOT_RECOMMENDED:
            return None

        valid_ids = {opt.option_id for opt in self.available_options.get(request.request_id, [])}
        sched = row.winning_plan.schedule if row.winning_plan else None

        if row.recommended_payment_method == METHOD_PARTIAL_PAYMENT:
            return None

        if sched and sched.option_id and sched.option_id not in valid_ids:
            if sched.option_id.startswith("opt_partial_") or sched.option_id.startswith("opt_default_"):
                return None
            return f"option '{sched.option_id}' does not exist in supplied payment options"

        if row.winning_plan and row.winning_plan.option:
            opt_id = row.winning_plan.option.option_id
            if opt_id not in valid_ids:
                return f"option '{opt_id}' does not exist in supplied payment options"

        return None

    def _check_currency_rates(
        self,
        state: ReconstructedFinancialState,
        request: PurchaseRequest,
        row: OptimizerOutputRow
    ) -> List[Tuple[str, str]]:
        base = state.profile.base_currency
        currencies: Set[str] = {request.currency, base}
        for ev in state.active_inflows + state.active_essential_expenses + state.active_flexible_expenses:
            currencies.add(ev.currency)
        if row.winning_plan and row.winning_plan.schedule:
            currencies.add(row.winning_plan.schedule.currency)
        missing = self.converter.missing_rate_pairs(list(currencies), base)
        dates = [request.request_date + timedelta(days=offset) for offset in range(91)]
        if row.winning_plan and row.winning_plan.schedule:
            dates.extend(row.winning_plan.schedule.due_dates)
        for currency in currencies:
            if currency.upper() == base.upper():
                continue
            if any(not self.converter.has_supplied_rate_on_date(currency, base, day) for day in dates):
                pair = (currency, base)
                if pair not in missing:
                    missing.append(pair)
        return missing

    def _check_unsupported_events(self, state: ReconstructedFinancialState) -> List[str]:
        unsupported: List[str] = []
        for event in state.active_inflows + state.active_essential_expenses + state.active_flexible_expenses:
            if event.status != "confirmed" or event.amount is None:
                unsupported.append(event.event_id)
                continue
            if event.event_type in ("income", "refund"):
                continue
            if event.event_type in ("expense", "investment"):
                continue
            unsupported.append(event.event_id)
        return unsupported

    def _check_stopped_and_reduced_events(
        self,
        state: ReconstructedFinancialState,
        row: OptimizerOutputRow
    ) -> List[str]:
        """Detect events that are both stopped (cancelled/failed) and targeted for reduction."""
        conflicts: List[str] = []
        if row.spending_changes_needed == "none":
            return conflicts

        active_flexible_ids = {ev.event_id for ev in state.active_flexible_expenses}
        for ev in state.active_flexible_expenses:
            if ev.status in ("cancelled", "failed"):
                conflicts.append(ev.event_id)

        all_events = (
            state.active_inflows
            + state.active_essential_expenses
            + state.active_flexible_expenses
        )
        for ev in all_events:
            if ev.status in ("cancelled", "failed") and ev.event_id in active_flexible_ids:
                conflicts.append(ev.event_id)

        return list(set(conflicts))

    # =========================================================================
    # Deterministic Repair Engine
    # =========================================================================

    def _attempt_deterministic_repair(
        self,
        row: OptimizerOutputRow,
        violations: List[InvariantViolation],
        request: PurchaseRequest,
        state: ReconstructedFinancialState
    ) -> Tuple[OptimizerOutputRow, List[Tuple[str, str]]]:
        """
        Applies deterministic repairs to the row based on detected invariant violations.
        """
        repairs_applied: List[Tuple[str, str]] = []
        v_rules = {v.rule_name for v in violations}

        # Repair 1: request_id mismatch or empty
        if "request_id_exists" in v_rules:
            row.request_id = request.request_id
            repairs_applied.append(("request_id_exists", f"Set request_id to '{request.request_id}'"))

        # Repair 2 & 3: amount_safe_to_pay bounds or non-numeric
        if "amount_safe_to_pay_is_numeric" in v_rules or "amount_safe_to_pay_bounds" in v_rules:
            baseline_sim = self.simulator.simulate(state, request.request_date, None)
            headroom = baseline_sim.min_cushion_observed - state.profile.minimum_balance_to_keep
            clamped = max(Decimal("0.00"), min(request.amount, headroom.quantize(Decimal("0.01"))))
            row.amount_safe_to_pay = f"{clamped:.2f}"
            repairs_applied.append(("amount_safe_to_pay_bounds", f"Clamped amount_safe_to_pay to {row.amount_safe_to_pay}"))

        # Repair 4 & 5: affordability_status and recommended_payment_method
        if "affordability_status_allowed" in v_rules:
            row.affordability_status = self._derive_affordability_status(row)
            repairs_applied.append(("affordability_status_allowed", f"Derived status '{row.affordability_status}' from method"))

        if "recommended_payment_method_allowed" in v_rules:
            if row.recommended_payment_method not in ALLOWED_RECOMMENDED_METHODS:
                row.recommended_payment_method = METHOD_NOT_RECOMMENDED
                row.affordability_status = STATUS_NOT_AFFORDABLE
                row.payment_plan = "NONE"
                repairs_applied.append(("recommended_payment_method_allowed", "Reset invalid method to 'not_recommended'"))

        # Repair 13: spending_changes references only flexible recurring events
        if "spending_changes_flexible_only" in v_rules:
            row.spending_changes_needed = "none"
            if row.winning_plan and row.winning_plan.diagnostics:
                row.winning_plan.diagnostics.spending_changes_needed = False
                row.winning_plan.diagnostics.spending_reduction_pct = Decimal("0.00")
            repairs_applied.append(("spending_changes_flexible_only", "Cleared invalid spending changes to 'none'"))

        # Repair 14: no event both stopped and reduced
        if "no_event_both_stopped_and_reduced" in v_rules:
            row.spending_changes_needed = "none"
            if row.winning_plan and row.winning_plan.diagnostics:
                row.winning_plan.diagnostics.spending_changes_needed = False
                row.winning_plan.diagnostics.spending_reduction_pct = Decimal("0.00")
            repairs_applied.append(("no_event_both_stopped_and_reduced", "Removed spending reduction to resolve stop/reduce conflict"))

        # Repair 9: payment plan totals
        if "payment_plan_totals_correct" in v_rules and row.winning_plan and row.winning_plan.schedule:
            sched = row.winning_plan.schedule
            total_due = sum(sched.due_amounts)
            sched.total_nominal_cost = total_due
            repairs_applied.append(("payment_plan_totals_correct", f"Set total_nominal_cost to {total_due}"))

        # Repair 15: affordable_now implies earliest_date_for_full_payment == request_date
        if "affordable_now_earliest_date" in v_rules:
            row.earliest_date_for_full_payment = request.request_date.isoformat()
            repairs_applied.append((
                "affordable_now_earliest_date",
                f"Set earliest_date_for_full_payment to request_date ({request.request_date.isoformat()})"
            ))

        # Repair 6: payment_plan syntax
        if "payment_plan_syntax" in v_rules:
            sched = row.winning_plan.schedule if row.winning_plan else None
            method = row.recommended_payment_method
            curr = request.currency
            if method == METHOD_NOT_RECOMMENDED or not sched:
                row.payment_plan = "NONE"
                repairs_applied.append(("payment_plan_syntax", "Set payment_plan to 'NONE'"))
            elif method == METHOD_PARTIAL_PAYMENT and len(sched.due_amounts) == 2:
                p1, p2 = sched.due_amounts[0], sched.due_amounts[1]
                d1, d2 = sched.due_dates[0], sched.due_dates[1]
                row.payment_plan = f"2 payments: {p1:.2f} {curr} on {d1.isoformat()}, {p2:.2f} {curr} on {d2.isoformat()} (Total: {sched.total_nominal_cost:.2f} {curr}, Option: NONE)"
                repairs_applied.append(("payment_plan_syntax", "Regenerated 2-payment partial syntax"))
            elif sched.installments_count == 1:
                opt_id = row.winning_plan.option.option_id if (row.winning_plan and row.winning_plan.option) else "NONE"
                row.payment_plan = f"Full payment of {sched.total_nominal_cost:.2f} {curr} on {row.winning_plan.start_date.isoformat()} (Option: {opt_id})"
                repairs_applied.append(("payment_plan_syntax", "Regenerated full payment syntax"))
            else:
                opt_id = row.winning_plan.option.option_id if (row.winning_plan and row.winning_plan.option) else "NONE"
                row.payment_plan = f"{sched.installments_count} installments of {sched.installment_amount:.2f} {curr} starting {row.winning_plan.start_date.isoformat()} (Total: {sched.total_nominal_cost:.2f} {curr}, Option: {opt_id})"
                repairs_applied.append(("payment_plan_syntax", "Regenerated installment syntax"))

        # Repair 10 & 11: partial payment 2 payments and sum
        if ("partial_payment_exactly_two_payments" in v_rules or "partial_payment_sums_to_requested" in v_rules) and row.recommended_payment_method == METHOD_PARTIAL_PAYMENT:
            try:
                safe_amt = Decimal(str(row.amount_safe_to_pay))
            except Exception:
                safe_amt = (request.amount / Decimal("2.00")).quantize(Decimal("0.01"))
            if safe_amt >= request.amount or safe_amt <= Decimal("0.00"):
                p1 = (request.amount / Decimal("2.00")).quantize(Decimal("0.01"))
            else:
                p1 = safe_amt.quantize(Decimal("0.01"))
            p2 = (request.amount - p1).quantize(Decimal("0.01"))
            d1 = request.request_date
            d2 = request.desired_completion_date if request.desired_completion_date > d1 else (d1 + timedelta(days=14))
            
            repaired_sched = PaymentSchedule(
                option_id=f"opt_partial_{request.request_id}",
                payment_type="PARTIAL",
                start_date=d1,
                installments_count=2,
                installment_amount=p1,
                total_nominal_cost=request.amount,
                due_dates=[d1, d2],
                due_amounts=[p1, p2],
                currency=request.currency
            )
            if row.winning_plan:
                row.winning_plan.schedule = repaired_sched
            curr = request.currency
            row.payment_plan = f"2 payments: {p1:.2f} {curr} on {d1.isoformat()}, {p2:.2f} {curr} on {d2.isoformat()} (Total: {request.amount:.2f} {curr}, Option: NONE)"
            repairs_applied.append(("partial_payment_sums_to_requested", "Rebuilt partial schedule with exactly 2 payments summing to requested amount"))

        return row, repairs_applied

    def _derive_affordability_status(self, row: OptimizerOutputRow) -> str:
        if row.affordability_status == "affordable_now":
            return STATUS_AFFORDABLE
        method = row.recommended_payment_method
        has_spending = row.spending_changes_needed != "none"
        if method == METHOD_NOT_RECOMMENDED:
            return STATUS_NOT_AFFORDABLE
        if method == METHOD_PARTIAL_PAYMENT:
            return STATUS_PARTIALLY_AFFORDABLE
        if method == METHOD_WAIT:
            return STATUS_AFFORDABLE_WITH_DELAY_AND_SPENDING_CHANGES if has_spending else STATUS_AFFORDABLE_WITH_DELAY
        if method in (METHOD_FULL_PAYMENT, METHOD_INSTALLMENTS):
            return STATUS_AFFORDABLE_WITH_SPENDING_CHANGES if has_spending else STATUS_AFFORDABLE
        return STATUS_NOT_AFFORDABLE

    # =========================================================================
    # Safest Valid Fallback
    # =========================================================================

    def _apply_safest_fallback(
        self,
        row: OptimizerOutputRow,
        request: PurchaseRequest,
        state: ReconstructedFinancialState,
        unresolved_violations: List[InvariantViolation]
    ) -> OptimizerOutputRow:
        """
        Creates the guaranteed-safe fallback row (not_recommended / not_affordable).
        """
        baseline_sim = self.simulator.simulate(state, request.request_date, None)
        headroom = baseline_sim.min_cushion_observed - state.profile.minimum_balance_to_keep
        safe_amount = max(Decimal("0.00"), min(request.amount, headroom.quantize(Decimal("0.01"))))

        reasons = [v.rule_name for v in unresolved_violations]
        explanation = (
            f"Not recommended. Projected cashflow breaches your {state.profile.minimum_balance_to_keep:.2f} "
            f"{state.profile.base_currency} safety reserve over the 90-day forecast. "
            f"Maximum safe amount to pay today without risk is {safe_amount:.2f} {request.currency}."
        )

        return OptimizerOutputRow(
            request_id=request.request_id,
            amount_safe_to_pay=f"{safe_amount:.2f}",
            affordability_status=STATUS_NOT_AFFORDABLE,
            recommended_payment_method=METHOD_NOT_RECOMMENDED,
            payment_plan="NONE",
            earliest_date_for_full_payment=(
                request.request_date.isoformat()
                if row and row.affordability_status in {
                    STATUS_AFFORDABLE,
                    STATUS_AFFORDABLE_WITH_SPENDING_CHANGES,
                    "affordable_now",
                }
                else "NONE"
            ),
            spending_changes_needed="none",
            decision_explanation=explanation,
            winning_plan=None,
            all_diagnostics=row.all_diagnostics if row else []
        )
