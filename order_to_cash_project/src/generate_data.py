
import sys
import csv
import random
from pathlib import Path
from datetime import date, timedelta
from decimal import Decimal

from faker import Faker

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DATASET_CONFIG, SEED, DATA_DIR

fake = Faker("en_IN")

PRODUCTS = [
    ("Laptop", 45000),
    ("Monitor", 12000),
    ("Keyboard", 1500),
    ("Mouse", 700),
    ("Printer", 18000),
    ("Server", 95000),
    ("Router", 4500),
    ("SSD", 6000)
]

INDUSTRIES = [
    "Technology", "Retail", "Healthcare",
    "Manufacturing", "Education", "Finance"
]

def save_csv(filename, records):
    path = DATA_DIR / "raw" / filename
    if not records:
        raise ValueError(f"No records generated for {filename}")

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)

    print(f"Saved {len(records)} rows: {path}")

def generate(scale="starter"):
    if scale not in DATASET_CONFIG:
        raise ValueError("Scale must be starter or full")

    random.seed(SEED)
    Faker.seed(SEED)

    config = DATASET_CONFIG[scale]
    quote_count = config["quotes"]
    order_count = config["orders"]

    account_count = max(10, quote_count // 5)

    accounts = []
    quotes = []
    quote_lines = []

    start_date = date(2026, 1, 1)

    for i in range(1, account_count + 1):
        created = start_date + timedelta(
            days=random.randint(0, 30)
        )

        accounts.append({
            "account_id": f"ACC-2026-{i:06d}",
            "account_name": fake.company(),
            "industry": random.choice(INDUSTRIES),
            "created_at": created.isoformat(),
            "status": "ACTIVE"
        })

    # Exactly order_count accepted quotes.
    accepted_indices = set(
        random.sample(range(1, quote_count + 1), order_count)
    )

    line_counter = 1

    for i in range(1, quote_count + 1):
        account = random.choice(accounts)

        quote_date = start_date + timedelta(
            days=random.randint(31, 180)
        )

        valid_until = quote_date + timedelta(days=30)

        if i in accepted_indices:
            status = "ACCEPTED"
        else:
            status = random.choice([
                "REJECTED", "EXPIRED", "SENT"
            ])

        quote_id = f"QTE-2026-{i:06d}"

        quotes.append({
            "quote_id": quote_id,
            "account_id": account["account_id"],
            "quote_date": quote_date.isoformat(),
            "valid_until": valid_until.isoformat(),
            "status": status
        })

        num_lines = random.randint(1, 4)
        selected_products = random.sample(
            PRODUCTS, num_lines
        )

        for product_name, base_price in selected_products:
            quantity = random.randint(1, 100)
            price = Decimal(base_price) * Decimal(
                str(random.choice([0.90, 1.00, 1.10]))
            )

            quote_lines.append({
                "quote_line_id": f"QL-2026-{line_counter:06d}",
                "quote_id": quote_id,
                "product_name": product_name,
                "quantity": quantity,
                "unit_price": f"{price:.2f}"
            })

            line_counter += 1

    save_csv("accounts.csv", accounts)
    save_csv("quotes.csv", quotes)
    save_csv("quote_lines.csv", quote_lines)

    print("\nGeneration summary")
    print("Accounts:", len(accounts))
    print("Quotes:", len(quotes))
    print("Accepted quotes:", len(accepted_indices))
    print("Quote lines:", len(quote_lines))
    print("Seed:", SEED)

if __name__ == "__main__":
    scale = sys.argv[1] if len(sys.argv) > 1 else "starter"
    generate(scale)
