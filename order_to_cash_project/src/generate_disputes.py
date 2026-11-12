
import csv
import random
import sys
from pathlib import Path
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import SEED, DATA_DIR, REPORT_CUTOFF

RAW = DATA_DIR / "raw"
PROCESSED = DATA_DIR / "processed"
CUTOFF = date.fromisoformat(REPORT_CUTOFF)


def money(value):
    return Decimal(str(value)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} rows: {path.name}")


def generate_disputes():
    rng = random.Random(SEED + 5)

    invoices = read_csv(RAW / "invoices.csv")
    balances = read_csv(
        PROCESSED / "invoice_balances.csv"
    )

    invoice_map = {
        row["invoice_id"]: row for row in invoices
    }

    eligible = [
        row for row in balances
        if money(row["outstanding_balance"]) > 0
        and date.fromisoformat(
            invoice_map[row["invoice_id"]]["invoice_date"]
        ) <= CUTOFF
    ]

    # Select about 20% of invoices with
    # outstanding balances for disputes.
    dispute_count = min(
        len(eligible),
        max(1, round(len(eligible) * 0.20))
    ) if eligible else 0

    selected = rng.sample(eligible, dispute_count)

    disputes = []
    exceptions = []

    for index, balance in enumerate(selected, 1):
        invoice_id = balance["invoice_id"]
        invoice = invoice_map[invoice_id]

        outstanding = money(
            balance["outstanding_balance"]
        )

        disputed_amount = money(
            outstanding * Decimal(
                str(rng.uniform(0.25, 1.0))
            )
        )

        disputed_amount = min(
            outstanding,
            max(Decimal("0.01"), disputed_amount)
        )

        invoice_date = date.fromisoformat(
            invoice["invoice_date"]
        )

        days_available = (CUTOFF - invoice_date).days

        opened_at = invoice_date + timedelta(
            days=rng.randint(0, days_available)
        )

        status = rng.choice([
            "OPEN",
            "INVESTIGATING",
            "RESOLVED"
        ])

        dispute_id = f"DSP-2026-{index:06d}"

        disputes.append({
            "dispute_id": dispute_id,
            "invoice_id": invoice_id,
            "opened_at": opened_at.isoformat(),
            "disputed_amount": str(disputed_amount),
            "status": status
        })

        if status != "RESOLVED":
            exceptions.append({
                "dispute_id": dispute_id,
                "invoice_id": invoice_id,
                "issue_type": "OPEN_DISPUTE",
                "disputed_amount": str(disputed_amount),
                "outstanding_balance": str(outstanding),
                "status": status
            })

    write_csv(
        RAW / "disputes.csv",
        disputes,
        [
            "dispute_id", "invoice_id",
            "opened_at", "disputed_amount",
            "status"
        ]
    )

    write_csv(
        PROCESSED / "dispute_exceptions.csv",
        exceptions,
        [
            "dispute_id", "invoice_id",
            "issue_type", "disputed_amount",
            "outstanding_balance", "status"
        ]
    )

    # Validate references and amounts.
    invoice_ids = set(invoice_map)

    assert len({
        d["dispute_id"] for d in disputes
    }) == len(disputes)

    assert all(
        d["invoice_id"] in invoice_ids
        for d in disputes
    )

    balance_map = {
        b["invoice_id"]: money(
            b["outstanding_balance"]
        )
        for b in balances
    }

    assert all(
        Decimal("0") < money(d["disputed_amount"])
        <= balance_map[d["invoice_id"]]
        for d in disputes
    )

    assert all(
        date.fromisoformat(d["opened_at"]) <= CUTOFF
        for d in disputes
    )

    total_disputed = sum(
        (
            money(d["disputed_amount"])
            for d in disputes
        ),
        Decimal("0.00")
    )

    print("\nDISPUTE GENERATION SUMMARY")
    print("--------------------------")
    print("Eligible invoices:", len(eligible))
    print("Disputes:", len(disputes))
    print("Open/investigating:", len(exceptions))
    print("Total disputed (INR):", total_disputed)
    print("Reporting cutoff:", REPORT_CUTOFF)
    print("Dispute validation PASSED")


if __name__ == "__main__":
    generate_disputes()
