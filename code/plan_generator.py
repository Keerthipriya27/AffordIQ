"""
Payment plan schedule generator and candidate explorer.
Calculates nominal costs, due dates, installment breakdowns, and delay scenarios.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional, Any
from code.models import PaymentOption, PaymentSchedule, PurchaseRequest, Profile
from code.config import MAX_WAIT_SEARCH_DAYS, setup_logging

logger = setup_logging(__name__)

class PaymentPlanGenerator:
    @staticmethod
    def build_schedule(
        option: PaymentOption,
        amount: Decimal,
        start_date: date,
        amount_currency: Optional[str] = None,
        currency_converter: Optional[Any] = None
    ) -> PaymentSchedule:
        """
        Builds precise calendar dates and amounts for a payment option.
        """
        if amount_currency and option.currency and amount_currency.upper() != option.currency.upper():
            if currency_converter is None or not currency_converter.has_supplied_rate_on_date(
                amount_currency, option.currency, start_date
            ):
                raise ValueError(
                    f"No dated rate to reconcile request {amount_currency} with option {option.currency}"
                )
            amount = currency_converter.convert(amount, amount_currency, option.currency, start_date)

        # Calculate fees and interest
        fee_fixed = option.fee_fixed
        fee_pct = (amount * option.fee_percentage).quantize(Decimal("0.01"))
        
        # Calculate interest if financing
        count = max(1, option.installments_count)
        interval = option.interval_days or 30
        approx_months = Decimal(str((count * interval) / 30.0))
        interest = Decimal("0.00")
        if option.interest_rate_apr > 0:
            interest = (amount * option.interest_rate_apr * (approx_months / Decimal("12.0"))).quantize(Decimal("0.01"))

        total_cost = (amount + fee_fixed + fee_pct + interest).quantize(Decimal("0.01"))
        
        # Schedule generation.  An initial deposit is the first due amount;
        # the remaining balance is spread across the remaining installments.
        due_dates: List[date] = []
        due_amounts: List[Decimal] = []

        if count == 1:
            due_dates.append(start_date)
            due_amounts.append(total_cost)
            installment_amt = total_cost
        else:
            # Multi-installment (e.g. BNPL Pay in 4)
            deposit_pct = max(Decimal("0"), min(Decimal("1"), option.initial_deposit_pct))
            first = (total_cost * deposit_pct).quantize(Decimal("0.01"))
            remaining_count = count - 1
            base_installment = ((total_cost - first) / Decimal(str(remaining_count))
                                ).quantize(Decimal("0.01")) if remaining_count else total_cost
            allocated = Decimal("0.00")
            
            for i in range(count):
                due_d = start_date + timedelta(days=i * interval)
                due_dates.append(due_d)
                if i == 0 and deposit_pct > 0:
                    due_amounts.append(first)
                elif i == count - 1:
                    # Final installment absorbs rounding difference
                    due_amounts.append(total_cost - first - allocated)
                else:
                    due_amounts.append(base_installment)
                    allocated += base_installment

            installment_amt = base_installment

        return PaymentSchedule(
            option_id=option.option_id,
            payment_type=option.payment_type.upper(),
            start_date=start_date,
            installments_count=count,
            installment_amount=installment_amt,
            total_nominal_cost=total_cost,
            due_dates=due_dates,
            due_amounts=due_amounts,
            currency=option.currency or "USD"
        )

    @staticmethod
    def is_option_eligible(
        option: PaymentOption,
        request: PurchaseRequest,
        profile: Profile
    ) -> bool:
        """
        Validates user preference constraints and partial payment rules.
        """
        # 1. User payment method preference check
        allowed_methods = [m.upper() for m in profile.payment_methods_user_will_consider]
        if option.payment_type.upper() not in allowed_methods:
            return False

        # 2. Partial payment allowance check
        if not request.allows_partial_payment and option.installments_count > 1:
            return False

        return True
