"""
Financial state reconstruction module.
Categorizes cashflows, separates essential vs flexible, filters invalid/unrealized events.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Dict, Any, Tuple
from code.models import Profile, Event
from code.currency import CurrencyConverter
from code.config import setup_logging

logger = setup_logging(__name__)

@dataclass
class ReconstructedFinancialState:
    profile: Profile
    liquid_starting_balance: Decimal
    minimum_balance_to_keep: Decimal
    active_inflows: List[Event]
    active_essential_expenses: List[Event]
    active_flexible_expenses: List[Event]
    ignored_events_summary: Dict[str, int] = field(default_factory=dict)

class FinancialStateReconstructor:
    def __init__(self, currency_converter: CurrencyConverter):
        self.converter = currency_converter

    def reconstruct(self, profile: Profile, raw_events: List[Event]) -> ReconstructedFinancialState:
        """
        Reconstructs the user's validated financial state from raw resolved events.
        """
        ignored_counts = {
            "cancelled": 0,
            "failed": 0,
            "pending_income": 0,
            "unrealized_investment": 0,
            "missing_amount": 0
        }

        active_inflows: List[Event] = []
        active_essential_expenses: List[Event] = []
        active_flexible_expenses: List[Event] = []

        for ev in raw_events:
            # 1. Filter cancelled & failed
            if ev.status in ["cancelled", "failed"]:
                ignored_counts[ev.status] += 1
                logger.debug(f"Ignoring {ev.status} event: {ev.event_id}")
                continue

            # 2. Filter pending income (do not count until confirmed)
            if ev.event_type in ["income", "refund"] and ev.status == "pending":
                ignored_counts["pending_income"] += 1
                logger.debug(f"Ignoring unconfirmed pending income: {ev.event_id}")
                continue

            # 3. Filter unrealized investments
            if ev.is_unrealized:
                ignored_counts["unrealized_investment"] += 1
                logger.debug(f"Ignoring unrealized investment: {ev.event_id}")
                continue

            # 4. Check for missing amount (should have been resolved from image)
            if ev.amount is None:
                ignored_counts["missing_amount"] += 1
                logger.error(f"Event {ev.event_id} still has missing amount after resolution!")
                continue

            # 5. Classify Inflows vs Expenses
            if ev.event_type in ["income", "refund"]:
                active_inflows.append(ev)
            elif ev.event_type in ["expense", "investment"]:
                # If investment is realized cash outflow, it's an expense
                if ev.is_essential:
                    active_essential_expenses.append(ev)
                else:
                    active_flexible_expenses.append(ev)
            else:
                logger.warning(f"Unknown event_type {ev.event_type} for event {ev.event_id}")

        logger.debug(
            f"User {profile.user_id} financial state reconstructed: "
            f"{len(active_inflows)} inflows, {len(active_essential_expenses)} essential, "
            f"{len(active_flexible_expenses)} flexible. Ignored: {ignored_counts}"
        )

        return ReconstructedFinancialState(
            profile=profile,
            liquid_starting_balance=profile.current_balance,
            minimum_balance_to_keep=profile.minimum_balance_to_keep,
            active_inflows=active_inflows,
            active_essential_expenses=active_essential_expenses,
            active_flexible_expenses=active_flexible_expenses,
            ignored_events_summary=ignored_counts
        )
