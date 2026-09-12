"""
Domain models and dataclasses for the Buy or Wait reasoning engine.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional, Dict, Any

@dataclass
class Profile:
    user_id: str
    base_currency: str
    current_balance: Decimal
    minimum_balance_to_keep: Decimal
    monthly_essential_expenses: Decimal
    monthly_flexible_expenses: Decimal
    payment_methods_user_will_consider: List[str]  # e.g. ["FULL", "INSTALLMENTS", "DEFERRED", "FINANCING"]
    risk_tolerance: str = "moderate"
    flexible_reduction_limit: Decimal = Decimal("0.50")

@dataclass
class Event:
    event_id: str
    user_id: str
    event_type: str        # income, expense, refund, investment, credit_line
    category: str          # salary, rent, utilities, subscription, loan_payment, groceries, dining, stock_purchase
    amount: Optional[Decimal]   # None if blank in CSV! Must be resolved
    currency: str
    frequency: str         # one-time, daily, weekly, bi-weekly, monthly, quarterly, annual
    start_date: date
    day_of_month: Optional[int] = None
    end_date: Optional[date] = None
    status: str = "confirmed"   # confirmed, pending, cancelled, failed
    is_essential: bool = True
    is_unrealized: bool = False
    image_id: Optional[str] = None
    related_event_id: Optional[str] = None
    description: str = ""

@dataclass
class Message:
    message_id: str
    user_id: str
    timestamp: str         # ISO format or YYYY-MM-DD
    sender: str
    content: str
    related_event_id: Optional[str] = None

@dataclass
class ImageRecord:
    image_id: str
    user_id: str
    file_path: str
    document_type: str     # bill, receipt, payslip, contract, price_quote
    related_event_id: Optional[str] = None
    description: str = ""
    # Extracted fields from evidence
    extracted_amount: Optional[Decimal] = None
    extracted_currency: Optional[str] = None
    extracted_date: Optional[date] = None
    extracted_notes: str = ""

@dataclass
class PaymentOption:
    option_id: str
    request_id: str
    payment_type: str      # FULL, INSTALLMENTS, DEFERRED, FINANCING
    installments_count: int
    interest_rate_apr: Decimal
    fee_fixed: Decimal
    fee_percentage: Decimal
    interval_days: int
    initial_deposit_pct: Decimal
    allows_partial_payment: bool
    currency: str

@dataclass
class ExchangeRate:
    date_val: date
    from_currency: str
    to_currency: str
    rate: Decimal

@dataclass
class PurchaseRequest:
    request_id: str
    user_id: str
    request_date: date
    item_name: str
    amount: Decimal
    currency: str
    desired_completion_date: Optional[date] = None
    allows_partial_payment: bool = True
    urgency: str = "medium"

@dataclass
class PaymentSchedule:
    option_id: str
    payment_type: str
    start_date: date
    installments_count: int
    installment_amount: Decimal
    total_nominal_cost: Decimal
    due_dates: List[date]
    due_amounts: List[Decimal]
    currency: str = "USD"

@dataclass
class SimulationResult:
    is_safe: bool
    min_cushion_observed: Decimal
    min_cushion_date: date
    daily_balances: List[Decimal]
    failed_on_day: Optional[int] = None
    violation_amount: Decimal = Decimal("0.00")

@dataclass
class CandidatePlan:
    decision: str          # BUY_NOW, WAIT, DO_NOT_BUY
    option: Optional[PaymentOption]
    schedule: Optional[PaymentSchedule]
    start_date: date
    simulation: SimulationResult
    score: float
    flexible_reduction_applied: Decimal = Decimal("0.00")
    reason: str = ""

@dataclass
class OutputRow:
    request_id: str
    decision: str
    recommended_option_id: str
    payment_type: str
    start_date: str
    total_cost: Decimal
    installments_count: int
    installment_amount: Decimal
    safety_cushion_min: Decimal
    explanation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "decision": self.decision,
            "recommended_option_id": self.recommended_option_id,
            "payment_type": self.payment_type,
            "start_date": self.start_date,
            "total_cost": f"{self.total_cost:.2f}",
            "installments_count": self.installments_count,
            "installment_amount": f"{self.installment_amount:.2f}",
            "safety_cushion_min": f"{self.safety_cushion_min:.2f}",
            "explanation": self.explanation
        }

@dataclass
class EvidenceRecord:
    source_id: str
    source_type: str  # "message" | "image"
    financial_facts: List[str] = field(default_factory=list)
    event_updates: List[Dict[str, Any]] = field(default_factory=list)
    amounts: List[Decimal] = field(default_factory=list)
    currencies: List[str] = field(default_factory=list)
    dates: List[str] = field(default_factory=list)
    recurring_frequency: Optional[str] = None
    status: Optional[str] = None
    cancellation: Optional[bool] = None
    confirmation: Optional[bool] = None
    confidence: float = 0.0
    reasoning_summary: str = ""
    potential_conflict: bool = False
    merchant_payee: Optional[str] = None
    document_type: Optional[str] = None
    relevant_identifiers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "financial_facts": self.financial_facts,
            "event_updates": self.event_updates,
            "amounts": [str(a) for a in self.amounts],
            "currencies": self.currencies,
            "dates": self.dates,
            "recurring_frequency": self.recurring_frequency,
            "status": self.status,
            "cancellation": self.cancellation,
            "confirmation": self.confirmation,
            "confidence": self.confidence,
            "reasoning_summary": self.reasoning_summary,
            "potential_conflict": self.potential_conflict,
            "merchant_payee": self.merchant_payee,
            "document_type": self.document_type,
            "relevant_identifiers": self.relevant_identifiers
        }

