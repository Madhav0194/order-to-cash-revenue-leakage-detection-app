
"""Independently validate the Step 13 SQLite database."""

import csv
import json
import sqlite3

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "data" / "full"

DB = (
    ROOT / "database" / "order_to_cash_full.db"
)

REPORT = (
    ROOT / "reports" / "validation_full_database.json"
)

FILES = {
    "Account": "raw/accounts.csv",
    "Quote": "raw/quotes.csv",
    "QuoteLine": "raw/quote_lines.csv",
    "SalesOrder": "raw/sales_orders.csv",
    "OrderLine": "raw/order_lines.csv",
    "Shipment": "raw/shipments.csv",
    "ShipmentLine": "raw/shipment_lines.csv",
    "Invoice": "raw/invoices.csv",
    "InvoiceLine": "raw/invoice_lines.csv",
    "Payment": "raw/payments.csv",
    "PaymentAllocation": "raw/payment_allocations.csv",
    "Dispute": "raw/disputes.csv",
    "DisputeTimeline": "raw/dispute_timeline.csv",
    "StatusEvent": "raw/status_events.csv",
    "InvoiceBalance": "processed/invoice_balances.csv",
}

KEYS = {
    "Quote": "quote_id",
    "SalesOrder": "order_id",
    "Shipment": "shipment_id",
    "Invoice": "invoice_id",
    "Payment": "payment_id",
    "Dispute": "dispute_id",
}

ALLOWED = {
    "Quote": {
        "": {"DRAFT"},
        "DRAFT": {"SENT"},
        "SENT": {
            "ACCEPTED", "REJECTED", "EXPIRED"
        },
    },
    "SalesOrder": {
        "": {"CREATED"},
        "CREATED": {"CONFIRMED"},
        "CONFIRMED": {"FULFILLED"},
    },
    "Shipment": {
        "": {"CREATED"},
        "CREATED": {"DISPATCHED"},
        "DISPATCHED": {"DELIVERED"},
    },
    "Invoice": {
        "": {"ISSUED"},
        "ISSUED": {"PARTIALLY_PAID", "PAID"},
        "PARTIALLY_PAID": {"PAID", "OVERDUE"},
    },
    "Payment": {
        "": {"RECEIVED"},
        "RECEIVED": {"ALLOCATED"},
    },
    "Dispute": {
        "": {"OPEN"},
        "OPEN": {"INVESTIGATING"},
        "INVESTIGATING": {"RESOLVED"},
    },
}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    require(
        DB.is_file(),
        f"Database missing: {DB}"
    )

    manifest = json.loads(
        (BASE / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    report = {
        "database": str(DB),
        "seed": manifest["seed"],
        "counts": {},
        "checks": [],
    }

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    try:
        con.execute("PRAGMA foreign_keys = ON")

        require(
            con.execute(
                "PRAGMA foreign_keys"
            ).fetchone()[0] == 1,
            "Foreign keys disabled"
        )

        require(
            con.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0] == "ok",
            "Integrity check failed"
        )

        require(
            not con.execute(
                "PRAGMA foreign_key_check"
            ).fetchall(),
            "Foreign key violation"
        )

        report["checks"].extend([
            "sqlite_integrity",
            "foreign_keys",
        ])

        tables = {
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table'"
            )
        }

        require(
            tables == set(FILES),
            "Unexpected/missing tables: "
            f"{tables ^ set(FILES)}"
        )

        # Compare all imported rows against CSVs.
        for table, relative in FILES.items():
            n = con.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0]

            require(
                n == manifest["files"][relative]["rows"],
                f"Count mismatch: {table}"
            )

            report["counts"][table] = n

            with (BASE / relative).open(
                newline="", encoding="utf-8"
            ) as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames

                selected = ", ".join(
                    '"' + c + '"' for c in cols
                )

                cursor = con.execute(
                    f'SELECT {selected} FROM "{table}" '
                    "ORDER BY rowid"
                )

                for idx, (csv_row, db_row) in enumerate(
                    zip(reader, cursor), 1
                ):
                    for col in cols:
                        left = csv_row[col]
                        right = db_row[col]

                        if right is None:
                            right = ""

                        if col in {
                            "unit_price",
                            "amount",
                            "allocated_amount",
                            "disputed_amount",
                            "invoice_total",
                            "outstanding_balance",
                        }:
                            same = (
                                Decimal(str(left))
                                == Decimal(str(right))
                            )
                        else:
                            same = (
                                str(left) == str(right)
                            )

                        require(
                            same,
                            "CSV/DB mismatch: "
                            f"{table} row {idx} "
                            f"field {col}: "
                            f"{left!r} != {right!r}"
                        )

        report["checks"].append(
            "all_csv_rows_equal_database"
        )

        # Verify required full-scale counts.
        targets = [
            ("Quote", 10000),
            ("SalesOrder", 7000),
            ("Invoice", 8000),
            ("Payment", 15000),
            ("Dispute", 400),
            ("StatusEvent", 125000),
        ]

        for table, expected in targets:
            require(
                report["counts"][table] == expected,
                f"Target count: {table}"
            )

        report["checks"].append(
            "exact_full_scale_counts"
        )

        # Validate polymorphic event references.
        for kind, key in KEYS.items():
            n = con.execute(
                f"""
                SELECT COUNT(*)
                FROM StatusEvent e
                LEFT JOIN "{kind}" p
                    ON p."{key}" = e.entity_id
                WHERE e.entity_type = ?
                  AND p."{key}" IS NULL
                """,
                (kind,),
            ).fetchone()[0]

            require(
                n == 0,
                f"Orphan status events: {kind}: {n}"
            )

        report["checks"].append(
            "polymorphic_event_references"
        )

        # Validate status transitions and final status.
        histories = defaultdict(list)

        for r in con.execute(
            """
            SELECT entity_type, entity_id,
                   old_status, new_status, event_time
            FROM StatusEvent
            ORDER BY entity_type, entity_id,
                     event_time, event_id
            """
        ):
            histories[
                (r["entity_type"], r["entity_id"])
            ].append(r)

        for (kind, entity), rows in histories.items():
            previous = ""

            for r in rows:
                require(
                    r["old_status"] == previous,
                    f"Broken status chain: "
                    f"{kind} {entity}"
                )

                require(
                    r["new_status"]
                    in ALLOWED[kind].get(
                        previous, set()
                    ),
                    f"Invalid status transition: "
                    f"{kind} {entity}: "
                    f"{previous} -> {r['new_status']}"
                )

                previous = r["new_status"]

        for kind, key in KEYS.items():
            for r in con.execute(
                f'SELECT "{key}" AS id, status '
                f'FROM "{kind}"'
            ):
                history = histories.get(
                    (kind, r["id"])
                )

                require(
                    history,
                    f"Missing event history: "
                    f"{kind} {r['id']}"
                )

                require(
                    history[-1]["new_status"]
                    == r["status"],
                    f"Final status mismatch: "
                    f"{kind} {r['id']}"
                )

        report["checks"].append(
            "event_transitions_and_final_status"
        )

        # Verify dispute timeline.
        dispute_query = """
            SELECT
                d.dispute_id,
                d.opened_at AS source_opened,
                d.status,
                t.opened_at,
                t.investigating_at,
                t.resolved_at
            FROM Dispute d
            JOIN DisputeTimeline t
              ON d.dispute_id = t.dispute_id
        """

        for r in con.execute(dispute_query):
            require(
                r["source_opened"] == r["opened_at"],
                "Dispute opening mismatch: "
                f"{r['dispute_id']}"
            )

            expected = {
                "OPEN": 1,
                "INVESTIGATING": 2,
                "RESOLVED": 3,
            }[r["status"]]

            history = histories[
                ("Dispute", r["dispute_id"])
            ]

            require(
                len(history) == expected,
                "Dispute event count: "
                f"{r['dispute_id']}"
            )

            timestamps = [
                r["opened_at"],
                r["investigating_at"],
                r["resolved_at"],
            ][:expected]

            for event, day in zip(
                history, timestamps
            ):
                require(
                    event["event_time"][:10] == day,
                    "Dispute event date mismatch: "
                    f"{r['dispute_id']}"
                )

            require(
                (r["investigating_at"] is not None)
                == (expected >= 2),
                "Investigation date mismatch"
            )

            require(
                (r["resolved_at"] is not None)
                == (expected == 3),
                "Resolution date mismatch"
            )

        report["checks"].append(
            "dispute_timeline"
        )

        # Reconcile financial data using Decimal.
        totals = defaultdict(
            lambda: Decimal("0.00")
        )

        paid = defaultdict(
            lambda: Decimal("0.00")
        )

        paid_per_payment = defaultdict(
            lambda: Decimal("0.00")
        )

        for r in con.execute(
            "SELECT invoice_id, quantity, unit_price "
            "FROM InvoiceLine"
        ):
            totals[r["invoice_id"]] += (
                Decimal(str(r["unit_price"]))
                * r["quantity"]
            )

        for r in con.execute(
            "SELECT payment_id, invoice_id, "
            "allocated_amount FROM PaymentAllocation"
        ):
            amount = Decimal(
                str(r["allocated_amount"])
            )

            paid[r["invoice_id"]] += amount
            paid_per_payment[
                r["payment_id"]
            ] += amount

        for r in con.execute(
            "SELECT payment_id, amount FROM Payment"
        ):
            require(
                paid_per_payment[r["payment_id"]]
                == Decimal(str(r["amount"])),
                "Payment allocation mismatch: "
                f"{r['payment_id']}"
            )

        for r in con.execute(
            "SELECT * FROM InvoiceBalance"
        ):
            iid = r["invoice_id"]

            require(
                totals[iid]
                == Decimal(str(r["invoice_total"])),
                f"Invoice total mismatch: {iid}"
            )

            require(
                paid[iid]
                == Decimal(str(r["allocated_amount"])),
                f"Invoice allocation mismatch: {iid}"
            )

            require(
                totals[iid] - paid[iid]
                == Decimal(
                    str(r["outstanding_balance"])
                ),
                f"Invoice receivable mismatch: {iid}"
            )

            require(
                Decimal(
                    str(r["outstanding_balance"])
                ) >= 0,
                f"Negative receivable: {iid}"
            )

        report["checks"].append(
            "financial_reconciliation"
        )

        # Ensure ground truth is not in operational DB.
        require(
            "ground_truth" not in tables
            and "GroundTruth" not in tables,
            "Ground-truth table leaked"
        )

        event_columns = {
            r[1]
            for r in con.execute(
                "PRAGMA table_info(StatusEvent)"
            )
        }

        require(
            "ground_truth" not in event_columns,
            "Ground-truth field leaked into events"
        )

        labelled_count = con.execute(
            "SELECT COUNT(*) FROM StatusEvent "
            "WHERE issue_type <> ''"
        ).fetchone()[0]

        require(
            labelled_count == 0,
            "Clean baseline contains labelled events"
        )

        report["checks"].append(
            "no_ground_truth_leakage"
        )

        REPORT.parent.mkdir(
            parents=True, exist_ok=True
        )

        REPORT.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8"
        )

        print("FULL DATABASE VALIDATION PASSED")

        for table in [
            "Quote",
            "SalesOrder",
            "Invoice",
            "Payment",
            "StatusEvent",
            "Dispute",
        ]:
            print(
                f"{table}: "
                f"{report['counts'][table]:,}"
            )

        print("Foreign key violations: 0")
        print("Dispute timeline mismatches: 0")
        print("Financial reconciliation issues: 0")
        print("Ground truth leakage: 0")
        print("Report:", REPORT)

    finally:
        con.close()


if __name__ == "__main__":
    main()

