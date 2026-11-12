
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


def save_csv(filename, rows, fields):
    with (RAW_DIR / filename).open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=fields
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} rows: {filename}")


def generate_shipments():
    rng = random.Random(SEED + 2)

    orders = read_csv("sales_orders.csv")
    order_lines = read_csv("order_lines.csv")

    shipments = []
    shipment_lines = []

    shipment_counter = 1
    shipment_line_counter = 1

    lines_by_order = defaultdict(list)

    for line in order_lines:
        lines_by_order[line["order_id"]].append(line)

    for order in orders:
        order_id = order["order_id"]
        order_date = date.fromisoformat(
            order["order_date"]
        )

        lines = lines_by_order[order_id]

        scenario = rng.choices(
            ["FULL", "PARTIAL", "NONE"],
            weights=[70, 25, 5],
            k=1
        )[0]

        if scenario == "NONE":
            continue

        # Full orders can have two shipments.
        shipment_count = (
            2 if scenario == "FULL"
            and rng.random() < 0.25
            else 1
        )

        # Determine the total quantity to fulfill
        # for each order line before splitting.
        target_quantities = {}

        for line in lines:
            ordered_qty = int(line["quantity"])

            if scenario == "PARTIAL":
                target_qty = max(
                    1,
                    int(
                        ordered_qty *
                        rng.uniform(0.3, 0.8)
                    )
                )
            else:
                target_qty = ordered_qty

            target_quantities[
                line["order_line_id"]
            ] = target_qty

        for shipment_index in range(shipment_count):
            current_lines = []

            for line in lines:
                line_id = line["order_line_id"]
                target_qty = target_quantities[line_id]

                if shipment_count == 2:
                    first_qty = target_qty // 2

                    if shipment_index == 0:
                        delivered_qty = first_qty
                    else:
                        delivered_qty = (
                            target_qty - first_qty
                        )
                else:
                    delivered_qty = target_qty

                # Never create zero-quantity lines.
                if delivered_qty <= 0:
                    continue

                current_lines.append({
                    "order_line_id": line_id,
                    "quantity": delivered_qty
                })

            # Do not create empty shipments.
            if not current_lines:
                continue

            shipment_id = (
                f"SHP-2026-{shipment_counter:06d}"
            )

            shipment_date = order_date + timedelta(
                days=3 + shipment_index * 5
                + rng.randint(0, 7)
            )

            shipments.append({
                "shipment_id": shipment_id,
                "order_id": order_id,
                "shipment_date": shipment_date.isoformat(),
                "status": "DELIVERED"
            })

            for item in current_lines:
                shipment_lines.append({
                    "shipment_line_id": (
                        f"SL-2026-"
                        f"{shipment_line_counter:06d}"
                    ),
                    "shipment_id": shipment_id,
                    "order_line_id": (
                        item["order_line_id"]
                    ),
                    "quantity": item["quantity"]
                })

                shipment_line_counter += 1

            shipment_counter += 1

    save_csv(
        "shipments.csv",
        shipments,
        [
            "shipment_id",
            "order_id",
            "shipment_date",
            "status"
        ]
    )

    save_csv(
        "shipment_lines.csv",
        shipment_lines,
        [
            "shipment_line_id",
            "shipment_id",
            "order_line_id",
            "quantity"
        ]
    )

    # Validate cumulative shipped quantities.
    shipped_by_line = defaultdict(int)

    for shipment_line in shipment_lines:
        shipped_by_line[
            shipment_line["order_line_id"]
        ] += shipment_line["quantity"]

    over_shipped = 0
    partial_lines = 0

    for line in order_lines:
        ordered = int(line["quantity"])
        shipped = shipped_by_line[
            line["order_line_id"]
        ]

        if shipped > ordered:
            over_shipped += 1

        if 0 < shipped < ordered:
            partial_lines += 1

    print("\nShipment generation complete")
    print("Shipments:", len(shipments))
    print("Shipment lines:", len(shipment_lines))
    print("Over-shipped lines:", over_shipped)
    print("Partially shipped lines:", partial_lines)

    if over_shipped:
        raise ValueError(
            "Shipment validation failed!"
        )

    print("Shipment validation PASSED")


if __name__ == "__main__":
    generate_shipments()
