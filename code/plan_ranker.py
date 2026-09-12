"""
Plan evaluator and ranking optimizer.
Selects optimal decision: BUY_NOW, WAIT, or DO_NOT_BUY.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple, Dict
from code.models import (
    Profile, PurchaseRequest, PaymentOption, CandidatePlan,
    PaymentSchedule, SimulationResult
)
from code.financial_state import ReconstructedFinancialState
from code.simulator import BalanceSimulator
from code.optimizer import (
    CandidatePaymentPlanOptimizer, OptimizedCandidatePlan, CandidateDiagnostics,
    METHOD_FULL_PAYMENT, METHOD_INSTALLMENTS, METHOD_WAIT, METHOD_PARTIAL_PAYMENT,
    METHOD_NOT_RECOMMENDED
)
from code.config import setup_logging

logger = setup_logging(__name__)

class PlanRanker:
    """
    PlanRanker delegating plan evaluation and ranking to the deterministic
    CandidatePaymentPlanOptimizer according to challenge specification.
    """
    def __init__(self, simulator: BalanceSimulator):
        self.simulator = simulator
        self.optimizer = CandidatePaymentPlanOptimizer(simulator)

    def evaluate_request(
        self,
        request: PurchaseRequest,
        state: ReconstructedFinancialState,
        options: List[PaymentOption]
    ) -> CandidatePlan:
        """
        Evaluates all candidate payment options using deterministic ranking.
        """
        optimized_plan = self.optimizer.optimize(request, state, options)
        
        # Convert OptimizedCandidatePlan to CandidatePlan for backward compatibility
        return CandidatePlan(
            decision=optimized_plan.decision,
            option=optimized_plan.option,
            schedule=optimized_plan.schedule,
            start_date=optimized_plan.start_date,
            simulation=optimized_plan.simulation,
            score=0.0,
            flexible_reduction_applied=optimized_plan.diagnostics.spending_reduction_pct,
            reason=optimized_plan.diagnostics.rejection_reasons[0] if (not optimized_plan.diagnostics.is_safe and optimized_plan.diagnostics.rejection_reasons) else ""
        )

    def evaluate_request_optimized(
        self,
        request: PurchaseRequest,
        state: ReconstructedFinancialState,
        options: List[PaymentOption]
    ) -> OptimizedCandidatePlan:
        """
        Returns the full OptimizedCandidatePlan with complete diagnostics.
        """
        return self.optimizer.optimize(request, state, options)

    def get_diagnostics(self, request_id: str) -> List[CandidateDiagnostics]:
        return self.optimizer.get_diagnostics_for_request(request_id)

