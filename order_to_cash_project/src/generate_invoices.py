
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
    path = RAW_DIR / filename

    with path.open(
        "r", newline="", encoding="utf-8"
    ) as f:
        return list(csv.DictReader(f))


def save_csv(filename, rows, fields):
    path = RAW_DIR / filename

    with path.open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=fields
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} rows: {filename}")


def generate_invoices():

    rng = random.Random(SEED + 3)

    orders = read_csv("sales_orders.csv")
    order_lines = read_csv("order_lines.csv")
    shipments = read_csv("shipments.csv")
    shipment_lines = read_csv("shipment_lines.csv")

    shipment_map = {
        s["shipment_id"]: s
        for s in shipments
    }

    lines_by_order = defaultdict(list)

    for line in order_lines:
        lines_by_order[
            line["order_id"]
        ].append(line)

    # Collect delivered quantities and dates.
    deliveries = defaultdict(list)

    for shipment_line in shipment_lines:

        shipment = shipment_map[
            shipment_line["shipment_id"]
        ]

        if shipment["status"] != "DELIVERED":
            continue

        line_id = shipment_line["order_line_id"]

        deliveries[line_id].append({
            "date": date.fromisoformat(
                shipment["shipment_date"]
            ),
            "quantity": int(
                shipment_line["quantity"]
            )
        })

    invoices = []
    invoice_lines = []

    invoice_counter = 1
    line_counter = 1

    for order in orders:

        order_id = order["order_id"]
        lines = lines_by_order[order_id]

        eligible_lines = []

        for line in lines:
            line_id = line["order_line_id"]

            delivered = sum(
                d["quantity"]
                for d in deliveries[line_id]
            )

            if delivered > 0:
                eligible_lines.append(
                    (line, delivered)
                )

        if not eligible_lines:
            continue

        # 25% chance of two invoices.
        invoice_count = (
            2 if rng.random() < 0.25
            else 1
        )

        # Apply underbilling once per order line,
        # then split the billable quantity.
        billed_targets = {}

        for line, delivered in eligible_lines:

            if rng.random() < 0.12:
                billed = max(
                    0, int(delivered * 0.8)
                )
            else:
                billed = delivered

            billed_targets[
                line["order_line_id"]
            ] = billed

        # Use a delivery cutoff for each invoice.
        delivery_dates = sorted({
            d["date"]
            for line, _ in eligible_lines
            for d in deliveries[
                line["order_line_id"]
            ]
        })

        final_delivery_date = max(
            delivery_dates
        )

        for invoice_index in range(invoice_count):

            billed_lines = []

            for line, delivered in eligible_lines:

                line_id = line["order_line_id"]
                target = billed_targets[line_id]

                if invoice_count == 2:
                    first = target // 2

                    quantity = (
                        first
                        if invoice_index == 0
                        else target - first
                    )
                else:
                    quantity = target

                if quantity <= 0:
                    continue

                billed_lines.append({
                    "order_line_id": line_id,
                    "quantity": quantity,
                    "unit_price": line["unit_price"]
                })

            if not billed_lines:
                continue

            invoice_id = (
                f"INV-2026-"
                f"{invoice_counter:06d}"
            )

            # Both invoices occur after fulfillment
            # so no invoice bills future deliveries.
            invoice_date = (
                final_delivery_date
                + timedelta(
                    days=1 + invoice_index
                    + rng.randint(0, 3)
                )
            )

            due_date = invoice_date + timedelta(
                days=rng.choice(
                    [15, 30, 45, 60]
                )
            )

            invoices.append({
                "invoice_id": invoice_id,
                "order_id": order_id,
                "invoice_date": (
                    invoice_date.isoformat()
                ),
                "due_date": (
                    due_date.isoformat()
                ),
                "status": "ISSUED"
            })

            for item in billed_lines:

                invoice_lines.append({
                    "invoice_line_id": (
                        f"IL-2026-"
                        f"{line_counter:06d}"
                    ),
                    "invoice_id": invoice_id,
                    "order_line_id": (
                        item["order_line_id"]
                    ),
                    "quantity": item["quantity"],
                    "unit_price": item["unit_price"]
                })

                line_counter += 1

            invoice_counter += 1

    save_csv(
        "invoices.csv",
        invoices,
        [
            "invoice_id",
            "order_id",
            "invoice_date",
            "due_date",
            "status"
        ]
    )

    save_csv(
        "invoice_lines.csv",
        invoice_lines,
        [
            "invoice_line_id",
            "invoice_id",
            "order_line_id",
            "quantity",
            "unit_price"
        ]
    )

    # Validate invoiced quantities.
    fulfilled_by_line = defaultdict(int)

    for line_id, events in deliveries.items():
        fulfilled_by_line[line_id] = sum(
            event["quantity"]
            for event in events
        )

    billed_by_line = defaultdict(int)

    for line in invoice_lines:
        billed_by_line[
            line["order_line_id"]
        ] += line["quantity"]

    overbilled = 0
    underbilled = 0

    for line_id, fulfilled in (
        fulfilled_by_line.items()
    ):
        billed = billed_by_line[line_id]

        if billed > fulfilled:
            overbilled += 1

        if billed < fulfilled:
            underbilled += 1

    print("\nInvoice Generation Summary")
    print("--------------------------")
    print("Invoices:", len(invoices))
    print("Invoice lines:", len(invoice_lines))
    print("Overbilled lines:", overbilled)
    print("Underbilled lines:", underbilled)

    if overbilled:
        raise ValueError(
            "Invoice quantity validation failed"
        )

    print("Invoice validation PASSED")


if __name__ == "__main__":
    generate_invoices()
