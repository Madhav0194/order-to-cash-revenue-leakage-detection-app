
"""Step 14: Detect and evaluate full-scale SQLite anomalies."""

import json
import sqlite3
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CLEAN = ROOT / "database" / "order_to_cash_full.db"
ANOMALOUS = ROOT / "database" / "order_to_cash_anomalous.db"

TRUTH = (
    ROOT / "data" / "full" / "ground_truth"
    / "sqlite_anomalies.json"
)

REPORT = (
    ROOT / "reports" / "full_anomaly_evaluation.json"
)

D = lambda x: Decimal(str(x))


def detect(database):
    con = sqlite3.connect(
        f"file:{database.as_posix()}?mode=ro",
        uri=True
    )
    con.row_factory = sqlite3.Row

    findings = set()

    try:
        # Rule 1: Aggregate billed quantities must
        # not exceed delivered quantities.
        rows = con.execute("""
            WITH delivered AS (
                SELECT order_line_id,
                       SUM(quantity) AS quantity
                FROM ShipmentLine
                GROUP BY order_line_id
            ),
            billed AS (
                SELECT order_line_id,
                       SUM(quantity) AS quantity
                FROM InvoiceLine
                GROUP BY order_line_id
            )
            SELECT b.order_line_id
            FROM billed b
            LEFT JOIN delivered d
              ON b.order_line_id=d.order_line_id
            WHERE b.quantity >
                  COALESCE(d.quantity, 0)
        """).fetchall()

        for row in rows:
            findings.add((
                "INVOICE_EXCEEDS_FULFILLMENT",
                row["order_line_id"]
            ))

        # Rule 2: Detect duplicate allocation
        # groups as one business incident.
        rows = con.execute("""
            SELECT payment_id, invoice_id,
                   allocated_amount, COUNT(*) AS n
            FROM PaymentAllocation
            GROUP BY payment_id, invoice_id,
                     allocated_amount
            HAVING COUNT(*) > 1
        """).fetchall()

        for row in rows:
            case_id = (
                f"{row['payment_id']}|"
                f"{row['invoice_id']}|"
                f"{D(row['allocated_amount']):.2f}"
            )

            findings.add((
                "DUPLICATE_PAYMENT_ALLOCATION",
                case_id
            ))

        # Rule 3: A CLOSED order must not have
        # an outstanding invoice.
        rows = con.execute("""
            SELECT DISTINCT e.entity_id
            FROM StatusEvent e
            JOIN Invoice i
              ON i.order_id=e.entity_id
            JOIN InvoiceBalance b
              ON b.invoice_id=i.invoice_id
            WHERE e.entity_type='SalesOrder'
              AND e.new_status='CLOSED'
              AND b.outstanding_balance > 0
        """).fetchall()

        for row in rows:
            findings.add((
                "CLOSED_ORDER_WITH_UNPAID_INVOICE",
                row["entity_id"]
            ))

        # Rule 4: A delivered shipment must
        # contain a DISPATCHED transition.
        rows = con.execute("""
            SELECT DISTINCT delivered.entity_id
            FROM StatusEvent delivered
            WHERE delivered.entity_type='Shipment'
              AND delivered.new_status='DELIVERED'
              AND NOT EXISTS (
                  SELECT 1
                  FROM StatusEvent dispatched
                  WHERE dispatched.entity_type='Shipment'
                    AND dispatched.entity_id=delivered.entity_id
                    AND dispatched.new_status='DISPATCHED'
                    AND dispatched.event_time <=
                        delivered.event_time
              )
        """).fetchall()

        for row in rows:
            findings.add((
                "SKIPPED_REQUIRED_STATUS",
                row["entity_id"]
            ))

        # Rule 5: Active-dispute receivables must
        # reconcile to invoices minus allocations.
        # Use Decimal for exact currency comparison.
        rows = con.execute("""
            SELECT DISTINCT d.invoice_id,
                   b.outstanding_balance
            FROM Dispute d
            JOIN InvoiceBalance b
              ON b.invoice_id=d.invoice_id
            WHERE d.status IN ('OPEN', 'INVESTIGATING')
        """).fetchall()

        for row in rows:
            iid = row["invoice_id"]

            invoice_lines = con.execute("""
                SELECT quantity, unit_price
                FROM InvoiceLine
                WHERE invoice_id=?
            """, (iid,)).fetchall()

            allocations = con.execute("""
                SELECT allocated_amount
                FROM PaymentAllocation
                WHERE invoice_id=?
            """, (iid,)).fetchall()

            total = sum(
                (
                    D(line["unit_price"])
                    * line["quantity"]
                    for line in invoice_lines
                ),
                Decimal("0.00")
            )

            allocated = sum(
                (
                    D(a["allocated_amount"])
                    for a in allocations
                ),
                Decimal("0.00")
            )

            actual = D(row["outstanding_balance"])

            if actual != total - allocated:
                findings.add((
                    "DISPUTE_RECEIVABLE_MISMATCH",
                    iid
                ))

    finally:
        con.close()

    return findings


def evaluate():
    for path in (CLEAN, ANOMALOUS, TRUTH):
        if not path.exists():
            raise FileNotFoundError(
                f"Required file missing: {path}"
            )

    truth_data = json.loads(
        TRUTH.read_text(encoding="utf-8")
    )

    expected = {
        (case["type"], case["case_id"])
        for case in truth_data["cases"]
    }

    clean_findings = detect(CLEAN)
    findings = detect(ANOMALOUS)

    matched = expected & findings
    missed = expected - findings
    extra = findings - expected

    tp = len(matched)
    fp = len(extra)
    fn = len(missed)

    precision = (
        tp / (tp + fp)
        if tp + fp else 0.0
    )

    recall = (
        tp / (tp + fn)
        if tp + fn else 0.0
    )

    f1 = (
        2 * precision * recall
        / (precision + recall)
        if precision + recall else 0.0
    )

    print("\nFULL-SCALE ANOMALY EVALUATION")
    print("--------------------------------")

    print("Clean baseline findings:", len(clean_findings))
    print("Ground-truth cases:", len(expected))
    print("Detected cases:", len(findings))
    print("Matched cases:", tp)
    print("Missed cases:", fn)
    print("Additional cases:", fp)

    print("\nDETECTION BY ANOMALY TYPE")
    print("--------------------------------")

    all_types = sorted(
        {type_name for type_name, _ in expected | findings}
    )

    for type_name in all_types:
        expected_count = sum(
            t == type_name for t, _ in expected
        )
        detected_count = sum(
            t == type_name for t, _ in findings
        )
        matched_count = sum(
            t == type_name for t, _ in matched
        )

        print(
            f"{type_name}: "
            f"expected={expected_count}, "
            f"detected={detected_count}, "
            f"matched={matched_count}"
        )

    print("\nMATCHED CASES")
    print("--------------------------------")
    for issue_type, case_id in sorted(matched):
        print(f"MATCHED: {issue_type} | {case_id}")

    if missed:
        print("\nMISSED CASES")
        for issue_type, case_id in sorted(missed):
            print(f"MISSED: {issue_type} | {case_id}")

    if extra:
        print("\nADDITIONAL CASES")
        for issue_type, case_id in sorted(extra):
            print(f"EXTRA: {issue_type} | {case_id}")

    if clean_findings:
        print("\nCLEAN BASELINE FINDINGS")
        for issue_type, case_id in sorted(clean_findings):
            print(f"BASELINE: {issue_type} | {case_id}")

    print("\nMETRICS")
    print("--------------------------------")
    print(f"Precision: {precision:.2%}")
    print(f"Recall:    {recall:.2%}")
    print(f"F1-score:  {f1:.2%}")

    report = {
        "evaluation_unit": "anomaly_case",
        "ground_truth_count": len(expected),
        "clean_baseline_findings": [
            {"type": t, "case_id": i}
            for t, i in sorted(clean_findings)
        ],
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "f1_score": f1,
        "matched": [
            {"type": t, "case_id": i}
            for t, i in sorted(matched)
        ],
        "missed": [
            {"type": t, "case_id": i}
            for t, i in sorted(missed)
        ],
        "additional": [
            {"type": t, "case_id": i}
            for t, i in sorted(extra)
        ]
    }

    REPORT.parent.mkdir(
        parents=True, exist_ok=True
    )

    REPORT.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8"
    )

    print("\nReport:", REPORT)

    passed = (
        len(expected) == 5
        and not clean_findings
        and not missed
        and not extra
    )

    if passed:
        print("\nFULL-SCALE ANOMALY EVALUATION PASSED")
    else:
        print("\nANOMALY EVALUATION REQUIRES REVIEW")
        raise SystemExit(1)


if __name__ == "__main__":
    evaluate()
