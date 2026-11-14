
import csv
import json
import shutil
import sys
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DATA_DIR, REPORT_CUTOFF

RAW = DATA_DIR / "raw"
PROCESSED = DATA_DIR / "processed"
ANOMALOUS = DATA_DIR / "anomalous"
TRUTH = DATA_DIR / "ground_truth"

FILES = [
    "accounts.csv",
    "quotes.csv",
    "quote_lines.csv",
    "sales_orders.csv",
    "order_lines.csv",
    "shipments.csv",
    "shipment_lines.csv",
    "invoices.csv",
    "invoice_lines.csv",
    "payments.csv",
    "payment_allocations.csv",
    "disputes.csv",
    "status_events.csv"
]

labels = []


def read_csv(path):
    with path.open(
        newline="", encoding="utf-8"
    ) as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    path.parent.mkdir(
        parents=True, exist_ok=True
    )

    with path.open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=fields
        )
        writer.writeheader()
        writer.writerows(rows)


def save_rows(name, rows):
    if not rows:
        raise ValueError(
            f"Cannot save empty table: {name}"
        )

    write_csv(
        ANOMALOUS / name,
        rows,
        list(rows[0].keys())
    )


def add_label(issue_type, entity_type, entity_id,
              related_id, rule, expected):
    labels.append({
        "anomaly_id": (
            f"ANM-2026-{len(labels)+1:06d}"
        ),
        "issue_type": issue_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "related_id": related_id,
        "expected_rule": rule,
        "expected_decision": expected,
        "ground_truth": 1
    })


def copy_baseline():
    ANOMALOUS.mkdir(
        parents=True, exist_ok=True
    )
    TRUTH.mkdir(
        parents=True, exist_ok=True
    )

    for name in FILES:
        source = RAW / name

        if not source.exists():
            raise FileNotFoundError(source)

        shutil.copy2(
            source, ANOMALOUS / name
        )

    shutil.copy2(
        PROCESSED / "invoice_balances.csv",
        ANOMALOUS / "invoice_balances.csv"
    )


def inject_overbilling():
    shipments = read_csv(
        ANOMALOUS / "shipment_lines.csv"
    )
    invoice_lines = read_csv(
        ANOMALOUS / "invoice_lines.csv"
    )

    fulfilled = defaultdict(int)
    billed = defaultdict(int)

    for row in shipments:
        fulfilled[row["order_line_id"]] += int(
            row["quantity"]
        )

    for row in invoice_lines:
        billed[row["order_line_id"]] += int(
            row["quantity"]
        )

    candidates = [
        row for row in invoice_lines
        if fulfilled[row["order_line_id"]] > 0
    ]

    if not candidates:
        raise ValueError(
            "No invoice lines available"
        )

    row = candidates[0]
    line_id = row["order_line_id"]

    # Increase the billed quantity so its
    # cumulative total exceeds fulfillment.
    excess = (
        fulfilled[line_id] - billed[line_id] + 1
    )

    row["quantity"] = str(
        int(row["quantity"]) + excess
    )

    save_rows("invoice_lines.csv", invoice_lines)

    add_label(
        "INVOICE_EXCEEDS_FULFILLMENT",
        "InvoiceLine",
        row["invoice_line_id"],
        line_id,
        "Total invoiced quantity must not exceed "
        "delivered quantity",
        "FLAG_OVERBILLING"
    )


def inject_duplicate_allocation():
    allocations = read_csv(
        ANOMALOUS / "payment_allocations.csv"
    )

    if not allocations:
        raise ValueError(
            "No payment allocations available"
        )

    source = allocations[0]
    duplicate = dict(source)

    # Unique PK but duplicate business allocation.
    duplicate["allocation_id"] = (
        "PAL-2026-999999"
    )

    if any(
        x["allocation_id"] == duplicate["allocation_id"]
        for x in allocations
    ):
        raise ValueError(
            "Reserved allocation ID already exists"
        )

    allocations.append(duplicate)

    save_rows(
        "payment_allocations.csv",
        allocations
    )

    add_label(
        "DUPLICATE_PAYMENT_ALLOCATION",
        "PaymentAllocation",
        duplicate["allocation_id"],
        source["allocation_id"],
        "One payment allocation must not be "
        "recorded twice",
        "FLAG_DUPLICATE_ALLOCATION"
    )


def inject_invalid_closure():
    balances = read_csv(
        ANOMALOUS / "invoice_balances.csv"
    )
    invoices = read_csv(
        ANOMALOUS / "invoices.csv"
    )
    events = read_csv(
        ANOMALOUS / "status_events.csv"
    )

    invoice_map = {
        i["invoice_id"]: i for i in invoices
    }

    candidates = [
        b for b in balances
        if Decimal(
            b["outstanding_balance"]
        ) > 0
    ]

    if not candidates:
        raise ValueError(
            "No unpaid invoices available"
        )

    chosen = candidates[0]
    invoice = invoice_map[
        chosen["invoice_id"]
    ]
    order_id = invoice["order_id"]

    order_history = [
        e for e in events
        if e["entity_type"] == "SalesOrder"
        and e["entity_id"] == order_id
    ]

    order_history.sort(
        key=lambda e: e["event_time"]
    )

    last = order_history[-1]

    # Add a CLOSED event after the last order event.
    # This is deliberately invalid while receivables
    # remain outstanding.
    cutoff = datetime.fromisoformat(
        REPORT_CUTOFF + "T23:00:00"
    )

    close_time = cutoff

    if datetime.fromisoformat(
        last["event_time"]
    ) >= close_time:
        raise ValueError(
            "No time available for closure anomaly"
        )

    new_event = dict(last)

    new_event["event_id"] = (
        "EVT-2026-999998"
    )
    new_event["old_status"] = last["new_status"]
    new_event["new_status"] = "CLOSED"
    new_event["event_time"] = (
        close_time.isoformat(
            timespec="seconds"
        )
    )
    new_event["issue_type"] = ""
    new_event["ground_truth"] = "0"

    events.append(new_event)
    save_rows("status_events.csv", events)

    add_label(
        "CLOSED_ORDER_WITH_UNPAID_INVOICE",
        "SalesOrder",
        order_id,
        chosen["invoice_id"],
        "Order cannot close while invoice "
        "balance is outstanding",
        "FLAG_INVALID_CLOSURE"
    )


def inject_skipped_status():
    events = read_csv(
        ANOMALOUS / "status_events.csv"
    )

    # Find a shipment with all three states.
    by_shipment = defaultdict(list)

    for event in events:
        if event["entity_type"] == "Shipment":
            by_shipment[
                event["entity_id"]
            ].append(event)

    selected_id = None
    selected_event = None

    for shipment_id, history in sorted(
        by_shipment.items()
    ):
        states = {
            e["new_status"] for e in history
        }

        if states == {
            "CREATED", "DISPATCHED", "DELIVERED"
        }:
            selected_id = shipment_id
            selected_event = next(
                e for e in history
                if e["new_status"] == "DISPATCHED"
            )
            break

    if selected_id is None:
        raise ValueError(
            "No eligible shipment history"
        )

    removed_id = selected_event["event_id"]

    events = [
        e for e in events
        if e["event_id"] != removed_id
    ]

    # CREATED -> DELIVERED now skips DISPATCHED.
    save_rows("status_events.csv", events)

    add_label(
        "SKIPPED_REQUIRED_STATUS",
        "Shipment",
        selected_id,
        removed_id,
        "Shipment must pass through DISPATCHED "
        "before DELIVERED",
        "FLAG_INVALID_TRANSITION"
    )


def inject_dispute_receivable_mismatch():
    disputes = read_csv(
        ANOMALOUS / "disputes.csv"
    )
    balances = read_csv(
        ANOMALOUS / "invoice_balances.csv"
    )

    active = [
        d for d in disputes
        if d["status"] in (
            "OPEN", "INVESTIGATING"
        )
    ]

    if not active:
        raise ValueError(
            "No active disputes available"
        )

    dispute = active[0]
    invoice_id = dispute["invoice_id"]

    balance = next(
        b for b in balances
        if b["invoice_id"] == invoice_id
    )

    # Deliberately reduce the receivable without
    # any payment or authorized credit adjustment.
    original = Decimal(
        balance["outstanding_balance"]
    )
    disputed = Decimal(
        dispute["disputed_amount"]
    )

    incorrect = original - disputed

    balance["outstanding_balance"] = str(
        incorrect.quantize(Decimal("0.01"))
    )

    save_rows(
        "invoice_balances.csv", balances
    )

    add_label(
        "DISPUTE_RECEIVABLE_MISMATCH",
        "Invoice",
        invoice_id,
        dispute["dispute_id"],
        "Dispute alone cannot reduce receivables "
        "without a documented credit adjustment",
        "FLAG_RECEIVABLE_MISMATCH"
    )


def validate_injection():
    if len(labels) != 5:
        raise ValueError(
            "Expected exactly five anomaly labels"
        )

    types = [
        x["issue_type"] for x in labels
    ]

    if len(set(types)) != 5:
        raise ValueError(
            "Duplicate anomaly types"
        )

    for name in FILES:
        if not (ANOMALOUS / name).exists():
            raise FileNotFoundError(name)

    # Preserve unique physical primary keys.
    keys = {
        "invoice_lines.csv": "invoice_line_id",
        "payment_allocations.csv": "allocation_id",
        "status_events.csv": "event_id"
    }

    for filename, key in keys.items():
        rows = read_csv(
            ANOMALOUS / filename
        )

        ids = [row[key] for row in rows]

        if len(ids) != len(set(ids)):
            raise ValueError(
                f"Duplicate primary key: {filename}"
            )


def main():
    copy_baseline()

    inject_overbilling()
    inject_duplicate_allocation()
    inject_invalid_closure()
    inject_skipped_status()
    inject_dispute_receivable_mismatch()

    validate_injection()

    fields = [
        "anomaly_id",
        "issue_type",
        "entity_type",
        "entity_id",
        "related_id",
        "expected_rule",
        "expected_decision",
        "ground_truth"
    ]

    write_csv(
        TRUTH / "ground_truth.csv",
        labels, fields
    )

    with (
        TRUTH / "ground_truth.json"
    ).open("w", encoding="utf-8") as f:
        json.dump(
            labels, f, indent=2
        )

    print("\nANOMALY INJECTION SUMMARY")
    print("-------------------------")

    for label in labels:
        print(
            label["anomaly_id"],
            label["issue_type"],
            label["entity_id"]
        )

    print("\nTotal anomalies:", len(labels))
    print("Clean baseline: data/raw/")
    print("Anomaly data: data/anomalous/")
    print("Labels: data/ground_truth/")
    print("Anomaly injection PASSED")


if __name__ == "__main__":
    main()
