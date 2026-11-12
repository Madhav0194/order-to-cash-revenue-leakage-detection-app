
import csv
import random
import sys
from pathlib import Path
from datetime import date, timedelta
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import SEED, DATA_DIR

RAW_DIR = DATA_DIR / "raw"


def read_csv(filename):
    with (RAW_DIR / filename).open(
        "r", newline="", encoding="utf-8"
    ) as f:
        return list(csv.DictReader(f))


def save_csv(filename, rows):
    if not rows:
        raise ValueError(f"No records for {filename}")

    with (RAW_DIR / filename).open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=rows[0].keys()
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} rows: {filename}")


def generate_orders():
    rng = random.Random(SEED + 1)

    quotes = read_csv("quotes.csv")
    quote_lines = read_csv("quote_lines.csv")

    lines_by_quote = defaultdict(list)

    for line in quote_lines:
        lines_by_quote[line["quote_id"]].append(line)

    accepted = [
        q for q in quotes
        if q["status"] == "ACCEPTED"
    ]

    accepted.sort(key=lambda q: q["quote_id"])

    orders = []
    order_lines = []
    line_counter = 1

    for index, quote in enumerate(accepted, start=1):
        quote_id = quote["quote_id"]
        order_id = f"SO-2026-{index:06d}"

        quote_date = date.fromisoformat(
            quote["quote_date"]
        )

        valid_until = date.fromisoformat(
            quote["valid_until"]
        )

        order_date = quote_date + timedelta(
            days=rng.randint(1, 15)
        )

        if order_date > valid_until:
            raise ValueError(
                f"Order after quote expiry: {quote_id}"
            )

        orders.append({
            "order_id": order_id,
            "quote_id": quote_id,
            "account_id": quote["account_id"],
            "order_date": order_date.isoformat(),
            "status": "CREATED"
        })

        for quote_line in lines_by_quote[quote_id]:
            order_lines.append({
                "order_line_id": (
                    f"OL-2026-{line_counter:06d}"
                ),
                "order_id": order_id,
                "quote_line_id": (
                    quote_line["quote_line_id"]
                ),
                "quantity": quote_line["quantity"],
                "unit_price": quote_line["unit_price"]
            })

            line_counter += 1

    save_csv("sales_orders.csv", orders)
    save_csv("order_lines.csv", order_lines)

    print("\nOrder generation complete")
    print("Accepted quotes:", len(accepted))
    print("Sales orders:", len(orders))
    print("Order lines:", len(order_lines))


if __name__ == "__main__":
    generate_orders()
