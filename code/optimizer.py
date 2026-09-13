"""
Candidate Payment-Plan Optimizer and Output Mapper.
Generates, simulates, verifies, and deterministically ranks all legally eligible candidate plans.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Dict, Optional, Tuple, Any
import calendar

from code.models import (
    Profile, PurchaseRequest, PaymentOption, PaymentSchedule,
    SimulationResult, OutputRow
)
from code.financial_state import ReconstructedFinancialState
from code.simulator import BalanceSimulator
from code.plan_generator import PaymentPlanGenerator
from code.config import MAX_WAIT_SEARCH_DAYS, setup_logging

logger = setup_logging(__name__)

# Constants for candidate methods
METHOD_FULL_PAYMENT = "full_payment"
METHOD_PARTIAL_PAYMENT = "partial_payment"
METHOD_INSTALLMENTS = "installments"
METHOD_WAIT = "wait"
METHOD_NOT_RECOMMENDED = "not_recommended"

ALL_CANDIDATE_METHODS = [
    METHOD_FULL_PAYMENT,
    METHOD_PARTIAL_PAYMENT,
    METHOD_INSTALLMENTS,
    METHOD_WAIT,
    METHOD_NOT_RECOMMENDED
]

# Affordability status constants
STATUS_AFFORDABLE = "affordable"
STATUS_AFFORDABLE_WITH_DELAY = "affordable_with_delay"
STATUS_AFFORDABLE_WITH_SPENDING_CHANGES = "affordable_with_spending_changes"
STATUS_AFFORDABLE_WITH_DELAY_AND_SPENDING_CHANGES = "affordable_with_delay_and_spending_changes"
STATUS_PARTIALLY_AFFORDABLE = "partially_affordable"
STATUS_NOT_AFFORDABLE = "not_affordable"

ALLOWED_AFFORDABILITY_STATUSES = [
    STATUS_AFFORDABLE,
    STATUS_AFFORDABLE_WITH_DELAY,
    STATUS_AFFORDABLE_WITH_SPENDING_CHANGES,
    STATUS_AFFORDABLE_WITH_DELAY_AND_SPENDING_CHANGES,
    STATUS_PARTIALLY_AFFORDABLE,
    STATUS_NOT_AFFORDABLE,
]

ALLOWED_RECOMMENDED_METHODS = ALL_CANDIDATE_METHODS

OPTIMIZER_OUTPUT_HEADERS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation"
]


@dataclass
class CandidateDiagnostics:
    candidate_id: str
    method: str                           # full_payment, partial_payment, installments, wait, not_recommended
    option_id: Optional[str]
    is_safe: bool
    is_eligible: bool
    rejection_reasons: List[str] = field(default_factory=list)
    
    # Verification checks
    minimum_balance_verified: bool = True
    min_cushion_observed: Decimal = Decimal("0.00")
    min_cushion_date: Optional[date] = None
    failed_on_day: Optional[int] = None
    violation_amount: Decimal = Decimal("0.00")
    
    requested_amount_completed: bool = True
    completed_by_desired_date: bool = True
    method_accepted_by_user: bool = True
    matches_supplied_option: bool = True
    partial_rules_satisfied: bool = True
    spending_changes_affect_only_flexible: bool = True
    spending_changes_needed: bool = False
    spending_reduction_pct: Decimal = Decimal("0.00")
    
    # Schedule attributes
    start_date: date = field(default_factory=date.today)
    completion_date: date = field(default_factory=date.today)
    total_cost: Decimal = Decimal("0.00")
    installments_count: int = 1
    installment_amount: Decimal = Decimal("0.00")
    due_dates: List[date] = field(default_factory=list)
    due_amounts: List[Decimal] = field(default_factory=list)
    currency: str = "USD"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "method": self.method,
            "option_id": self.option_id,
            "is_safe": self.is_safe,
            "is_eligible": self.is_eligible,
            "rejection_reasons": self.rejection_reasons,
            "minimum_balance_verified": self.minimum_balance_verified,
            "min_cushion_observed": f"{self.min_cushion_observed:.2f}",
            "min_cushion_date": self.min_cushion_date.isoformat() if self.min_cushion_date else None,
            "failed_on_day": self.failed_on_day,
            "violation_amount": f"{self.violation_amount:.2f}",
            "requested_amount_completed": self.requested_amount_completed,
            "completed_by_desired_date": self.completed_by_desired_date,
            "method_accepted_by_user": self.method_accepted_by_user,
            "matches_supplied_option": self.matches_supplied_option,
            "partial_rules_satisfied": self.partial_rules_satisfied,
            "spending_changes_affect_only_flexible": self.spending_changes_affect_only_flexible,
            "spending_changes_needed": self.spending_changes_needed,
            "spending_reduction_pct": f"{self.spending_reduction_pct:.2f}",
            "start_date": self.start_date.isoformat(),
            "completion_date": self.completion_date.isoformat(),
            "total_cost": f"{self.total_cost:.2f}",
            "installments_count": self.installments_count,
            "installment_amount": f"{self.installment_amount:.2f}",
            "currency": self.currency
        }


@dataclass
class OptimizedCandidatePlan:
    candidate_id: str
    method: str                           # full_payment, partial_payment, installments, wait, not_recommended
    decision: str                         # BUY_NOW, WAIT, DO_NOT_BUY
    option: Optional[PaymentOption]
    schedule: Optional[PaymentSchedule]
    start_date: date
    simulation: SimulationResult
    diagnostics: CandidateDiagnostics
    score: float = 0.0
    ranking_tuple: Tuple = field(default_factory=tuple)


@dataclass
class OptimizerOutputRow:
    request_id: str
    amount_safe_to_pay: str
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: str
    spending_changes_needed: str
    decision_explanation: str
    
    # Internal references for diagnostics and legacy mapping
    winning_plan: Optional[OptimizedCandidatePlan] = None
    all_diagnostics: List[CandidateDiagnostics] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "amount_safe_to_pay": self.amount_safe_to_pay,
            "affordability_status": self.affordability_status,
            "recommended_payment_method": self.recommended_payment_method,
            "payment_plan": self.payment_plan,
            "earliest_date_for_full_payment": self.earliest_date_for_full_payment,
            "spending_changes_needed": self.spending_changes_needed,
            "decision_explanation": self.decision_explanation
        }

    def to_legacy_output_row(self) -> OutputRow:
        """
        Maps optimizer result to legacy OutputRow schema for compatibility with 10-header output.csv.
        """
        plan = self.winning_plan
        if not plan or plan.method == METHOD_NOT_RECOMMENDED or plan.decision == "DO_NOT_BUY":
            return OutputRow(
                request_id=self.request_id,
                decision="DO_NOT_BUY",
                recommended_option_id="NONE",
                payment_type="NONE",
                start_date=plan.start_date.isoformat() if plan else "2026-09-12",
                total_cost=Decimal("0.00"),
                installments_count=0,
                installment_amount=Decimal("0.00"),
                safety_cushion_min=plan.simulation.min_cushion_observed if plan else Decimal("0.00"),
                explanation=self.decision_explanation
            )
        
        legacy_decision = "WAIT" if plan.method == METHOD_WAIT else "BUY_NOW"
        rec_opt_id = plan.option.option_id if plan.option else f"opt_{self.request_id}"
        ptype = plan.schedule.payment_type if plan.schedule else "FULL"
        total_cost = plan.schedule.total_nominal_cost if plan.schedule else Decimal("0.00")
        inst_count = plan.schedule.installments_count if plan.schedule else 1
        inst_amt = plan.schedule.installment_amount if plan.schedule else total_cost

        if plan.method == METHOD_PARTIAL_PAYMENT and plan.schedule:
            inst_count = 2
            inst_amt = (total_cost / Decimal("2.00")).quantize(Decimal("0.01"))
        
        return OutputRow(
            request_id=self.request_id,
            decision=legacy_decision,
            recommended_option_id=rec_opt_id,
            payment_type=ptype,
            start_date=plan.start_date.isoformat(),
            total_cost=total_cost,
            installments_count=inst_count,
            installment_amount=inst_amt,
            safety_cushion_min=plan.simulation.min_cushion_observed,
            explanation=self.decision_explanation
        )


class CandidatePaymentPlanOptimizer:
    """
    Deterministic optimizer that generates all legally eligible candidate plans,
    runs exhaustive 90-day simulation & verification, and deterministically ranks
    them according to the challenge specification without any LLM intervention.
    """

    def __init__(self, simulator: BalanceSimulator):
        self.simulator = simulator
        self.diagnostics_store: Dict[str, List[CandidateDiagnostics]] = {}

    def _build_schedule(self, option: PaymentOption, request: PurchaseRequest, start_date: date) -> PaymentSchedule:
        return PaymentPlanGenerator.build_schedule(
            option, request.amount, start_date,
            amount_currency=request.currency,
            currency_converter=self.simulator.converter,
        )

    def optimize(
        self,
        request: PurchaseRequest,
        state: ReconstructedFinancialState,
        options: List[PaymentOption]
    ) -> OptimizedCandidatePlan:
        """
        Executes candidate generation, verification, and deterministic ranking for a single request.
        """
        self.diagnostics_store[request.request_id] = []
        
        # 1. Generate all candidate plans across the 5 possible methods
        candidates = self.generate_all_candidates(request, state, options)
        
        # Store diagnostics for inspection
        for cand in candidates:
            self.diagnostics_store[request.request_id].append(cand.diagnostics)
            
        # 2. Filter safe candidates
        safe_candidates = [c for c in candidates if c.diagnostics.is_safe and c.diagnostics.is_eligible]
        
        logger.debug(
            f"Request {request.request_id}: Generated {len(candidates)} total candidates, "
            f"{len(safe_candidates)} verified safe."
        )

        # 3. Deterministic Ranking
        if safe_candidates:
            # Sort safe candidates by deterministic ranking key
            ranked_safe = sorted(safe_candidates, key=self._candidate_ranking_key)
            winning_plan = ranked_safe[0]
            logger.info(
                f"Request {request.request_id}: Winning candidate {winning_plan.candidate_id} "
                f"[{winning_plan.method}] with option {winning_plan.option.option_id if winning_plan.option else 'NONE'}"
            )
            return winning_plan

        # 4. Fallback to not_recommended when no safe plan is found
        not_rec_candidates = [c for c in candidates if c.method == METHOD_NOT_RECOMMENDED]
        if not_rec_candidates:
            fallback = not_rec_candidates[0]
        else:
            fallback = self._create_not_recommended_candidate(request, state)
            
        logger.info(f"Request {request.request_id}: No safe candidate found. Recommended not_recommended.")
        return fallback

    optimize_payment_plan = optimize

    def generate_all_candidates(
        self,
        request: PurchaseRequest,
        state: ReconstructedFinancialState,
        options: List[PaymentOption]
    ) -> List[OptimizedCandidatePlan]:
        """
        Generates candidate plans for all 5 methods:
        - full_payment
        - partial_payment
        - installments
        - wait
        - not_recommended
        """
        profile = state.profile
        candidates: List[OptimizedCandidatePlan] = []
        
        # Payment options are dataset evidence; never synthesize one for a request.
        normalized_options = [
            opt for opt in options
            if (
                opt.currency.upper() == request.currency.upper()
                or self.simulator.converter.has_supplied_rate_on_date(
                    request.currency, opt.currency, request.request_date
                )
            )
            and PaymentPlanGenerator.is_option_eligible(opt, request, profile)
        ]

        # -------------------------------------------------------------
        # METHOD 1: full_payment (Immediate lump-sum on request_date)
        # -------------------------------------------------------------
        full_options = [opt for opt in normalized_options if opt.payment_type.upper() == "FULL"]

        for opt in full_options:
            # Candidate 1A: Full payment without spending changes
            cand_id = f"cand_full_{opt.option_id}_no_austerity"
            schedule = self._build_schedule(opt, request, request.request_date)
            plan = self._evaluate_candidate(
                candidate_id=cand_id,
                method=METHOD_FULL_PAYMENT,
                decision="BUY_NOW",
                option=opt,
                schedule=schedule,
                start_date=request.request_date,
                request=request,
                state=state,
                spending_reduction_pct=Decimal("0.00")
            )
            candidates.append(plan)

            # Candidate 1B: Full payment with flexible spending reduction (if profile allows)
            if profile.flexible_reduction_limit > 0:
                cand_id_aust = f"cand_full_{opt.option_id}_austerity"
                plan_aust = self._evaluate_candidate(
                    candidate_id=cand_id_aust,
                    method=METHOD_FULL_PAYMENT,
                    decision="BUY_NOW",
                    option=opt,
                    schedule=schedule,
                    start_date=request.request_date,
                    request=request,
                    state=state,
                    spending_reduction_pct=profile.flexible_reduction_limit
                )
                candidates.append(plan_aust)

        # -------------------------------------------------------------
        # METHOD 2: installments (Immediate multi-payment on request_date)
        # -------------------------------------------------------------
        inst_options = [
            opt for opt in normalized_options
            if opt.payment_type.upper() in ["INSTALLMENTS", "FINANCING", "DEFERRED"] or opt.installments_count > 1
        ]
        for opt in inst_options:
            schedule = self._build_schedule(opt, request, request.request_date)
            
            # Candidate 2A: Installments without spending changes
            cand_id = f"cand_inst_{opt.option_id}_no_austerity"
            plan = self._evaluate_candidate(
                candidate_id=cand_id,
                method=METHOD_INSTALLMENTS,
                decision="BUY_NOW",
                option=opt,
                schedule=schedule,
                start_date=request.request_date,
                request=request,
                state=state,
                spending_reduction_pct=Decimal("0.00")
            )
            candidates.append(plan)

            # Candidate 2B: Installments with flexible spending reduction
            if profile.flexible_reduction_limit > 0:
                cand_id_aust = f"cand_inst_{opt.option_id}_austerity"
                plan_aust = self._evaluate_candidate(
                    candidate_id=cand_id_aust,
                    method=METHOD_INSTALLMENTS,
                    decision="BUY_NOW",
                    option=opt,
                    schedule=schedule,
                    start_date=request.request_date,
                    request=request,
                    state=state,
                    spending_reduction_pct=profile.flexible_reduction_limit
                )
                candidates.append(plan_aust)

        # -------------------------------------------------------------
        # METHOD 3: partial_payment
        # -------------------------------------------------------------
        # Generates partial payment candidates when allows_partial_payment is true
        if request.allows_partial_payment:
            # Check maximum safe lump sum right now
            baseline_sim = self.simulator.simulate(state, request.request_date, None)
            headroom = baseline_sim.min_cushion_observed - profile.minimum_balance_to_keep
            safe_upfront = max(Decimal("0.00"), min(request.amount, headroom.quantize(Decimal("0.01"))))
            
            # Generate single partial payment candidate (pays safe upfront portion)
            single_partial_cand = self._generate_pure_partial_candidate(
                request, state, safe_upfront, profile
            )
            candidates.append(single_partial_cand)
        else:
            # Record an explicitly ineligible partial payment diagnostic for inspection
            ineligible_partial = self._create_ineligible_partial_candidate(request, state)
            candidates.append(ineligible_partial)

        # -------------------------------------------------------------
        # METHOD 4: wait (Delayed execution to future payday / liquid date)
        # -------------------------------------------------------------
        # Test eligible payment options across wait search window
        wait_options = normalized_options
        
        # Collect key cashflow dates (e.g. salary inflows) to test specifically, plus standard range
        inflow_dates = self._find_upcoming_inflow_dates(state, request.request_date, MAX_WAIT_SEARCH_DAYS)
        test_delay_days = sorted(list(set(
            [1, 2, 3, 5, 7, 10, 14, 21, 28, 30, 40] +
            [(d - request.request_date).days for d in inflow_dates if 0 < (d - request.request_date).days <= MAX_WAIT_SEARCH_DAYS]
        )))

        for delay_days in test_delay_days:
            delayed_date = request.request_date + timedelta(days=delay_days)
            if request.desired_completion_date and delayed_date > request.desired_completion_date:
                continue

            for opt in wait_options:
                schedule = self._build_schedule(opt, request, delayed_date)
                
                # Check desired completion date constraint
                if request.desired_completion_date and schedule.due_dates[-1] > request.desired_completion_date:
                    continue

                # Candidate 4A: Wait without spending changes
                cand_id = f"cand_wait_{delay_days}d_{opt.option_id}_no_austerity"
                plan = self._evaluate_candidate(
                    candidate_id=cand_id,
                    method=METHOD_WAIT,
                    decision="WAIT",
                    option=opt,
                    schedule=schedule,
                    start_date=delayed_date,
                    request=request,
                    state=state,
                    spending_reduction_pct=Decimal("0.00")
                )
                candidates.append(plan)

                # Candidate 4B: Wait with flexible spending reduction
                if profile.flexible_reduction_limit > 0:
                    cand_id_aust = f"cand_wait_{delay_days}d_{opt.option_id}_austerity"
                    plan_aust = self._evaluate_candidate(
                        candidate_id=cand_id_aust,
                        method=METHOD_WAIT,
                        decision="WAIT",
                        option=opt,
                        schedule=schedule,
                        start_date=delayed_date,
                        request=request,
                        state=state,
                        spending_reduction_pct=profile.flexible_reduction_limit
                    )
                    candidates.append(plan_aust)

        # -------------------------------------------------------------
        # METHOD 5: not_recommended (Zero purchase fallback)
        # -------------------------------------------------------------
        not_rec_cand = self._create_not_recommended_candidate(request, state)
        candidates.append(not_rec_cand)

        return candidates

    def _evaluate_candidate(
        self,
        candidate_id: str,
        method: str,
        decision: str,
        option: Optional[PaymentOption],
        schedule: Optional[PaymentSchedule],
        start_date: date,
        request: PurchaseRequest,
        state: ReconstructedFinancialState,
        spending_reduction_pct: Decimal = Decimal("0.00")
    ) -> OptimizedCandidatePlan:
        """
        Simulates and deterministically verifies all challenge invariants for a candidate plan.
        """
        profile = state.profile
        rejection_reasons: List[str] = []
        is_eligible = True
        
        # 1. Verify payment method is accepted by the user
        method_accepted = True
        if option:
            accepted_methods = [m.upper() for m in profile.payment_methods_user_will_consider]
            if option.payment_type.upper() not in accepted_methods:
                method_accepted = False
                is_eligible = False
                rejection_reasons.append(
                    f"Payment method '{option.payment_type}' is not accepted by user "
                    f"(user accepts: {profile.payment_methods_user_will_consider})"
                )

        # 2. Verify partial payment / installment rules
        partial_rules_satisfied = True
        if schedule and schedule.installments_count > 1:
            if not request.allows_partial_payment:
                partial_rules_satisfied = False
                is_eligible = False
                rejection_reasons.append("Request specifies allows_partial_payment=false; multi-installment schedule disallowed")
        if option and not option.allows_partial_payment and schedule and schedule.installments_count > 1:
            partial_rules_satisfied = False
            is_eligible = False
            rejection_reasons.append(f"Option {option.option_id} specifies allows_partial_payment=false")

        # 3. Verify installment schedule matches supplied payment option
        matches_supplied = True
        if option and schedule:
            if schedule.installments_count != max(1, option.installments_count):
                matches_supplied = False
                rejection_reasons.append("Schedule installments_count does not match option specification")

        # 4. Verify completion by desired_completion_date
        completed_by_desired_date = True
        completion_date = schedule.due_dates[-1] if schedule else start_date
        if request.desired_completion_date and completion_date > request.desired_completion_date:
            completed_by_desired_date = False
            rejection_reasons.append(
                f"Schedule completion date {completion_date.isoformat()} exceeds "
                f"desired_completion_date {request.desired_completion_date.isoformat()}"
            )

        # 5. Verify requested amount is fully completed
        requested_amount_completed = True
        if schedule:
            sum_due = sum(schedule.due_amounts)
            if abs(sum_due - schedule.total_nominal_cost) > Decimal("0.05"):
                requested_amount_completed = False
                rejection_reasons.append("Sum of installment payments does not equal total cost")
        else:
            requested_amount_completed = False

        # 6. Verify spending changes only affect flexible recurring expenses
        spending_changes_only_flexible = True
        spending_needed = spending_reduction_pct > Decimal("0.00")
        if spending_needed and spending_reduction_pct > profile.flexible_reduction_limit:
            spending_changes_only_flexible = False
            rejection_reasons.append(
                f"Spending reduction {spending_reduction_pct * 100}% exceeds profile limit {profile.flexible_reduction_limit * 100}%"
            )

        # 7. Simulate complete payment schedule over 90-day financial state
        sim = self.simulator.simulate(
            state=state,
            request_date=request.request_date,
            plan_schedule=schedule,
            flexible_reduction_pct=spending_reduction_pct
        )

        # 8. Verify minimum balance on every relevant date
        min_bal_verified = sim.is_safe
        if not sim.is_safe:
            rejection_reasons.append(
                f"Breaches minimum balance {profile.minimum_balance_to_keep:.2f} {profile.base_currency} "
                f"on day {sim.failed_on_day} (shortfall: {sim.violation_amount:.2f} {profile.base_currency})"
            )

        # Overall safety invariant
        is_safe = is_eligible and min_bal_verified

        diagnostics = CandidateDiagnostics(
            candidate_id=candidate_id,
            method=method,
            option_id=option.option_id if option else None,
            is_safe=is_safe,
            is_eligible=is_eligible,
            rejection_reasons=rejection_reasons,
            minimum_balance_verified=min_bal_verified,
            min_cushion_observed=sim.min_cushion_observed,
            min_cushion_date=sim.min_cushion_date,
            failed_on_day=sim.failed_on_day,
            violation_amount=sim.violation_amount,
            requested_amount_completed=requested_amount_completed,
            completed_by_desired_date=completed_by_desired_date,
            method_accepted_by_user=method_accepted,
            matches_supplied_option=matches_supplied,
            partial_rules_satisfied=partial_rules_satisfied,
            spending_changes_affect_only_flexible=spending_changes_only_flexible,
            spending_changes_needed=spending_needed,
            spending_reduction_pct=spending_reduction_pct,
            start_date=start_date,
            completion_date=completion_date,
            total_cost=schedule.total_nominal_cost if schedule else Decimal("0.00"),
            installments_count=schedule.installments_count if schedule else 0,
            installment_amount=schedule.installment_amount if schedule else Decimal("0.00"),
            due_dates=schedule.due_dates if schedule else [],
            due_amounts=schedule.due_amounts if schedule else [],
            currency=schedule.currency if schedule else request.currency
        )

        plan = OptimizedCandidatePlan(
            candidate_id=candidate_id,
            method=method,
            decision=decision,
            option=option,
            schedule=schedule,
            start_date=start_date,
            simulation=sim,
            diagnostics=diagnostics
        )
        plan.ranking_tuple = self._candidate_ranking_key(plan)
        return plan

    def _candidate_ranking_key(self, plan: OptimizedCandidatePlan) -> Tuple:
        """
        Deterministic ranking key strictly matching the challenge specification:
        1. complete the full request by desired_completion_date (0=yes, 1=no)
        2. require no spending changes (0=yes, 1=no)
        3. minimize total amount paid (lowest total_nominal_cost)
        4. start payment earlier (earlier start_date)
        5. use fewer payments (fewer installments_count)
        6. lowest payment_option_id as final tie-breaker (lexicographical string)
        """
        d = plan.diagnostics
        
        # Criterion 1: complete the full request by desired_completion_date
        completes_by_desired = 0 if (d.requested_amount_completed and d.completed_by_desired_date) else 1
        
        # Criterion 2: require no spending changes
        no_spending_changes = 0 if not d.spending_changes_needed else 1
        
        # Criterion 3: minimize total amount paid
        total_paid = d.total_cost
        
        # Criterion 4: start payment earlier
        start_d = d.start_date
        
        # Criterion 5: use fewer payments
        payment_count = d.installments_count
        
        # Criterion 6: lowest payment_option_id as final tie-breaker
        opt_id = d.option_id if d.option_id else "zzz_none"
        
        return (completes_by_desired, no_spending_changes, total_paid, start_d, payment_count, opt_id)

    def find_earliest_date_for_full_payment(
        self,
        request: PurchaseRequest,
        state: ReconstructedFinancialState
    ) -> Optional[date]:
        """
        Determines the earliest calendar date on which the full requested amount
        can be paid in a single lump sum without breaching minimum balance over 90 days.
        """
        profile = state.profile
        default_full_opt = self._create_default_full_option(request)

        for delay_days in range(MAX_WAIT_SEARCH_DAYS + 1):
            test_date = request.request_date + timedelta(days=delay_days)
            schedule = self._build_schedule(default_full_opt, request, test_date)
            sim = self.simulator.simulate(state, request.request_date, schedule)
            if sim.is_safe:
                return test_date

        return None

    def calculate_amount_safe_to_pay(
        self,
        request: PurchaseRequest,
        state: ReconstructedFinancialState,
        winning_plan: OptimizedCandidatePlan
    ) -> Decimal:
        """
        Calculates the amount safe to pay for this purchase request.
        """
        profile = state.profile
        
        # If an approved plan completes the full purchase, the full amount is safe
        if winning_plan.diagnostics.is_safe and winning_plan.diagnostics.requested_amount_completed:
            return request.amount

        # If a partial payment is recommended, return the safe partial cost
        if winning_plan.method == METHOD_PARTIAL_PAYMENT and winning_plan.diagnostics.is_safe:
            return winning_plan.diagnostics.total_cost

        # Otherwise calculate maximum safe lump sum on request_date based on 90-day minimum cushion
        baseline_sim = self.simulator.simulate(state, request.request_date, None)
        headroom = baseline_sim.min_cushion_observed - profile.minimum_balance_to_keep
        if headroom > Decimal("0.00"):
            return min(request.amount, headroom.quantize(Decimal("0.01")))
        return Decimal("0.00")

    def get_diagnostics_for_request(self, request_id: str) -> List[CandidateDiagnostics]:
        return self.diagnostics_store.get(request_id, [])

    def get_all_diagnostics(self) -> Dict[str, List[CandidateDiagnostics]]:
        return self.diagnostics_store

    # -------------------------------------------------------------------------
    # Helper candidate generators & fallback handlers
    # -------------------------------------------------------------------------
    def _create_default_full_option(self, request: PurchaseRequest) -> PaymentOption:
        import re
        base_opt_id = re.sub(r'^(?:s_)?req_', 'opt_', request.request_id)
        return PaymentOption(
            option_id=base_opt_id,
            request_id=request.request_id,
            payment_type="FULL",
            installments_count=1,
            interest_rate_apr=Decimal("0.00"),
            fee_fixed=Decimal("0.00"),
            fee_percentage=Decimal("0.00"),
            interval_days=30,
            initial_deposit_pct=Decimal("1.00"),
            allows_partial_payment=True,
            currency=request.currency
        )

    def _create_default_bnpl_option(self, request: PurchaseRequest) -> PaymentOption:
        import re
        base_opt_id = re.sub(r'^(?:s_)?req_', 'opt_', request.request_id)
        return PaymentOption(
            option_id=base_opt_id,
            request_id=request.request_id,
            payment_type="INSTALLMENTS",
            installments_count=4,
            interest_rate_apr=Decimal("0.00"),
            fee_fixed=Decimal("0.00"),
            fee_percentage=Decimal("0.00"),
            interval_days=14,
            initial_deposit_pct=Decimal("0.25"),
            allows_partial_payment=True,
            currency=request.currency
        )

    def _normalize_options(
        self,
        options: List[PaymentOption],
        request: PurchaseRequest
    ) -> List[PaymentOption]:
        """
        Ensures at least default FULL and BNPL options exist if options list is empty.
        """
        if options:
            return options
        
        opts = [self._create_default_full_option(request)]
        if request.allows_partial_payment:
            opts.append(self._create_default_bnpl_option(request))
        return opts

    def _create_not_recommended_candidate(
        self,
        request: PurchaseRequest,
        state: ReconstructedFinancialState
    ) -> OptimizedCandidatePlan:
        baseline_sim = self.simulator.simulate(state, request.request_date, None)
        profile = state.profile
        
        rejection_reasons = []
        if baseline_sim.min_cushion_observed < profile.minimum_balance_to_keep:
            rejection_reasons.append(
                f"Existing projected cashflow breaches {profile.minimum_balance_to_keep:.2f} {profile.base_currency} "
                f"safety reserve even without any purchase."
            )
        else:
            rejection_reasons.append("Exceeds safe budget across all evaluated candidate plans over 90 days.")

        diagnostics = CandidateDiagnostics(
            candidate_id="cand_not_recommended",
            method=METHOD_NOT_RECOMMENDED,
            option_id=None,
            is_safe=True,  # zero outflow is safe in itself
            is_eligible=True,
            rejection_reasons=rejection_reasons,
            minimum_balance_verified=baseline_sim.is_safe,
            min_cushion_observed=baseline_sim.min_cushion_observed,
            min_cushion_date=baseline_sim.min_cushion_date,
            failed_on_day=baseline_sim.failed_on_day,
            violation_amount=baseline_sim.violation_amount,
            requested_amount_completed=False,
            completed_by_desired_date=False,
            method_accepted_by_user=True,
            matches_supplied_option=True,
            partial_rules_satisfied=True,
            spending_changes_affect_only_flexible=True,
            spending_changes_needed=False,
            spending_reduction_pct=Decimal("0.00"),
            start_date=request.request_date,
            completion_date=request.request_date,
            total_cost=Decimal("0.00"),
            installments_count=0,
            installment_amount=Decimal("0.00"),
            due_dates=[],
            due_amounts=[],
            currency=request.currency
        )

        plan = OptimizedCandidatePlan(
            candidate_id="cand_not_recommended",
            method=METHOD_NOT_RECOMMENDED,
            decision="DO_NOT_BUY",
            option=None,
            schedule=None,
            start_date=request.request_date,
            simulation=baseline_sim,
            diagnostics=diagnostics
        )
        plan.ranking_tuple = self._candidate_ranking_key(plan)
        return plan

    def _create_ineligible_partial_candidate(
        self,
        request: PurchaseRequest,
        state: ReconstructedFinancialState
    ) -> OptimizedCandidatePlan:
        baseline_sim = self.simulator.simulate(state, request.request_date, None)
        diagnostics = CandidateDiagnostics(
            candidate_id="cand_partial_ineligible",
            method=METHOD_PARTIAL_PAYMENT,
            option_id=None,
            is_safe=False,
            is_eligible=False,
            rejection_reasons=["Request specifies allows_partial_payment=false"],
            minimum_balance_verified=True,
            min_cushion_observed=baseline_sim.min_cushion_observed,
            min_cushion_date=baseline_sim.min_cushion_date,
            requested_amount_completed=False,
            completed_by_desired_date=False,
            method_accepted_by_user=True,
            matches_supplied_option=True,
            partial_rules_satisfied=False,
            start_date=request.request_date,
            completion_date=request.request_date,
            total_cost=Decimal("0.00"),
            installments_count=0,
            installment_amount=Decimal("0.00"),
            currency=request.currency
        )
        plan = OptimizedCandidatePlan(
            candidate_id="cand_partial_ineligible",
            method=METHOD_PARTIAL_PAYMENT,
            decision="DO_NOT_BUY",
            option=None,
            schedule=None,
            start_date=request.request_date,
            simulation=baseline_sim,
            diagnostics=diagnostics
        )
        plan.ranking_tuple = self._candidate_ranking_key(plan)
        return plan

    def _generate_pure_partial_candidate(
        self,
        request: PurchaseRequest,
        state: ReconstructedFinancialState,
        safe_amount: Decimal,
        profile: Profile
    ) -> OptimizedCandidatePlan:
        """
        Evaluates a partial payment with exactly two payments summing to the requested amount.
        Payment 1: on request_date with safe upfront amount (or half if safe_amount >= requested).
        Payment 2: on subsequent date (e.g. next payday / completion date) with remainder.
        """
        cand_id = "cand_partial_two_payments"
        if safe_amount <= Decimal("0.00") or not request.allows_partial_payment:
            return self._create_ineligible_partial_candidate(request, state)

        # Payment 1 is the safe upfront portion (clamped to at most request.amount - 1.00 if safe_amount is large)
        if safe_amount >= request.amount:
            p1 = (request.amount / Decimal("2.00")).quantize(Decimal("0.01"))
        else:
            p1 = safe_amount.quantize(Decimal("0.01"))
        
        p2 = (request.amount - p1).quantize(Decimal("0.01"))

        # Find second date: test upcoming inflows or 14/21/30 days
        inflow_dates = self._find_upcoming_inflow_dates(state, request.request_date, 60)
        potential_dates = [d for d in inflow_dates if d > request.request_date]
        if not potential_dates:
            potential_dates = [
                request.request_date + timedelta(days=14),
                request.request_date + timedelta(days=21),
                request.request_date + timedelta(days=30),
                request.desired_completion_date
            ]
        
        # Select best second date where simulation is safe
        best_d2 = None
        best_sim = None
        
        for d2 in potential_dates:
            if d2 <= request.request_date:
                continue
            sched = PaymentSchedule(
                option_id=f"opt_partial_{request.request_id}",
                payment_type="PARTIAL",
                start_date=request.request_date,
                installments_count=2,
                installment_amount=p1,
                total_nominal_cost=request.amount,
                due_dates=[request.request_date, d2],
                due_amounts=[p1, p2],
                currency=request.currency
            )
            sim = self.simulator.simulate(state, request.request_date, sched)
            if sim.is_safe:
                best_d2 = d2
                best_sim = sim
                break
        
        # If no safe second date found, default to first potential date or desired_completion_date
        if not best_d2:
            best_d2 = potential_dates[-1]
            if best_d2 <= request.request_date:
                best_d2 = request.request_date + timedelta(days=30)
            sched = PaymentSchedule(
                option_id=f"opt_partial_{request.request_id}",
                payment_type="PARTIAL",
                start_date=request.request_date,
                installments_count=2,
                installment_amount=p1,
                total_nominal_cost=request.amount,
                due_dates=[request.request_date, best_d2],
                due_amounts=[p1, p2],
                currency=request.currency
            )
            best_sim = self.simulator.simulate(state, request.request_date, sched)
        else:
            sched = PaymentSchedule(
                option_id=f"opt_partial_{request.request_id}",
                payment_type="PARTIAL",
                start_date=request.request_date,
                installments_count=2,
                installment_amount=p1,
                total_nominal_cost=request.amount,
                due_dates=[request.request_date, best_d2],
                due_amounts=[p1, p2],
                currency=request.currency
            )

        is_safe = best_sim.is_safe and request.allows_partial_payment
        rejection_reasons = []
        if not is_safe:
            rejection_reasons.append("Two-payment partial plan breaches minimum balance")
        if best_d2 > request.desired_completion_date:
            rejection_reasons.append(f"Partial plan completion date {best_d2} exceeds desired date {request.desired_completion_date}")

        diagnostics = CandidateDiagnostics(
            candidate_id=cand_id,
            method=METHOD_PARTIAL_PAYMENT,
            option_id=f"opt_partial_{request.request_id}",
            is_safe=is_safe,
            is_eligible=request.allows_partial_payment,
            rejection_reasons=rejection_reasons,
            minimum_balance_verified=best_sim.is_safe,
            min_cushion_observed=best_sim.min_cushion_observed,
            min_cushion_date=best_sim.min_cushion_date,
            failed_on_day=best_sim.failed_on_day,
            violation_amount=best_sim.violation_amount,
            requested_amount_completed=True,
            completed_by_desired_date=(best_d2 <= request.desired_completion_date),
            method_accepted_by_user=True,
            matches_supplied_option=True,
            partial_rules_satisfied=request.allows_partial_payment,
            spending_changes_affect_only_flexible=True,
            spending_changes_needed=False,
            spending_reduction_pct=Decimal("0.00"),
            start_date=request.request_date,
            completion_date=best_d2,
            total_cost=request.amount,
            installments_count=2,
            installment_amount=p1,
            due_dates=[request.request_date, best_d2],
            due_amounts=[p1, p2],
            currency=request.currency
        )

        plan = OptimizedCandidatePlan(
            candidate_id=cand_id,
            method=METHOD_PARTIAL_PAYMENT,
            decision="BUY_NOW" if is_safe else "DO_NOT_BUY",
            option=None,
            schedule=sched,
            start_date=request.request_date,
            simulation=best_sim,
            diagnostics=diagnostics
        )
        plan.ranking_tuple = self._candidate_ranking_key(plan)
        return plan

    def _find_upcoming_inflow_dates(
        self,
        state: ReconstructedFinancialState,
        start_date: date,
        horizon_days: int
    ) -> List[date]:
        """
        Locates calendar dates of recurring and confirmed cash inflows (e.g. salary) within horizon.
        """
        from code.simulator import is_event_active_on_date
        inflow_dates: List[date] = []
        for day_offset in range(1, horizon_days + 1):
            target_d = start_date + timedelta(days=day_offset)
            for ev in state.active_inflows:
                if is_event_active_on_date(ev, target_d):
                    inflow_dates.append(target_d)
                    break
        return inflow_dates


class PaymentPlanOutputMapper:
    """
    Final output mapper converting optimization results and diagnostics to the
    specification schema with 8 standardized fields.
    """

    @staticmethod
    def map_to_output(
        request: PurchaseRequest,
        winning_plan: OptimizedCandidatePlan,
        state: ReconstructedFinancialState,
        earliest_full_date: Optional[date],
        amount_safe_to_pay: Decimal,
        all_diagnostics: List[CandidateDiagnostics]
    ) -> OptimizerOutputRow:
        profile = state.profile
        method = winning_plan.method
        d = winning_plan.diagnostics
        curr = request.currency
        base_curr = profile.base_currency

        # 1. request_id
        req_id = request.request_id

        # 2. amount_safe_to_pay
        amount_safe_str = f"{amount_safe_to_pay:.2f}"

        # 3. affordability_status
        if method in [METHOD_FULL_PAYMENT, METHOD_INSTALLMENTS]:
            if d.spending_changes_needed:
                affordability_status = STATUS_AFFORDABLE_WITH_SPENDING_CHANGES
            else:
                affordability_status = STATUS_AFFORDABLE
        elif method == METHOD_WAIT:
            if d.spending_changes_needed:
                affordability_status = STATUS_AFFORDABLE_WITH_DELAY_AND_SPENDING_CHANGES
            else:
                affordability_status = STATUS_AFFORDABLE_WITH_DELAY
        elif method == METHOD_PARTIAL_PAYMENT:
            affordability_status = STATUS_PARTIALLY_AFFORDABLE
        else:
            affordability_status = STATUS_NOT_AFFORDABLE

        # 4. recommended_payment_method
        rec_method = method

        # 5. payment_plan description
        if method == METHOD_NOT_RECOMMENDED or not winning_plan.schedule:
            payment_plan_desc = "NONE"
        elif method == METHOD_PARTIAL_PAYMENT and len(winning_plan.schedule.due_amounts) == 2:
            p1 = winning_plan.schedule.due_amounts[0]
            p2 = winning_plan.schedule.due_amounts[1]
            d1 = winning_plan.schedule.due_dates[0]
            d2 = winning_plan.schedule.due_dates[1]
            payment_plan_desc = (
                f"2 payments: {p1:.2f} {curr} on {d1.isoformat()}, "
                f"{p2:.2f} {curr} on {d2.isoformat()} (Total: {winning_plan.schedule.total_nominal_cost:.2f} {curr}, Option: NONE)"
            )
        elif winning_plan.schedule.installments_count == 1:
            payment_plan_desc = (
                f"Full payment of {winning_plan.schedule.total_nominal_cost:.2f} {curr} on "
                f"{winning_plan.start_date.isoformat()} (Option: {winning_plan.option.option_id if winning_plan.option else 'NONE'})"
            )
        else:
            payment_plan_desc = (
                f"{winning_plan.schedule.installments_count} installments of "
                f"{winning_plan.schedule.installment_amount:.2f} {curr} starting "
                f"{winning_plan.start_date.isoformat()} (Total: {winning_plan.schedule.total_nominal_cost:.2f} {curr}, "
                f"Option: {winning_plan.option.option_id if winning_plan.option else 'NONE'})"
            )

        # 6. earliest_date_for_full_payment
        if affordability_status in [STATUS_AFFORDABLE, STATUS_AFFORDABLE_WITH_SPENDING_CHANGES, "affordable_now"] or (method == METHOD_FULL_PAYMENT and not d.spending_changes_needed and winning_plan.start_date == request.request_date):
            earliest_full_str = request.request_date.isoformat()
        elif earliest_full_date:
            earliest_full_str = earliest_full_date.isoformat()
        else:
            earliest_full_str = "NONE"

        # 7. spending_changes_needed
        if d.spending_changes_needed:
            pct_int = int(d.spending_reduction_pct * Decimal("100.0"))
            spending_changes_str = f"reduce_flexible_expenses_by_{pct_int}%"
        else:
            spending_changes_str = "none"

        # 8. decision_explanation
        explanation = PaymentPlanOutputMapper._build_decision_explanation(
            winning_plan=winning_plan,
            request=request,
            profile=profile,
            earliest_full_date=earliest_full_date,
            amount_safe_to_pay=amount_safe_to_pay
        )

        return OptimizerOutputRow(
            request_id=req_id,
            amount_safe_to_pay=amount_safe_str,
            affordability_status=affordability_status,
            recommended_payment_method=rec_method,
            payment_plan=payment_plan_desc,
            earliest_date_for_full_payment=earliest_full_str,
            spending_changes_needed=spending_changes_str,
            decision_explanation=explanation,
            winning_plan=winning_plan,
            all_diagnostics=all_diagnostics
        )

    @staticmethod
    def _build_decision_explanation(
        winning_plan: OptimizedCandidatePlan,
        request: PurchaseRequest,
        profile: Profile,
        earliest_full_date: Optional[date],
        amount_safe_to_pay: Decimal
    ) -> str:
        curr = profile.base_currency
        cushion = winning_plan.simulation.min_cushion_observed
        min_keep = profile.minimum_balance_to_keep
        method = winning_plan.method
        sched = winning_plan.schedule

        if method == METHOD_FULL_PAYMENT:
            if winning_plan.diagnostics.spending_changes_needed:
                explanation = (
                    f"Affordable in full ({sched.total_nominal_cost:.2f} {request.currency}) by reducing flexible "
                    f"expenses by {int(winning_plan.diagnostics.spending_reduction_pct * 100)}%. "
                    f"Lowest 90-day balance is {cushion:.2f} {curr}, exceeding your {min_keep:.2f} {curr} reserve."
                )
            else:
                explanation = (
                    f"Affordable in full ({sched.total_nominal_cost:.2f} {request.currency}). "
                    f"Lowest 90-day balance is {cushion:.2f} {curr}, exceeding your {min_keep:.2f} {curr} reserve."
                )

        elif method == METHOD_INSTALLMENTS:
            if winning_plan.diagnostics.spending_changes_needed:
                explanation = (
                    f"Affordable via {sched.installments_count} installments of {sched.installment_amount:.2f} {request.currency} "
                    f"with {int(winning_plan.diagnostics.spending_reduction_pct * 100)}% flexible budget austerity. "
                    f"Lowest 90-day balance is {cushion:.2f} {curr}."
                )
            else:
                explanation = (
                    f"Affordable via {sched.installments_count} installments of {sched.installment_amount:.2f} {request.currency}. "
                    f"Lowest 90-day balance is {cushion:.2f} {curr}, exceeding your {min_keep:.2f} {curr} reserve."
                )

        elif method == METHOD_WAIT:
            days_wait = (winning_plan.start_date - request.request_date).days
            explanation = (
                f"Wait {days_wait} days until {winning_plan.start_date.isoformat()} after scheduled cash inflow. "
                f"Maintains a safe minimum cushion of {cushion:.2f} {curr} above your reserve."
            )

        elif method == METHOD_PARTIAL_PAYMENT:
            explanation = (
                f"Partially affordable up to {amount_safe_to_pay:.2f} {request.currency}. "
                f"Paying above this amount breaches your {min_keep:.2f} {curr} reserve."
            )

        else: # METHOD_NOT_RECOMMENDED
            if earliest_full_date:
                explanation = (
                    f"Not recommended. Projected cashflow breaches your {min_keep:.2f} {curr} safety reserve "
                    f"over 90 days. Earliest date for safe full payment is {earliest_full_date.isoformat()}."
                )
            else:
                explanation = (
                    f"Not recommended. Projected cashflow breaches your {min_keep:.2f} {curr} safety reserve "
                    f"across all evaluated payment plans over 90 days."
                )

        # Truncate if needed to prevent excessive string lengths
        if len(explanation) > 280:
            explanation = explanation[:277] + "..."

        return explanation
