"""
Data ingestion and relational loader module.
Parses CSV files, handles foreign-key joins, and resolves blank event amounts.
"""
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Optional
import csv
from code.models import (
    Profile, Event, Message, ImageRecord, PaymentOption,
    ExchangeRate, PurchaseRequest
)
from code.config import setup_logging

logger = setup_logging(__name__)

def parse_date(date_str: str) -> Optional[date]:
    if not date_str or not date_str.strip():
        return None
    # Handle YYYY-MM-DD or ISO timestamp
    clean = date_str.strip().split("T")[0]
    return datetime.strptime(clean, "%Y-%m-%d").date()

def parse_decimal(val_str: str, default: Optional[Decimal] = None) -> Optional[Decimal]:
    if val_str is None or val_str.strip() == "":
        return default
    clean = val_str.replace("$", "").replace("€", "").replace("£", "").replace(",", "").strip()
    try:
        parsed = Decimal(clean)
        if not parsed.is_finite():
            raise ValueError("non-finite numeric")
        return parsed.quantize(Decimal("0.01"))
    except Exception:
        logger.warning("Malformed numeric value %r; using default %r", val_str, default)
        return default

def parse_int(val_str: str, default: int = 0) -> int:
    try:
        value = int(str(val_str).strip())
        return value if value >= 0 else default
    except (TypeError, ValueError):
        logger.warning("Malformed integer value %r; using default %r", val_str, default)
        return default

class DataLoader:
    def __init__(self, dataset_dir: Path):
        self.dataset_dir = dataset_dir

    def load_profiles(self) -> Dict[str, Profile]:
        profiles = {}
        path = self.dataset_dir / "profiles.csv"
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                uid = row["user_id"].strip()
                methods_raw = row.get("payment_methods_user_will_consider", "FULL,INSTALLMENTS,DEFERRED,FINANCING")
                # Normalize methods e.g. full_payment -> FULL, installments -> INSTALLMENTS
                methods = []
                for m in methods_raw.split(","):
                    m_clean = m.strip().upper()
                    if "FULL" in m_clean:
                        methods.append("FULL")
                    elif "INSTALL" in m_clean or "BNPL" in m_clean:
                        methods.append("INSTALLMENTS")
                    elif "DEFER" in m_clean:
                        methods.append("DEFERRED")
                    elif "FINANC" in m_clean:
                        methods.append("FINANCING")
                    else:
                        methods.append(m_clean)

                profiles[uid] = Profile(
                    user_id=uid,
                    base_currency=row.get("base_currency", "USD").strip().upper(),
                    current_balance=parse_decimal(row.get("current_balance"), Decimal("0.00")),
                    minimum_balance_to_keep=parse_decimal(row.get("minimum_balance_to_keep"), Decimal("500.00")),
                    monthly_essential_expenses=parse_decimal(row.get("monthly_essential_expenses"), Decimal("0.00")),
                    monthly_flexible_expenses=parse_decimal(row.get("monthly_flexible_expenses"), Decimal("0.00")),
                    payment_methods_user_will_consider=methods,
                    risk_tolerance=row.get("risk_tolerance", "moderate").strip().lower()
                )
        logger.info(f"Loaded {len(profiles)} user profiles.")
        return profiles

    def load_events(self) -> List[Event]:
        events = []
        path = self.dataset_dir / "events.csv"
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                amount_raw = row.get("amount", "").strip()
                parsed_amount = None if amount_raw == "" else parse_decimal(amount_raw)

                dom_raw = row.get("day_of_month", "").strip()
                dom = int(dom_raw) if dom_raw.isdigit() else None

                events.append(Event(
                    event_id=row["event_id"].strip(),
                    user_id=row["user_id"].strip(),
                    event_type=row.get("event_type", "expense").strip().lower(),
                    category=row.get("category", "general").strip().lower(),
                    amount=parsed_amount,  # Can be None! Preserved for resolution
                    currency=row.get("currency", "USD").strip().upper(),
                    frequency=row.get("frequency", "one-time").strip().lower(),
                    start_date=parse_date(row["start_date"]),
                    day_of_month=dom,
                    end_date=parse_date(row.get("end_date")),
                    status=row.get("status", "confirmed").strip().lower(),
                    is_essential=row.get("is_essential", "true").strip().lower() in ["true", "1", "yes"],
                    is_unrealized=row.get("is_unrealized", "false").strip().lower() in ["true", "1", "yes"],
                    image_id=row.get("image_id", "").strip() or None,
                    related_event_id=row.get("related_event_id", "").strip() or None,
                    description=row.get("description", "").strip()
                ))
        logger.info(f"Loaded {len(events)} events.")
        return events

    def load_messages(self) -> List[Message]:
        messages = []
        path = self.dataset_dir / "messages.csv"
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                messages.append(Message(
                    message_id=row["message_id"].strip(),
                    user_id=row["user_id"].strip(),
                    timestamp=row.get("timestamp", "").strip(),
                    sender=row.get("sender", "user").strip(),
                    content=row.get("content", "").strip(),
                    related_event_id=row.get("related_event_id", "").strip() or None
                ))
        logger.info(f"Loaded {len(messages)} messages.")
        return messages

    def load_images(self) -> List[ImageRecord]:
        images = []
        path = self.dataset_dir / "images.csv"
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                images.append(ImageRecord(
                    image_id=row["image_id"].strip(),
                    user_id=row["user_id"].strip(),
                    file_path=row.get("file_path", "").strip(),
                    document_type=row.get("document_type", "bill").strip().lower(),
                    related_event_id=row.get("related_event_id", "").strip() or None,
                    description=row.get("description", "").strip()
                ))
        logger.info(f"Loaded {len(images)} image records.")
        return images

    def load_payment_options(self) -> Dict[str, List[PaymentOption]]:
        # Keyed by request_id
        options_map: Dict[str, List[PaymentOption]] = {}
        path = self.dataset_dir / "payment_options.csv"
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rid = row["request_id"].strip()
                if rid not in options_map:
                    options_map[rid] = []

                opt = PaymentOption(
                    option_id=row["option_id"].strip(),
                    request_id=rid,
                    payment_type=row.get("payment_type", "FULL").strip().upper(),
                    installments_count=max(1, parse_int(row.get("installments_count", 1), 1)),
                    interest_rate_apr=parse_decimal(row.get("interest_rate_apr"), Decimal("0.00")),
                    fee_fixed=parse_decimal(row.get("fee_fixed"), Decimal("0.00")),
                    fee_percentage=parse_decimal(row.get("fee_percentage"), Decimal("0.00")),
                    interval_days=parse_int(row.get("interval_days", 30), 30),
                    initial_deposit_pct=parse_decimal(row.get("initial_deposit_pct"), Decimal("0.00")),
                    allows_partial_payment=row.get("allows_partial_payment", "true").strip().lower() in ["true", "1", "yes"],
                    currency=row.get("currency", "USD").strip().upper()
                )
                options_map[rid].append(opt)
        logger.info(f"Loaded payment options for {len(options_map)} requests.")
        return options_map

    def load_exchange_rates(self) -> List[ExchangeRate]:
        rates = []
        path = self.dataset_dir / "exchange_rates.csv"
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rates.append(ExchangeRate(
                    date_val=parse_date(row["date"]),
                    from_currency=row["from_currency"].strip().upper(),
                    to_currency=row["to_currency"].strip().upper(),
                    rate=parse_decimal(row["rate"], Decimal("1.00"))
                ))
        logger.info(f"Loaded {len(rates)} exchange rates.")
        return rates

    def load_requests(self, filename: str = "prediction_requests.csv") -> List[PurchaseRequest]:
        requests = []
        path = self.dataset_dir / filename
        if not path.exists():
            # Fallback to sample_requests.csv if prediction_requests.csv is not present
            alt_path = self.dataset_dir / "sample_requests.csv"
            if alt_path.exists():
                path = alt_path
                logger.info(f"{filename} not found, falling back to sample_requests.csv")
            else:
                logger.error(f"No requests file found at {path}")
                return []

        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                requests.append(PurchaseRequest(
                    request_id=row["request_id"].strip(),
                    user_id=row["user_id"].strip(),
                    request_date=parse_date(row["request_date"]),
                    item_name=row.get("item_name", "Target Purchase").strip(),
                    amount=parse_decimal(row["amount"], Decimal("0.00")),
                    currency=row.get("currency", "USD").strip().upper(),
                    desired_completion_date=parse_date(row.get("desired_completion_date")),
                    allows_partial_payment=row.get("allows_partial_payment", "true").strip().lower() in ["true", "1", "yes"],
                    urgency=row.get("urgency", "medium").strip().lower()
                ))
        logger.info(f"Loaded {len(requests)} purchase requests from {path.name}.")
        return requests
