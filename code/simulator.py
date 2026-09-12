"""
Deterministic 90-day day-by-day cashflow balance simulation engine.
Forecasts balance Day 0 through Day 90, strictly enforcing minimum_balance_to_keep.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Dict, Tuple, Optional
import calendar
from code.models import Event, SimulationResult, PaymentSchedule
from code.financial_state import ReconstructedFinancialState
from code.currency import CurrencyConverter
from code.config import SIMULATION_HORIZON_DAYS, setup_logging

logger = setup_logging(__name__)

def is_event_active_on_date(ev: Event, target_date: date) -> bool:
    """
    Evaluates whether an event generates a cashflow on target_date.
    """
    if target_date < ev.start_date:
        return False
    if ev.end_date and target_date > ev.end_date:
        return False

    freq = (ev.frequency or "one-time").lower()

    if freq == "one-time":
        return target_date == ev.start_date
    elif freq == "daily":
        return True
    elif freq == "weekly":
        return (target_date - ev.start_date).days % 7 == 0
    elif freq in ["bi-weekly", "biweekly"]:
        return (target_date - ev.start_date).days % 14 == 0
    elif freq == "monthly":
        target_day = ev.day_of_month or ev.start_date.day
        # Handle month length (e.g. day 31 in Feb)
        _, days_in_month = calendar.monthrange(target_date.year, target_date.month)
        effective_day = min(target_day, days_in_month)
        return target_date.day == effective_day
    elif freq == "quarterly":
        months = (target_date.year - ev.start_date.year) * 12 + target_date.month - ev.start_date.month
        if months < 0 or months % 3 != 0:
            return False
        target_day = ev.day_of_month or ev.start_date.day
        _, days_in_month = calendar.monthrange(target_date.year, target_date.month)
        return target_date.day == min(target_day, days_in_month)
    elif freq == "annual":
        return target_date.month == ev.start_date.month and target_date.day == ev.start_date.day

    return False

class BalanceSimulator:
    def __init__(self, currency_converter: CurrencyConverter):
        self.converter = currency_converter

    def simulate(
        self,
        state: ReconstructedFinancialState,
        request_date: date,
        plan_schedule: Optional[PaymentSchedule] = None,
        flexible_reduction_pct: Decimal = Decimal("0.00"),
        horizon_days: int = SIMULATION_HORIZON_DAYS
    ) -> SimulationResult:
        """
        Simulates cash balance from request_date (Day 0) to request_date + horizon_days (Day 90).
        """
        base_curr = state.profile.base_currency
        min_balance = state.minimum_balance_to_keep
        current_balance = state.liquid_starting_balance

        daily_balances: List[Decimal] = []
        min_cushion = current_balance
        min_cushion_date = request_date
        is_safe = True
        failed_on_day = None
        violation_amount = Decimal("0.00")

        # Map plan payments to specific calendar dates
        plan_payment_map: Dict[date, Decimal] = {}
        if plan_schedule:
            for d, amt in zip(plan_schedule.due_dates, plan_schedule.due_amounts):
                # Convert plan payment to base currency if needed
                converted_amt = self.converter.convert(amt, plan_schedule.currency, base_curr, d)
                plan_payment_map[d] = plan_payment_map.get(d, Decimal("0.00")) + converted_amt

        # Daily simulation loop
        for day_offset in range(horizon_days + 1):
            cur_date = request_date + timedelta(days=day_offset)

            # 1. Apply Inflows for cur_date
            daily_inflows = Decimal("0.00")
            for ev in state.active_inflows:
                if is_event_active_on_date(ev, cur_date):
                    converted = self.converter.convert(ev.amount, ev.currency, base_curr, cur_date)
                    daily_inflows += converted

            current_balance += daily_inflows

            # 2. Deduct Plan Payments for cur_date
            if cur_date in plan_payment_map:
                current_balance -= plan_payment_map[cur_date]

            # 3. Apply Essential Outflows for cur_date
            daily_essential = Decimal("0.00")
            for ev in state.active_essential_expenses:
                if is_event_active_on_date(ev, cur_date):
                    converted = self.converter.convert(ev.amount, ev.currency, base_curr, cur_date)
                    daily_essential += converted

            # Use the profile baseline only when there are no itemized events.
            if not state.active_essential_expenses and state.profile.monthly_essential_expenses > 0:
                daily_essential += (state.profile.monthly_essential_expenses / Decimal("30.0")).quantize(Decimal("0.01"))

            current_balance -= daily_essential

            # 4. Apply Flexible Outflows for cur_date (with potential reduction applied)
            daily_flexible = Decimal("0.00")
            for ev in state.active_flexible_expenses:
                if is_event_active_on_date(ev, cur_date):
                    converted = self.converter.convert(ev.amount, ev.currency, base_curr, cur_date)
                    daily_flexible += converted

            if not state.active_flexible_expenses and state.profile.monthly_flexible_expenses > 0:
                daily_flexible += (state.profile.monthly_flexible_expenses / Decimal("30.0")).quantize(Decimal("0.01"))

            # Apply permitted reduction ratio (e.g. reduce by 20% during tight period)
            daily_flexible = (daily_flexible * (Decimal("1.00") - flexible_reduction_pct)).quantize(Decimal("0.01"))
            current_balance -= daily_flexible

            # Record state
            daily_balances.append(current_balance)

            if current_balance < min_cushion:
                min_cushion = current_balance
                min_cushion_date = cur_date

            # Safety Check Invariant
            if current_balance < min_balance and is_safe:
                is_safe = False
                failed_on_day = day_offset
                violation_amount = min_balance - current_balance

        return SimulationResult(
            is_safe=is_safe,
            min_cushion_observed=min_cushion,
            min_cushion_date=min_cushion_date,
            daily_balances=daily_balances,
            failed_on_day=failed_on_day,
            violation_amount=violation_amount
        )
