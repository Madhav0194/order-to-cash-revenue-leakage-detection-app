
import csv
import random
import sys
from pathlib import Path
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import SEED, DATA_DIR, REPORT_CUTOFF

RAW = DATA_DIR / "raw"
PROCESSED = DATA_DIR / "processed"

CENT = Decimal("0.01")


def money(value):
    return Decimal(str(value)).quantize(
        CENT, rounding=ROUND_HALF_UP
    )


def read_csv(filename):
    with (RAW / filename).open(
        newline="", encoding="utf-8"
    ) as f:
        return list(csv.DictReader(f))


def save_csv(folder, filename, rows, fields):
    folder.mkdir(parents=True, exist_ok=True)

    with (folder / filename).open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=fields
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} rows: {filename}")


def generate_payments():
    rng = random.Random(SEED + 4)
    cutoff = date.fromisoformat(REPORT_CUTOFF)

    invoices = read_csv("invoices.csv")
    invoice_lines = read_csv("invoice_lines.csv")
    orders = read_csv("sales_orders.csv")

    order_map = {
        row["order_id"]: row for row in orders
    }

    invoice_totals = defaultdict(
        lambda: Decimal("0.00")
    )

    for line in invoice_lines:
        invoice_totals[line["invoice_id"]] += (
            int(line["quantity"])
            * money(line["unit_price"])
        )

    payments = []
    allocations = []
    balances = []

    payment_counter = 1
    allocation_counter = 1

    payment_fields = [
        "payment_id", "account_id",
        "payment_date", "amount", "status"
    ]

    allocation_fields = [
        "allocation_id", "payment_id",
        "invoice_id", "allocated_amount"
    ]

    balance_fields = [
        "invoice_id", "account_id",
        "invoice_total", "allocated_amount",
        "outstanding_balance", "due_date",
        "days_overdue", "aging_bucket",
        "payment_status"
    ]

    for invoice in invoices:
        invoice_id = invoice["invoice_id"]
        order = order_map[invoice["order_id"]]
        account_id = order["account_id"]

        total = money(invoice_totals[invoice_id])
        invoice_date = date.fromisoformat(
            invoice["invoice_date"]
        )
        due_date = date.fromisoformat(
            invoice["due_date"]
        )

        # Payment scenarios are business behavior,
        # not anomaly ground-truth labels.
        scenario = rng.choices(
            ["FULL", "PARTIAL", "UNPAID", "SPLIT"],
            weights=[55, 25, 10, 10],
            k=1
        )[0]

        target_paid = Decimal("0.00")

        if scenario in ("FULL", "SPLIT"):
            target_paid = total
        elif scenario == "PARTIAL":
            target_paid = money(
                total * Decimal(
                    str(rng.uniform(0.25, 0.85))
                )
            )

        # Do not record future payments as of cutoff.
        if invoice_date > cutoff:
            target_paid = Decimal("0.00")

        payment_parts = []

        if target_paid > 0:
            if scenario == "SPLIT":
                first = money(
                    target_paid * Decimal("0.40")
                )
                second = target_paid - first

                payment_parts = [
                    part for part in (first, second)
                    if part > 0
                ]
            else:
                payment_parts = [target_paid]

        paid_total = Decimal("0.00")

        for part_index, amount in enumerate(
            payment_parts
        ):
            payment_date = invoice_date + timedelta(
                days=5 + part_index * 7
                + rng.randint(0, 20)
            )

            if payment_date > cutoff:
                continue

            payment_id = (
                f"PAY-2026-{payment_counter:06d}"
            )

            payments.append({
                "payment_id": payment_id,
                "account_id": account_id,
                "payment_date": (
                    payment_date.isoformat()
                ),
                "amount": str(money(amount)),
                "status": "ALLOCATED"
            })

            allocations.append({
                "allocation_id": (
                    f"PAL-2026-"
                    f"{allocation_counter:06d}"
                ),
                "payment_id": payment_id,
                "invoice_id": invoice_id,
                "allocated_amount": (
                    str(money(amount))
                )
            })

            paid_total += amount
            payment_counter += 1
            allocation_counter += 1

        outstanding = money(total - paid_total)

        if outstanding == 0:
            payment_status = "PAID"
        elif paid_total > 0:
            payment_status = "PARTIALLY_PAID"
        elif due_date < cutoff:
            payment_status = "OVERDUE"
        else:
            payment_status = "ISSUED"

        days_overdue = (
            max(0, (cutoff - due_date).days)
            if outstanding > 0 else 0
        )

        if outstanding == 0:
            aging_bucket = "PAID"
        elif days_overdue == 0:
            aging_bucket = "CURRENT"
        elif days_overdue <= 30:
            aging_bucket = "1-30"
        elif days_overdue <= 60:
            aging_bucket = "31-60"
        elif days_overdue <= 90:
            aging_bucket = "61-90"
        else:
            aging_bucket = "90+"

        balances.append({
            "invoice_id": invoice_id,
            "account_id": account_id,
            "invoice_total": str(total),
            "allocated_amount": str(
                money(paid_total)
            ),
            "outstanding_balance": str(
                outstanding
            ),
            "due_date": due_date.isoformat(),
            "days_overdue": days_overdue,
            "aging_bucket": aging_bucket,
            "payment_status": payment_status
        })

    save_csv(
        RAW, "payments.csv",
        payments, payment_fields
    )

    save_csv(
        RAW, "payment_allocations.csv",
        allocations, allocation_fields
    )

    save_csv(
        PROCESSED, "invoice_balances.csv",
        balances, balance_fields
    )

    total_invoiced = sum(
        (money(x["invoice_total"]) for x in balances),
        Decimal("0.00")
    )

    total_paid = sum(
        (money(x["allocated_amount"]) for x in balances),
        Decimal("0.00")
    )

    total_outstanding = sum(
        (
            money(x["outstanding_balance"])
            for x in balances
        ),
        Decimal("0.00")
    )

    payment_ids = {
        p["payment_id"] for p in payments
    }

    invoice_ids = {
        i["invoice_id"] for i in invoices
    }

    assert all(
        a["payment_id"] in payment_ids
        and a["invoice_id"] in invoice_ids
        for a in allocations
    )

    assert total_invoiced == (
        total_paid + total_outstanding
    )

    assert all(
        money(b["outstanding_balance"]) >= 0
        for b in balances
    )

    print("\nPAYMENT GENERATION SUMMARY")
    print("--------------------------")
    print("Invoices:", len(invoices))
    print("Payments:", len(payments))
    print("Allocations:", len(allocations))
    print("Total invoiced (INR):", total_invoiced)
    print("Total allocated (INR):", total_paid)
    print("Total outstanding (INR):",
          total_outstanding)
    print("Reporting cutoff:", REPORT_CUTOFF)
    print("Payment reconciliation PASSED")


if __name__ == "__main__":
    generate_payments()
