"""
Currency conversion engine using dated exchange rates.
"""
from datetime import date
from decimal import Decimal
from typing import Dict, Tuple, Optional, List
from code.models import ExchangeRate
from code.config import setup_logging

logger = setup_logging(__name__)

class MissingExchangeRateError(ValueError):
    """Raised when a conversion is requested without a supplied dated rate."""

class CurrencyConverter:
    def __init__(self, rates: List[ExchangeRate]):
        # Store as: (from_currency, to_currency) -> sorted list of (date, rate)
        self.rate_map: Dict[Tuple[str, str], List[Tuple[date, Decimal]]] = {}
        for r in rates:
            pair = (r.from_currency.upper(), r.to_currency.upper())
            if pair not in self.rate_map:
                self.rate_map[pair] = []
            self.rate_map[pair].append((r.date_val, r.rate))
            
            # Preserve every dated inverse.  Replacing the first entry loses
            # historical rates when the source contains multiple dates.
            inv_pair = (r.to_currency.upper(), r.from_currency.upper())
            if r.rate > 0:
                if inv_pair not in self.rate_map:
                    self.rate_map[inv_pair] = []
                self.rate_map[inv_pair].append((r.date_val, Decimal("1.0") / r.rate))

        # Sort all entries by date ascending
        for pair in self.rate_map:
            self.rate_map[pair].sort(key=lambda x: x[0])

    def get_rate(self, from_curr: str, to_curr: str, on_date: date) -> Decimal:
        from_curr = from_curr.upper()
        to_curr = to_curr.upper()
        if from_curr == to_curr:
            return Decimal("1.0")

        pair = (from_curr, to_curr)
        if pair not in self.rate_map:
            # Check if indirect through USD
            usd_pair1 = (from_curr, "USD")
            usd_pair2 = ("USD", to_curr)
            if usd_pair1 in self.rate_map and usd_pair2 in self.rate_map:
                r1 = self.get_rate(from_curr, "USD", on_date)
                r2 = self.get_rate("USD", to_curr, on_date)
                return r1 * r2
            raise MissingExchangeRateError(
                f"No exchange rate supplied for {from_curr} -> {to_curr} on {on_date}"
            )

        rates = self.rate_map[pair]
        # Binary search or scan for latest date <= on_date
        dated = [(d, r) for d, r in rates if d <= on_date]
        if not dated:
            raise MissingExchangeRateError(
                f"No exchange rate supplied for {from_curr} -> {to_curr} on {on_date}"
            )
        best_rate = dated[-1][1]
        return best_rate

    def convert(self, amount: Decimal, from_curr: str, to_curr: str, on_date: date) -> Decimal:
        if amount is None:
            return None
        rate = self.get_rate(from_curr, to_curr, on_date)
        return (amount * rate).quantize(Decimal("0.01"))

    def has_supplied_rate(self, from_curr: str, to_curr: str) -> bool:
        """True when a dated exchange rate exists (direct or via USD), not a fallback."""
        from_curr = from_curr.upper()
        to_curr = to_curr.upper()
        if from_curr == to_curr:
            return True
        if (from_curr, to_curr) in self.rate_map:
            return True
        usd_pair1 = (from_curr, "USD")
        usd_pair2 = ("USD", to_curr)
        return usd_pair1 in self.rate_map and usd_pair2 in self.rate_map

    def has_supplied_rate_on_date(self, from_curr: str, to_curr: str, on_date: date) -> bool:
        """True when a direct or indirect dated rate is available on or before on_date."""
        from_curr = from_curr.upper()
        to_curr = to_curr.upper()
        if from_curr == to_curr:
            return True
        if (from_curr, to_curr) in self.rate_map:
            return any(rate_date <= on_date for rate_date, _ in self.rate_map[(from_curr, to_curr)])
        return (
            self.has_supplied_rate_on_date(from_curr, "USD", on_date)
            and self.has_supplied_rate_on_date("USD", to_curr, on_date)
        )

    def missing_rate_pairs(self, currencies: List[str], base_currency: str) -> List[Tuple[str, str]]:
        """Returns currency pairs lacking supplied rates relative to base_currency."""
        missing: List[Tuple[str, str]] = []
        base = base_currency.upper()
        seen: set = set()
        for curr in currencies:
            c = curr.upper()
            if c == base:
                continue
            pair = (c, base)
            if pair in seen:
                continue
            seen.add(pair)
            if not self.has_supplied_rate(c, base):
                missing.append(pair)
        return missing
