"""
Explanation generation module producing concise, grounded rationales.
"""
from decimal import Decimal
from code.models import CandidatePlan, PurchaseRequest, Profile

class PlanExplainer:
    @staticmethod
    def generate_explanation(
        plan: CandidatePlan,
        request: PurchaseRequest,
        profile: Profile
    ) -> str:
        curr = profile.base_currency
        cushion = plan.simulation.min_cushion_observed
        min_keep = profile.minimum_balance_to_keep

        if plan.decision == "BUY_NOW":
            if plan.schedule.installments_count > 1:
                desc = f"Affordable via {plan.schedule.installments_count} installments of {plan.schedule.installment_amount:.2f} {curr}."
            else:
                desc = f"Affordable in full ({plan.schedule.total_nominal_cost:.2f} {curr})."
            
            cushion_desc = f" Lowest 90-day balance is {cushion:.2f} {curr}, exceeding your {min_keep:.2f} {curr} reserve."
            explanation = desc + cushion_desc

        elif plan.decision == "WAIT":
            days_wait = (plan.start_date - request.request_date).days
            explanation = (
                f"Wait {days_wait} days until {plan.start_date.isoformat()} after scheduled cash inflow. "
                f"Maintains a safe minimum cushion of {cushion:.2f} {curr} above your reserve."
            )

        else: # DO_NOT_BUY
            explanation = (
                f"Not recommended. Projected cashflow breaches your {min_keep:.2f} {curr} safety reserve "
                f"across all evaluated payment plans over 90 days."
            )

        # Ensure length <= 250 chars
        if len(explanation) > 250:
            explanation = explanation[:247] + "..."

        return explanation
