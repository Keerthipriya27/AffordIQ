"""
Schema and data validation for input CSV files.
"""
from typing import Dict, List, Set
from pathlib import Path
import csv
from code.config import setup_logging

logger = setup_logging(__name__)

REQUIRED_FILES_AND_COLUMNS: Dict[str, Set[str]] = {
    "profiles.csv": {
        "user_id", "base_currency", "current_balance", "minimum_balance_to_keep",
        "monthly_essential_expenses", "monthly_flexible_expenses"
    },
    "events.csv": {
        "event_id", "user_id", "event_type", "category", "amount",
        "currency", "frequency", "start_date", "status"
    },
    "messages.csv": {
        "message_id", "user_id", "timestamp", "sender", "content"
    },
    "images.csv": {
        "image_id", "user_id", "file_path", "document_type"
    },
    "payment_options.csv": {
        "option_id", "request_id", "payment_type", "installments_count",
        "interest_rate_apr", "fee_fixed", "fee_percentage", "interval_days"
    },
    "exchange_rates.csv": {
        "date", "from_currency", "to_currency", "rate"
    }
}

class SchemaValidator:
    @staticmethod
    def validate_dataset_directory(dataset_dir: Path) -> bool:
        """
        Validates presence and required columns of all input CSVs.
        """
        if not dataset_dir.exists():
            logger.error(f"Dataset directory does not exist: {dataset_dir}")
            return False

        all_valid = True
        for filename, required_cols in REQUIRED_FILES_AND_COLUMNS.items():
            file_path = dataset_dir / filename
            if not file_path.exists():
                logger.error(f"Missing required CSV file: {file_path}")
                all_valid = False
                continue

            try:
                with open(file_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.reader(f)
                    header = next(reader, None)
                    if not header:
                        logger.error(f"File {filename} is empty!")
                        all_valid = False
                        continue
                    
                    found_cols = {col.strip() for col in header}
                    missing_cols = required_cols - found_cols
                    if missing_cols:
                        logger.error(f"File {filename} is missing columns: {missing_cols}")
                        all_valid = False
                    else:
                        logger.debug(f"Schema validated for {filename} ({len(found_cols)} cols)")
            except Exception as e:
                logger.error(f"Failed to read or parse {file_path}: {e}")
                all_valid = False

        return all_valid
