"""
Configuration module for Buy or Wait financial reasoning engine.
"""
import os
import logging
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATASET_DIR = Path(os.getenv("DATASET_DIR", BASE_DIR / "dataset"))
MEDIA_IMAGES_DIR = DATASET_DIR / "media" / "images"
OUTPUT_PATH = Path(os.getenv("OUTPUT_PATH", BASE_DIR / "output.csv"))
CACHE_DIR = BASE_DIR / ".cache"
LOGS_DIR = BASE_DIR / "logs"

# Simulation constants
SIMULATION_HORIZON_DAYS = 90
MAX_WAIT_SEARCH_DAYS = 60
DEFAULT_SAFETY_RESERVE = 500.0
DEFAULT_FLEXIBLE_REDUCTION_LIMIT = 0.50  # Up to 50% reduction if needed

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

def setup_logging(name: str = "buy_or_wait", log_file: str = "pipeline.log") -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    
    # Avoid duplicate handlers
    if not logger.handlers:
        c_handler = logging.StreamHandler()
        c_format = logging.Formatter("[%(levelname)s] %(asctime)s - %(name)s: %(message)s", datefmt="%H:%M:%S")
        c_handler.setFormatter(c_format)
        logger.addHandler(c_handler)
        
        f_handler = logging.FileHandler(LOGS_DIR / log_file, encoding="utf-8")
        f_format = logging.Formatter("%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s")
        f_handler.setFormatter(f_format)
        logger.addHandler(f_handler)
        
    return logger
