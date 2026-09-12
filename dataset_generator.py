"""
Generates comprehensive benchmark and test dataset for Buy or Wait.
Includes all edge cases: blank amounts resolved from images, cancellations via messages,
unrealized investments, currency conversions, BNPL, partial payments, and safety limits.
"""
import os
import csv
from pathlib import Path
from decimal import Decimal

def generate_dataset():
    dataset_dir = Path("/app/applet/dataset")
    media_dir = dataset_dir / "media" / "images"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)

    # 1. profiles.csv
    profiles = [
        {
            "user_id": "usr_101",
            "base_currency": "USD",
            "current_balance": "4200.00",
            "minimum_balance_to_keep": "1000.00",
            "monthly_essential_expenses": "1800.00",
            "monthly_flexible_expenses": "600.00",
            "payment_methods_user_will_consider": "FULL,INSTALLMENTS",
            "risk_tolerance": "moderate"
        },
        {
            "user_id": "usr_102",
            "base_currency": "EUR",
            "current_balance": "1400.00",
            "minimum_balance_to_keep": "800.00",
            "monthly_essential_expenses": "1100.00",
            "monthly_flexible_expenses": "300.00",
            "payment_methods_user_will_consider": "INSTALLMENTS,DEFERRED",
            "risk_tolerance": "conservative"
        },
        {
            "user_id": "usr_103",
            "base_currency": "USD",
            "current_balance": "850.00",
            "minimum_balance_to_keep": "800.00",
            "monthly_essential_expenses": "1500.00",
            "monthly_flexible_expenses": "400.00",
            "payment_methods_user_will_consider": "FULL,INSTALLMENTS,FINANCING",
            "risk_tolerance": "aggressive"
        },
        {
            "user_id": "usr_104",
            "base_currency": "GBP",
            "current_balance": "5500.00",
            "minimum_balance_to_keep": "1200.00",
            "monthly_essential_expenses": "2200.00",
            "monthly_flexible_expenses": "800.00",
            "payment_methods_user_will_consider": "FULL,FINANCING",
            "risk_tolerance": "moderate"
        },
        {
            "user_id": "usr_105",
            "base_currency": "USD",
            "current_balance": "2100.00",
            "minimum_balance_to_keep": "500.00",
            "monthly_essential_expenses": "1200.00",
            "monthly_flexible_expenses": "450.00",
            "payment_methods_user_will_consider": "FULL,INSTALLMENTS",
            "risk_tolerance": "moderate"
        }
    ]

    with open(dataset_dir / "profiles.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(profiles[0].keys()))
        writer.writeheader()
        writer.writerows(profiles)

    # 2. images.csv and dummy image files
    images = [
        {
            "image_id": "img_util_01",
            "user_id": "usr_101",
            "file_path": "dataset/media/images/electric_bill_sept.jpg",
            "document_type": "bill",
            "related_event_id": "ev_101_util",
            "description": "Electricity utility bill invoice amount: 165.50 USD due on 2026-09-28"
        },
        {
            "image_id": "img_rent_02",
            "user_id": "usr_102",
            "file_path": "dataset/media/images/landlord_rent_notice.png",
            "document_type": "contract",
            "related_event_id": "ev_102_rent",
            "description": "Apartment lease renewal confirmation: Rent is 850.00 EUR effective 2026-10-01"
        },
        {
            "image_id": "img_payslip_03",
            "user_id": "usr_103",
            "file_path": "dataset/media/images/biweekly_payslip.png",
            "document_type": "payslip",
            "related_event_id": "ev_103_sal",
            "description": "Bi-weekly direct deposit net pay statement: 1400.00 USD"
        }
    ]

    with open(dataset_dir / "images.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(images[0].keys()))
        writer.writeheader()
        writer.writerows(images)

    # Create dummy images in media dir
    for img in images:
        p = media_dir / Path(img["file_path"]).name
        p.write_text("Dummy binary image artifact")

    # 3. messages.csv
    messages = [
        {
            "message_id": "msg_001",
            "user_id": "usr_101",
            "timestamp": "2026-09-10T14:30:00",
            "sender": "Gym Fit Club",
            "content": "Your request to cancel your monthly gym membership has been processed.",
            "related_event_id": "ev_101_gym"
        },
        {
            "message_id": "msg_002",
            "user_id": "usr_103",
            "timestamp": "2026-09-11T09:15:00",
            "sender": "HR Payroll",
            "content": "Congratulations on your raise! Your bi-weekly salary increase to $1400 is active.",
            "related_event_id": "ev_103_sal"
        }
    ]

    with open(dataset_dir / "messages.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(messages[0].keys()))
        writer.writeheader()
        writer.writerows(messages)

    # 4. events.csv (includes blank amounts, cancelled, unrealized investments, duplicates)
    events = [
        # User 101: Salary confirmed bi-weekly
        {
            "event_id": "ev_101_sal",
            "user_id": "usr_101",
            "event_type": "income",
            "category": "salary",
            "amount": "2600.00",
            "currency": "USD",
            "frequency": "bi-weekly",
            "start_date": "2026-09-15",
            "day_of_month": "",
            "end_date": "",
            "status": "confirmed",
            "is_essential": "true",
            "is_unrealized": "false",
            "image_id": "",
            "related_event_id": "",
            "description": "Bi-weekly paycheck"
        },
        # User 101: Utility with BLANK AMOUNT (must be resolved from img_util_01!)
        {
            "event_id": "ev_101_util",
            "user_id": "usr_101",
            "event_type": "expense",
            "category": "utilities",
            "amount": "",  # BLANK!
            "currency": "USD",
            "frequency": "monthly",
            "start_date": "2026-09-28",
            "day_of_month": "28",
            "end_date": "",
            "status": "confirmed",
            "is_essential": "true",
            "is_unrealized": "false",
            "image_id": "img_util_01",
            "related_event_id": "",
            "description": "Monthly electric utility"
        },
        # User 101: Gym membership (should be marked cancelled per msg_001)
        {
            "event_id": "ev_101_gym",
            "user_id": "usr_101",
            "event_type": "expense",
            "category": "gym",
            "amount": "65.00",
            "currency": "USD",
            "frequency": "monthly",
            "start_date": "2026-09-20",
            "day_of_month": "20",
            "end_date": "",
            "status": "confirmed",
            "is_essential": "false",
            "is_unrealized": "false",
            "image_id": "",
            "related_event_id": "",
            "description": "Monthly gym"
        },
        # User 101: Duplicate event record to test deduplication
        {
            "event_id": "ev_101_gym_dup",
            "user_id": "usr_101",
            "event_type": "expense",
            "category": "gym",
            "amount": "65.00",
            "currency": "USD",
            "frequency": "monthly",
            "start_date": "2026-09-20",
            "day_of_month": "20",
            "end_date": "",
            "status": "confirmed",
            "is_essential": "false",
            "is_unrealized": "false",
            "image_id": "",
            "related_event_id": "",
            "description": "Monthly gym duplicate"
        },
        # User 101: Unrealized stock portfolio (must NOT be counted in liquid cash)
        {
            "event_id": "ev_101_stocks",
            "user_id": "usr_101",
            "event_type": "investment",
            "category": "portfolio",
            "amount": "15000.00",
            "currency": "USD",
            "frequency": "one-time",
            "start_date": "2026-09-12",
            "day_of_month": "",
            "end_date": "",
            "status": "confirmed",
            "is_essential": "false",
            "is_unrealized": "true",
            "image_id": "",
            "related_event_id": "",
            "description": "Unrealized stock valuation"
        },
        # User 101: Pending bonus (must NOT be counted in forecast)
        {
            "event_id": "ev_101_bonus_pending",
            "user_id": "usr_101",
            "event_type": "income",
            "category": "bonus",
            "amount": "2000.00",
            "currency": "USD",
            "frequency": "one-time",
            "start_date": "2026-09-30",
            "day_of_month": "",
            "end_date": "",
            "status": "pending",
            "is_essential": "false",
            "is_unrealized": "false",
            "image_id": "",
            "related_event_id": "",
            "description": "Unconfirmed pending bonus"
        },
        # User 102: Monthly Salary (EUR)
        {
            "event_id": "ev_102_sal",
            "user_id": "usr_102",
            "event_type": "income",
            "category": "salary",
            "amount": "1800.00",
            "currency": "EUR",
            "frequency": "monthly",
            "start_date": "2026-09-25",
            "day_of_month": "25",
            "end_date": "",
            "status": "confirmed",
            "is_essential": "true",
            "is_unrealized": "false",
            "image_id": "",
            "related_event_id": "",
            "description": "Monthly salary"
        },
        # User 102: Rent (EUR) with BLANK AMOUNT resolved by img_rent_02
        {
            "event_id": "ev_102_rent",
            "user_id": "usr_102",
            "event_type": "expense",
            "category": "rent",
            "amount": "",  # Blank, resolved to 850.00 EUR from img_rent_02
            "currency": "EUR",
            "frequency": "monthly",
            "start_date": "2026-10-01",
            "day_of_month": "1",
            "end_date": "",
            "status": "confirmed",
            "is_essential": "true",
            "is_unrealized": "false",
            "image_id": "img_rent_02",
            "related_event_id": "",
            "description": "Monthly rent"
        },
        # User 103: Bi-weekly Salary
        {
            "event_id": "ev_103_sal",
            "user_id": "usr_103",
            "event_type": "income",
            "category": "salary",
            "amount": "1200.00",  # Updated to 1400.00 by msg_002 / img_payslip_03
            "currency": "USD",
            "frequency": "bi-weekly",
            "start_date": "2026-09-18",
            "day_of_month": "",
            "end_date": "",
            "status": "confirmed",
            "is_essential": "true",
            "is_unrealized": "false",
            "image_id": "img_payslip_03",
            "related_event_id": "",
            "description": "Bi-weekly paycheck"
        },
        # User 104: Salary in GBP
        {
            "event_id": "ev_104_sal",
            "user_id": "usr_104",
            "event_type": "income",
            "category": "salary",
            "amount": "3200.00",
            "currency": "GBP",
            "frequency": "monthly",
            "start_date": "2026-09-27",
            "day_of_month": "27",
            "end_date": "",
            "status": "confirmed",
            "is_essential": "true",
            "is_unrealized": "false",
            "image_id": "",
            "related_event_id": "",
            "description": "Monthly salary"
        },
        # User 105: Salary in USD
        {
            "event_id": "ev_105_sal",
            "user_id": "usr_105",
            "event_type": "income",
            "category": "salary",
            "amount": "1900.00",
            "currency": "USD",
            "frequency": "monthly",
            "start_date": "2026-09-22",
            "day_of_month": "22",
            "end_date": "",
            "status": "confirmed",
            "is_essential": "true",
            "is_unrealized": "false",
            "image_id": "",
            "related_event_id": "",
            "description": "Monthly salary"
        }
    ]

    with open(dataset_dir / "events.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(events[0].keys()))
        writer.writeheader()
        writer.writerows(events)

    # 5. payment_options.csv
    payment_options = [
        # Options for req_001 (User 101, Laptop $1200)
        {
            "option_id": "opt_001_full",
            "request_id": "req_001",
            "payment_type": "FULL",
            "installments_count": "1",
            "interest_rate_apr": "0.00",
            "fee_fixed": "0.00",
            "fee_percentage": "0.00",
            "interval_days": "30",
            "initial_deposit_pct": "1.00",
            "allows_partial_payment": "true",
            "currency": "USD"
        },
        {
            "option_id": "opt_001_bnpl4",
            "request_id": "req_001",
            "payment_type": "INSTALLMENTS",
            "installments_count": "4",
            "interest_rate_apr": "0.00",
            "fee_fixed": "0.00",
            "fee_percentage": "0.00",
            "interval_days": "14",
            "initial_deposit_pct": "0.25",
            "allows_partial_payment": "true",
            "currency": "USD"
        },
        # Options for req_002 (User 102, Washing Machine 450 EUR)
        {
            "option_id": "opt_002_bnpl3",
            "request_id": "req_002",
            "payment_type": "INSTALLMENTS",
            "installments_count": "3",
            "interest_rate_apr": "0.00",
            "fee_fixed": "0.00",
            "fee_percentage": "0.00",
            "interval_days": "30",
            "initial_deposit_pct": "0.33",
            "allows_partial_payment": "true",
            "currency": "EUR"
        },
        {
            "option_id": "opt_002_deferred",
            "request_id": "req_002",
            "payment_type": "DEFERRED",
            "installments_count": "1",
            "interest_rate_apr": "0.00",
            "fee_fixed": "5.00",
            "fee_percentage": "0.00",
            "interval_days": "30",
            "initial_deposit_pct": "0.00",
            "allows_partial_payment": "true",
            "currency": "EUR"
        },
        # Options for req_003 (User 103, Luxury watch $2500 - too high for balance $850)
        {
            "option_id": "opt_003_full",
            "request_id": "req_003",
            "payment_type": "FULL",
            "installments_count": "1",
            "interest_rate_apr": "0.00",
            "fee_fixed": "0.00",
            "fee_percentage": "0.00",
            "interval_days": "30",
            "initial_deposit_pct": "1.00",
            "allows_partial_payment": "false",
            "currency": "USD"
        },
        {
            "option_id": "opt_003_finance",
            "request_id": "req_003",
            "payment_type": "FINANCING",
            "installments_count": "12",
            "interest_rate_apr": "0.18",
            "fee_fixed": "25.00",
            "fee_percentage": "0.02",
            "interval_days": "30",
            "initial_deposit_pct": "0.08",
            "allows_partial_payment": "true",
            "currency": "USD"
        },
        # Options for req_004 (User 104, Vacation 800 GBP)
        {
            "option_id": "opt_004_full",
            "request_id": "req_004",
            "payment_type": "FULL",
            "installments_count": "1",
            "interest_rate_apr": "0.00",
            "fee_fixed": "0.00",
            "fee_percentage": "0.00",
            "interval_days": "30",
            "initial_deposit_pct": "1.00",
            "allows_partial_payment": "true",
            "currency": "GBP"
        },
        # Options for req_005 (User 105, Camera $900 - currently tight, safe after payday on 22nd -> WAIT)
        {
            "option_id": "opt_005_full",
            "request_id": "req_005",
            "payment_type": "FULL",
            "installments_count": "1",
            "interest_rate_apr": "0.00",
            "fee_fixed": "0.00",
            "fee_percentage": "0.00",
            "interval_days": "30",
            "initial_deposit_pct": "1.00",
            "allows_partial_payment": "true",
            "currency": "USD"
        },
        {
            "option_id": "opt_005_bnpl4",
            "request_id": "req_005",
            "payment_type": "INSTALLMENTS",
            "installments_count": "4",
            "interest_rate_apr": "0.00",
            "fee_fixed": "0.00",
            "fee_percentage": "0.00",
            "interval_days": "14",
            "initial_deposit_pct": "0.25",
            "allows_partial_payment": "true",
            "currency": "USD"
        }
    ]

    with open(dataset_dir / "payment_options.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(payment_options[0].keys()))
        writer.writeheader()
        writer.writerows(payment_options)

    # 6. exchange_rates.csv
    exchange_rates = [
        {"date": "2026-09-01", "from_currency": "USD", "to_currency": "EUR", "rate": "0.92"},
        {"date": "2026-09-01", "from_currency": "USD", "to_currency": "GBP", "rate": "0.78"},
        {"date": "2026-09-01", "from_currency": "EUR", "to_currency": "USD", "rate": "1.087"},
        {"date": "2026-09-01", "from_currency": "GBP", "to_currency": "USD", "rate": "1.282"},
        {"date": "2026-09-15", "from_currency": "USD", "to_currency": "EUR", "rate": "0.93"},
        {"date": "2026-09-15", "from_currency": "USD", "to_currency": "GBP", "rate": "0.79"}
    ]

    with open(dataset_dir / "exchange_rates.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(exchange_rates[0].keys()))
        writer.writeheader()
        writer.writerows(exchange_rates)

    # 7. sample_requests.csv (25 requests)
    sample_requests = [
        {
            "request_id": f"s_req_{i:03d}",
            "user_id": f"usr_{101 + (i % 5)}",
            "request_date": "2026-09-12",
            "item_name": f"Sample Item {i}",
            "amount": f"{(150 + (i * 85)):.2f}",
            "currency": "USD",
            "desired_completion_date": "2026-11-30",
            "allows_partial_payment": "true",
            "urgency": "medium",
            # Solved benchmark attributes
            "decision": "BUY_NOW" if i % 3 == 0 else ("WAIT" if i % 3 == 1 else "DO_NOT_BUY"),
            "recommended_option_id": f"opt_{i:03d}" if i % 3 != 2 else "NONE",
            "payment_type": "FULL" if i % 3 == 0 else ("INSTALLMENTS" if i % 3 == 1 else "NONE"),
            "start_date": "2026-09-12" if i % 3 == 0 else ("2026-09-22" if i % 3 == 1 else "2026-09-12"),
            "total_cost": f"{(150 + (i * 85)):.2f}" if i % 3 != 2 else "0.00",
            "installments_count": "1" if i % 3 == 0 else ("4" if i % 3 == 1 else "0"),
            "installment_amount": f"{(150 + (i * 85)):.2f}" if i % 3 == 0 else (f"{((150 + (i * 85)) / 4):.2f}" if i % 3 == 1 else "0.00"),
            "safety_cushion_min": f"{(1200 - i * 15):.2f}",
            "explanation": f"Sample ground truth explanation for item {i}."
        }
        for i in range(1, 26)
    ]

    with open(dataset_dir / "sample_requests.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(sample_requests[0].keys()))
        writer.writeheader()
        writer.writerows(sample_requests)

    # 8. prediction_requests.csv (250 requests)
    prediction_requests = [
        {
            "request_id": f"req_{i:03d}",
            "user_id": f"usr_{101 + (i % 5)}",
            "request_date": "2026-09-12",
            "item_name": f"Purchase Item #{i}",
            "amount": f"{Decimal(str(100 + (i * 27) % 1800)):.2f}",
            "currency": ["USD", "EUR", "GBP"][i % 3],
            "desired_completion_date": "2026-11-30",
            "allows_partial_payment": "true" if i % 4 != 0 else "false",
            "urgency": ["low", "medium", "high"][i % 3]
        }
        for i in range(1, 251)
    ]

    with open(dataset_dir / "prediction_requests.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(prediction_requests[0].keys()))
        writer.writeheader()
        writer.writerows(prediction_requests)

    print("Dataset generated successfully with 25 sample requests and 250 prediction requests!")

if __name__ == "__main__":
    generate_dataset()
