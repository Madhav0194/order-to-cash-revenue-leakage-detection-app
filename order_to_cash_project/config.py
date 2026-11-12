
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

SEED = 20261022

DATASET_CONFIG = {
    "starter": {
        "quotes": 100,
        "orders": 70,
        "invoices": 80,
        "payments": 150
    },
    "full": {
        "quotes": 10000,
        "orders": 7000,
        "invoices": 8000,
        "payments": 15000
    }
}

CURRENCY = "INR"
REPORT_CUTOFF = "2026-10-31"

for folder in [
    DATA_DIR / "raw",
    DATA_DIR / "processed",
    DATA_DIR / "ground_truth",
    BASE_DIR / "reports"
]:
    folder.mkdir(parents=True, exist_ok=True)

print("Project configuration loaded successfully!")

