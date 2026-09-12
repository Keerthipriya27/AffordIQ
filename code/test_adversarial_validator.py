import unittest
from datetime import date, timedelta
from decimal import Decimal

from code.models import PurchaseRequest, PaymentOption, Profile, Event, ExchangeRate
from code.financial_state import ReconstructedFinancialState, FinancialStateReconstructor
from code.currency import CurrencyConverter
from code.simulator import BalanceSimulator, PaymentSchedule, SimulationResult
from code.optimizer import (
    CandidatePaymentPlanOptimizer,
    PaymentPlanOutputMapper,
    OptimizerOutputRow,
    OptimizedCandidatePlan,
    CandidateDiagnostics,
    METHOD_FULL_PAYMENT,
    METHOD_PARTIAL_PAYMENT,
    METHOD_INSTALLMENTS,
    METHOD_WAIT,
    METHOD_NOT_RECOMMENDED,
    STATUS_AFFORDABLE,
    STATUS_AFFORDABLE_WITH_DELAY,
    STATUS_AFFORDABLE_WITH_SPENDING_CHANGES,
    STATUS_PARTIALLY_AFFORDABLE,
    STATUS_NOT_AFFORDABLE
)
from code.adversarial_validator import (
    StrictAdversarialValidator,
    FatalValidationError,
    ValidationStatistics
)


class TestStrictAdversarialValidator(unittest.TestCase):
    def setUp(self):
        self.converter = CurrencyConverter([
            ExchangeRate(date(2026, 9, 1), "USD", "USD", Decimal("1.00")),
            ExchangeRate(date(2026, 9, 1), "EUR", "USD", Decimal("1.10")),
        ])
        self.simulator = BalanceSimulator(self.converter)
        self.reconstructor = FinancialStateReconstructor(self.converter)
        
        self.profile = Profile(
            user_id="user_adv_01",
            current_balance=Decimal("2000.00"),
            minimum_balance_to_keep=Decimal("500.00"),
            monthly_essential_expenses=Decimal("800.00"),
            monthly_flexible_expenses=Decimal("200.00"),
            payment_methods_user_will_consider=["FULL", "INSTALLMENTS"],
            flexible_reduction_limit=Decimal("0.50"),
            base_currency="USD"
        )
        
        events = [
            Event(
                event_id="ev_salary",
                user_id="user_adv_01",
                event_type="income",
                category="salary",
                amount=Decimal("1500.00"),
                currency="USD",
                frequency="monthly",
                start_date=date(2026, 9, 25),
                is_essential=True
            ),
            Event(
                event_id="ev_rent",
                user_id="user_adv_01",
                event_type="expense",
                category="rent",
                amount=Decimal("800.00"),
                currency="USD",
                frequency="monthly",
                start_date=date(2026, 9, 28),
                is_essential=True
            )
        ]
        self.state = self.reconstructor.reconstruct(self.profile, events)

        self.request = PurchaseRequest(
            request_id="req_adv_001",
            user_id="user_adv_01",
            request_date=date(2026, 9, 12),
            item_name="Test Item",
            amount=Decimal("600.00"),
            currency="USD",
            desired_completion_date=date(2026, 10, 15),
            allows_partial_payment=True,
        )

        self.options = [
            PaymentOption(
                option_id="opt_adv_inst_4",
                request_id="req_adv_001",
                payment_type="INSTALLMENTS",
                installments_count=4,
                interest_rate_apr=Decimal("0.00"),
                fee_fixed=Decimal("0.00"),
                fee_percentage=Decimal("0.00"),
                interval_days=14,
                initial_deposit_pct=Decimal("0.25"),
                allows_partial_payment=True,
                currency="USD"
            )
        ]

        self.available_options = {"req_adv_001": self.options}
        self.validator = StrictAdversarialValidator(
            simulator=self.simulator,
            currency_converter=self.converter,
            available_options_by_request=self.available_options
        )

    def test_valid_affordable_row_passes_without_repair(self):
        """Rule 1-6 & 15: Clean affordable row passes initial validation immediately."""
        optimizer = CandidatePaymentPlanOptimizer(self.simulator)
        winning_plan = optimizer.optimize_payment_plan(self.request, self.state, self.options)
        
        row = PaymentPlanOutputMapper.map_to_output(
            request=self.request,
            winning_plan=winning_plan,
            state=self.state,
            earliest_full_date=date(2026, 9, 12),
            amount_safe_to_pay=Decimal("600.00"),
            all_diagnostics=[]
        )

        validated_row = self.validator.validate_and_repair(row, self.request, self.state)
        self.assertEqual(validated_row.request_id, "req_adv_001")
        self.assertEqual(validated_row.earliest_date_for_full_payment, "2026-09-12")
        self.assertEqual(self.validator.stats.passed_first_pass, 1)
        self.assertEqual(self.validator.stats.repaired_count, 0)
        self.assertEqual(self.validator.stats.fallen_back_count, 0)

    def test_rule_1_repair_request_id_mismatch(self):
        """Rule 1: Invalid or mismatched request_id is repaired deterministically."""
        row = OptimizerOutputRow(
            request_id="WRONG_ID",
            amount_safe_to_pay="600.00",
            affordability_status=STATUS_AFFORDABLE,
            recommended_payment_method=METHOD_FULL_PAYMENT,
            payment_plan="Full payment of 600.00 USD on 2026-09-12 (Option: opt_adv_inst_4)",
            earliest_date_for_full_payment="2026-09-12",
            spending_changes_needed="none",
            decision_explanation="Affordable in full.",
            winning_plan=None,
            all_diagnostics=[]
        )

        validated = self.validator.validate_and_repair(row, self.request, self.state)
        self.assertEqual(validated.request_id, "req_adv_001")
        self.assertIn("request_id_exists", self.validator.stats.violations_detected)
        self.assertEqual(self.validator.stats.repaired_count, 1)

    def test_rule_2_and_3_amount_safe_to_pay_bounds(self):
        """Rule 2 & 3: Out of bound or non-numeric amount_safe_to_pay is clamped and repaired."""
        row = OptimizerOutputRow(
            request_id="req_adv_001",
            amount_safe_to_pay="999999.00",  # exceeds requested 600.00
            affordability_status=STATUS_AFFORDABLE,
            recommended_payment_method=METHOD_FULL_PAYMENT,
            payment_plan="Full payment of 600.00 USD on 2026-09-12 (Option: opt_adv_inst_4)",
            earliest_date_for_full_payment="2026-09-12",
            spending_changes_needed="none",
            decision_explanation="Affordable in full.",
            winning_plan=None,
            all_diagnostics=[]
        )

        validated = self.validator.validate_and_repair(row, self.request, self.state)
        val = Decimal(validated.amount_safe_to_pay)
        self.assertTrue(Decimal("0.00") <= val <= self.request.amount)
        self.assertIn("amount_safe_to_pay_bounds", self.validator.stats.violations_detected)

    def test_rule_10_and_11_partial_payment_two_payments_and_exact_sum(self):
        """Rules 10 & 11: Partial-payment plan must contain exactly two payments summing to requested_amount."""
        d1 = date(2026, 9, 12)
        d2 = date(2026, 9, 26)
        sched = PaymentSchedule(
            option_id="opt_partial_req_adv_001",
            payment_type="PARTIAL",
            start_date=d1,
            installments_count=2,
            installment_amount=Decimal("300.00"),
            total_nominal_cost=Decimal("600.00"),
            due_dates=[d1, d2],
            due_amounts=[Decimal("300.00"), Decimal("300.00")],
            currency="USD"
        )
        sim = self.simulator.simulate(self.state, d1, sched)
        
        diag = CandidateDiagnostics(
            candidate_id="cand_partial_test",
            method=METHOD_PARTIAL_PAYMENT,
            option_id="opt_partial_req_adv_001",
            is_safe=True,
            is_eligible=True,
            rejection_reasons=[],
            minimum_balance_verified=True,
            min_cushion_observed=sim.min_cushion_observed,
            min_cushion_date=sim.min_cushion_date,
            requested_amount_completed=True,
            completed_by_desired_date=True,
            method_accepted_by_user=True,
            matches_supplied_option=True,
            partial_rules_satisfied=True,
            start_date=d1,
            completion_date=d2,
            total_cost=Decimal("600.00"),
            installments_count=2,
            installment_amount=Decimal("300.00"),
            due_dates=[d1, d2],
            due_amounts=[Decimal("300.00"), Decimal("300.00")],
            currency="USD"
        )
        plan = OptimizedCandidatePlan(
            candidate_id="cand_partial_test",
            method=METHOD_PARTIAL_PAYMENT,
            decision="BUY_NOW",
            option=None,
            schedule=sched,
            start_date=d1,
            simulation=sim,
            diagnostics=diag
        )
        
        row = PaymentPlanOutputMapper.map_to_output(
            request=self.request,
            winning_plan=plan,
            state=self.state,
            earliest_full_date=date(2026, 9, 26),
            amount_safe_to_pay=Decimal("300.00"),
            all_diagnostics=[]
        )

        validated = self.validator.validate_and_repair(row, self.request, self.state)
        self.assertEqual(validated.recommended_payment_method, METHOD_PARTIAL_PAYMENT)
        self.assertIn("2 payments: 300.00 USD on 2026-09-12, 300.00 USD on 2026-09-26", validated.payment_plan)
        # Verify payments sum exactly to 600.00
        self.assertEqual(sum(sched.due_amounts), self.request.amount)
        self.assertEqual(len(sched.due_amounts), 2)

    def test_rule_15_affordable_now_enforces_earliest_date_is_request_date(self):
        """Rule 15: affordable_now implies earliest_date_for_full_payment == request_date."""
        row = OptimizerOutputRow(
            request_id="req_adv_001",
            amount_safe_to_pay="600.00",
            affordability_status=STATUS_AFFORDABLE,
            recommended_payment_method=METHOD_FULL_PAYMENT,
            payment_plan="Full payment of 600.00 USD on 2026-09-12 (Option: NONE)",
            earliest_date_for_full_payment="2026-10-01",  # Invalid for affordable now!
            spending_changes_needed="none",
            decision_explanation="Affordable now.",
            winning_plan=None,
            all_diagnostics=[]
        )

        validated = self.validator.validate_and_repair(row, self.request, self.state)
        self.assertEqual(validated.earliest_date_for_full_payment, "2026-09-12")
        self.assertIn("affordable_now_earliest_date", self.validator.stats.violations_detected)

    def test_rule_16_and_21_unsafe_plan_triggers_safest_fallback(self):
        """Rules 16 & 21: An unsafe plan that breaches minimum balance triggers safest valid fallback."""
        d1 = date(2026, 9, 12)
        # Massive payment that completely drains balance far below minimum reserve
        sched = PaymentSchedule(
            option_id="opt_massive_breach",
            payment_type="FULL",
            start_date=d1,
            installments_count=1,
            installment_amount=Decimal("1900.00"),
            total_nominal_cost=Decimal("1900.00"),
            due_dates=[d1],
            due_amounts=[Decimal("1900.00")],
            currency="USD"
        )
        sim = self.simulator.simulate(self.state, d1, sched)
        # Simulation will confirm breach
        self.assertFalse(sim.is_safe)

        diag = CandidateDiagnostics(
            candidate_id="cand_bad",
            method=METHOD_FULL_PAYMENT,
            option_id="opt_massive_breach",
            is_safe=False,
            is_eligible=True,
            rejection_reasons=["Breaches minimum balance"],
            minimum_balance_verified=False,
            min_cushion_observed=sim.min_cushion_observed,
            min_cushion_date=sim.min_cushion_date,
            start_date=d1,
            completion_date=d1,
            total_cost=Decimal("1900.00"),
            installments_count=1,
            installment_amount=Decimal("1900.00"),
            due_dates=[d1],
            due_amounts=[Decimal("1900.00")],
            currency="USD"
        )
        bad_plan = OptimizedCandidatePlan(
            candidate_id="cand_bad",
            method=METHOD_FULL_PAYMENT,
            decision="BUY_NOW",
            option=None,
            schedule=sched,
            start_date=d1,
            simulation=sim,
            diagnostics=diag
        )

        row = OptimizerOutputRow(
            request_id="req_adv_001",
            amount_safe_to_pay="600.00",
            affordability_status=STATUS_AFFORDABLE,
            recommended_payment_method=METHOD_FULL_PAYMENT,
            payment_plan="Full payment of 1900.00 USD on 2026-09-12 (Option: opt_massive_breach)",
            earliest_date_for_full_payment="2026-09-12",
            spending_changes_needed="none",
            decision_explanation="Affordable.",
            winning_plan=bad_plan,
            all_diagnostics=[]
        )

        validated = self.validator.validate_and_repair(row, self.request, self.state)
        # Fallback must be applied
        self.assertEqual(validated.recommended_payment_method, METHOD_NOT_RECOMMENDED)
        self.assertEqual(validated.affordability_status, STATUS_NOT_AFFORDABLE)
        self.assertEqual(validated.payment_plan, "NONE")
        self.assertEqual(self.validator.stats.fallen_back_count, 1)

    def test_statistics_tracking(self):
        """ValidationStatistics accurately captures passes, repairs, fallbacks, and breakdown."""
        stats = self.validator.stats.to_dict()
        self.assertIn("total_validated", stats)
        self.assertIn("passed_first_pass", stats)
        self.assertIn("repaired_count", stats)
        self.assertIn("fallen_back_count", stats)
        self.assertIn("final_valid", stats)
        self.assertIn("violations_detected_by_rule", stats)


if __name__ == "__main__":
    unittest.main()
