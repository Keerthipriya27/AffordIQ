"""
Unit and integration tests for CandidatePaymentPlanOptimizer and PaymentPlanOutputMapper.
"""
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from code.data_loader import DataLoader
from code.currency import CurrencyConverter
from code.financial_state import FinancialStateReconstructor, ReconstructedFinancialState
from code.simulator import BalanceSimulator
from code.optimizer import (
    CandidatePaymentPlanOptimizer,
    PaymentPlanOutputMapper,
    METHOD_FULL_PAYMENT,
    METHOD_PARTIAL_PAYMENT,
    METHOD_INSTALLMENTS,
    METHOD_WAIT,
    METHOD_NOT_RECOMMENDED,
)
from code.models import PurchaseRequest, PaymentOption, Profile

class TestCandidatePaymentPlanOptimizer(unittest.TestCase):
    def setUp(self):
        self.dataset_dir = Path("dataset")
        dl = DataLoader(self.dataset_dir)
        rates = dl.load_exchange_rates()
        self.converter = CurrencyConverter(rates)
        self.simulator = BalanceSimulator(self.converter)
        self.reconstructor = FinancialStateReconstructor(self.converter)
        self.optimizer = CandidatePaymentPlanOptimizer(self.simulator)

    def test_candidate_generation_methods(self):
        """Verifies that all 5 candidate methods are generated and evaluated."""
        profile = Profile(
            user_id="usr_test",
            base_currency="USD",
            current_balance=Decimal("2000.00"),
            minimum_balance_to_keep=Decimal("500.00"),
            monthly_essential_expenses=Decimal("1000.00"),
            monthly_flexible_expenses=Decimal("400.00"),
            payment_methods_user_will_consider=["FULL", "INSTALLMENTS", "DEFERRED"],
            risk_tolerance="moderate"
        )
        state = self.reconstructor.reconstruct(profile, [])
        req = PurchaseRequest(
            request_id="req_test_01",
            user_id="usr_test",
            request_date=date(2026, 9, 12),
            item_name="Laptop",
            amount=Decimal("600.00"),
            currency="USD",
            desired_completion_date=date(2026, 11, 30),
            allows_partial_payment=True,
            urgency="medium"
        )
        options = [
            PaymentOption("opt_full", "req_test_01", "FULL", 1, Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), 30, Decimal("1.00"), True, "USD"),
            PaymentOption("opt_bnpl", "req_test_01", "INSTALLMENTS", 4, Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), 14, Decimal("0.25"), True, "USD")
        ]

        candidates = self.optimizer.generate_all_candidates(req, state, options)
        methods = {c.method for c in candidates}
        
        self.assertIn(METHOD_FULL_PAYMENT, methods)
        self.assertIn(METHOD_INSTALLMENTS, methods)
        self.assertIn(METHOD_PARTIAL_PAYMENT, methods)
        self.assertIn(METHOD_WAIT, methods)
        self.assertIn(METHOD_NOT_RECOMMENDED, methods)

    def test_deterministic_ranking_tiebreaker(self):
        """Verifies that ranking strictly follows the 6-step criteria."""
        req = PurchaseRequest(
            request_id="req_test_02",
            user_id="usr_test",
            request_date=date(2026, 9, 12),
            item_name="Desk",
            amount=Decimal("300.00"),
            currency="USD",
            desired_completion_date=date(2026, 11, 30),
            allows_partial_payment=True,
            urgency="medium"
        )
        profile = Profile(
            user_id="usr_test",
            base_currency="USD",
            current_balance=Decimal("5000.00"),
            minimum_balance_to_keep=Decimal("500.00"),
            monthly_essential_expenses=Decimal("200.00"),
            monthly_flexible_expenses=Decimal("100.00"),
            payment_methods_user_will_consider=["FULL", "INSTALLMENTS"],
            risk_tolerance="moderate"
        )
        state = self.reconstructor.reconstruct(profile, [])
        
        # When both FULL and INSTALLMENTS are safe on request date with no spending changes and same cost:
        # Full payment uses 1 payment; installments uses 4 payments.
        # Criterion 5 (fewer payments) must prefer FULL payment over INSTALLMENTS.
        opt_full = PaymentOption("opt_full", "req_test_02", "FULL", 1, Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), 30, Decimal("1.00"), True, "USD")
        opt_bnpl = PaymentOption("opt_bnpl", "req_test_02", "INSTALLMENTS", 4, Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), 14, Decimal("0.25"), True, "USD")

        winning_plan = self.optimizer.optimize(req, state, [opt_full, opt_bnpl])
        self.assertEqual(winning_plan.method, METHOD_FULL_PAYMENT)
        self.assertEqual(winning_plan.diagnostics.installments_count, 1)

    def test_output_mapping_schema(self):
        """Verifies 8-field optimizer output row structure and values."""
        profile = Profile(
            user_id="usr_test",
            base_currency="USD",
            current_balance=Decimal("5000.00"),
            minimum_balance_to_keep=Decimal("500.00"),
            monthly_essential_expenses=Decimal("200.00"),
            monthly_flexible_expenses=Decimal("100.00"),
            payment_methods_user_will_consider=["FULL"],
            risk_tolerance="moderate"
        )
        state = self.reconstructor.reconstruct(profile, [])
        req = PurchaseRequest(
            request_id="req_test_03",
            user_id="usr_test",
            request_date=date(2026, 9, 12),
            item_name="Monitor",
            amount=Decimal("250.00"),
            currency="USD",
            desired_completion_date=date(2026, 11, 30),
            allows_partial_payment=True,
            urgency="medium"
        )
        opt_full = PaymentOption("opt_full", "req_test_03", "FULL", 1, Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), 30, Decimal("1.00"), True, "USD")
        winning_plan = self.optimizer.optimize(req, state, [opt_full])
        earliest_full = self.optimizer.find_earliest_date_for_full_payment(req, state)
        safe_amt = self.optimizer.calculate_amount_safe_to_pay(req, state, winning_plan)
        diags = self.optimizer.get_diagnostics_for_request(req.request_id)

        output = PaymentPlanOutputMapper.map_to_output(
            request=req,
            winning_plan=winning_plan,
            state=state,
            earliest_full_date=earliest_full,
            amount_safe_to_pay=safe_amt,
            all_diagnostics=diags
        )

        d = output.to_dict()
        required_keys = [
            "request_id", "amount_safe_to_pay", "affordability_status",
            "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment",
            "spending_changes_needed", "decision_explanation"
        ]
        for k in required_keys:
            self.assertIn(k, d)
            self.assertIsNotNone(d[k])

if __name__ == "__main__":
    unittest.main()
