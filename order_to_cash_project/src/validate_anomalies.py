
import csv
import sys
from pathlib import Path
from decimal import Decimal
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DATA_DIR

DATA = DATA_DIR / "anomalous"
TRUTH = DATA_DIR / "ground_truth"


def load(folder, filename):
    path = folder / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Missing required file: {path}"
        )

    with path.open(
        newline="", encoding="utf-8"
    ) as f:
        return list(csv.DictReader(f))


def detect():
    shipment_lines = load(
        DATA, "shipment_lines.csv"
    )
    invoice_lines = load(
        DATA, "invoice_lines.csv"
    )
    invoices = load(DATA, "invoices.csv")
    payments = load(DATA, "payments.csv")
    allocations = load(
        DATA, "payment_allocations.csv"
    )
    balances = load(
        DATA, "invoice_balances.csv"
    )
    events = load(DATA, "status_events.csv")
    disputes = load(DATA, "disputes.csv")

    findings = set()

    # ---------------------------------
    # 1. Invoice exceeds fulfillment
    # ---------------------------------

    fulfilled = defaultdict(int)
    billed = defaultdict(int)

    for row in shipment_lines:
        fulfilled[row["order_line_id"]] += int(
            row["quantity"]
        )

    for row in invoice_lines:
        billed[row["order_line_id"]] += int(
            row["quantity"]
        )

    for row in invoice_lines:
        line_id = row["order_line_id"]

        if billed[line_id] > fulfilled[line_id]:
            findings.add((
                "INVOICE_EXCEEDS_FULFILLMENT",
                row["invoice_line_id"]
            ))

    # ---------------------------------
    # 2. Duplicate payment allocation
    # ---------------------------------

    allocation_keys = Counter(
        (
            a["payment_id"],
            a["invoice_id"],
            a["allocated_amount"]
        )
        for a in allocations
    )

    for allocation in allocations:
        key = (
            allocation["payment_id"],
            allocation["invoice_id"],
            allocation["allocated_amount"]
        )

        if allocation_keys[key] > 1:
            findings.add((
                "DUPLICATE_PAYMENT_ALLOCATION",
                allocation["allocation_id"]
            ))

    # ---------------------------------
    # 3. Closed order with unpaid invoice
    # ---------------------------------

    invoice_to_order = {
        invoice["invoice_id"]: invoice["order_id"]
        for invoice in invoices
    }

    unpaid_orders = set()

    for balance in balances:
        outstanding = Decimal(
            balance["outstanding_balance"]
        )

        if outstanding > 0:
            unpaid_orders.add(
                invoice_to_order[
                    balance["invoice_id"]
                ]
            )

    for event in events:
        if (
            event["entity_type"] == "SalesOrder"
            and event["new_status"] == "CLOSED"
            and event["entity_id"] in unpaid_orders
        ):
            findings.add((
                "CLOSED_ORDER_WITH_UNPAID_INVOICE",
                event["entity_id"]
            ))

    # ---------------------------------
    # 4. Skipped shipment status
    # ---------------------------------

    shipment_history = defaultdict(list)

    for event in events:
        if event["entity_type"] == "Shipment":
            shipment_history[
                event["entity_id"]
            ].append(event)

    for shipment_id, history in shipment_history.items():
        history.sort(
            key=lambda e: e["event_time"]
        )

        states = [
            event["new_status"]
            for event in history
        ]

        if (
            "DELIVERED" in states
            and "DISPATCHED" not in states
        ):
            findings.add((
                "SKIPPED_REQUIRED_STATUS",
                shipment_id
            ))

    # ---------------------------------
    # 5. Dispute receivable mismatch
    # ---------------------------------

    payment_map = {
        p["payment_id"]: p
        for p in payments
    }

    invoice_totals = defaultdict(
        lambda: Decimal("0.00")
    )

    for line in invoice_lines:
        invoice_totals[
            line["invoice_id"]
        ] += (
            Decimal(line["unit_price"])
            * int(line["quantity"])
        )

    allocated = defaultdict(
        lambda: Decimal("0.00")
    )

    for allocation in allocations:
        if allocation["payment_id"] not in payment_map:
            raise ValueError(
                "Unknown payment reference: "
                + allocation["payment_id"]
            )

        allocated[
            allocation["invoice_id"]
        ] += Decimal(
            allocation["allocated_amount"]
        )

    active_disputes = {
        dispute["invoice_id"]
        for dispute in disputes
        if dispute["status"] in (
            "OPEN", "INVESTIGATING"
        )
    }

    for balance in balances:
        invoice_id = balance["invoice_id"]

        if invoice_id not in active_disputes:
            continue

        expected = (
            invoice_totals[invoice_id]
            - allocated[invoice_id]
        )

        actual = Decimal(
            balance["outstanding_balance"]
        )

        if actual != expected:
            findings.add((
                "DISPUTE_RECEIVABLE_MISMATCH",
                invoice_id
            ))

    return findings


def main():
    findings = detect()

    truth = load(
        TRUTH, "ground_truth.csv"
    )

    expected = {
        (
            row["issue_type"],
            row["entity_id"]
        )
        for row in truth
    }

    true_positives = findings & expected
    false_negatives = expected - findings
    extra_findings = findings - expected

    tp = len(true_positives)
    fn = len(false_negatives)
    extra = len(extra_findings)

    recall = (
        tp / (tp + fn)
        if (tp + fn) > 0 else 0
    )

    provisional_precision = (
        tp / (tp + extra)
        if (tp + extra) > 0 else 0
    )

    print("\nANOMALY VALIDATION SUMMARY")
    print("--------------------------")
    print("Ground truth:", len(expected))
    print("Detected records:", len(findings))
    print("Matched:", tp)
    print("Missed:", fn)
    print("Additional findings:", extra)

    print("\nGROUND TRUTH RESULTS")
    print("--------------------------")

    for issue, entity in sorted(expected):
        status = (
            "DETECTED"
            if (issue, entity) in findings
            else "MISSED"
        )

        print(
            f"{status}: {issue} | {entity}"
        )

    print("\nALL DETECTED FINDINGS")
    print("--------------------------")

    for issue, entity in sorted(findings):
        label = (
            "MATCHED"
            if (issue, entity) in expected
            else "UNMATCHED"
        )

        print(
            f"{label}: {issue} | {entity}"
        )

    print("\nADDITIONAL FINDINGS DETAILS")
    print("--------------------------")

    if extra_findings:
        for issue, entity in sorted(extra_findings):
            print(
                f"EXTRA: {issue} | {entity}"
            )
    else:
        print("No additional findings.")

    print("\nDETECTION METRICS")
    print("--------------------------")
    print(
        f"Injected-anomaly recall: {recall:.2%}"
    )
    print(
        "Provisional precision: "
        f"{provisional_precision:.2%}"
    )
    print("False negatives:", fn)
    print("Unmatched findings:", extra)

    print(
        "\nNote: Unmatched findings are not "
        "necessarily false positives."
    )

    if false_negatives:
        raise ValueError(
            "Not all injected anomalies detected"
        )

    print("\nGround-truth recall PASSED")


if __name__ == "__main__":
    main()
