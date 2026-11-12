
"""Load validated Step 12 CSVs into a NEW SQLite database atomically."""

import csv
import hashlib
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "data" / "full"
SCHEMA = ROOT / "database" / "schema_full.sql"
DEST = ROOT / "database" / "order_to_cash_full.db"
TEMP = ROOT / "database" / "order_to_cash_full.db.building"

LOAD_ORDER = [
    ("raw/accounts.csv", "Account"),
    ("raw/quotes.csv", "Quote"),
    ("raw/quote_lines.csv", "QuoteLine"),
    ("raw/sales_orders.csv", "SalesOrder"),
    ("raw/order_lines.csv", "OrderLine"),
    ("raw/shipments.csv", "Shipment"),
    ("raw/shipment_lines.csv", "ShipmentLine"),
    ("raw/invoices.csv", "Invoice"),
    ("raw/invoice_lines.csv", "InvoiceLine"),
    ("raw/payments.csv", "Payment"),
    ("raw/payment_allocations.csv", "PaymentAllocation"),
    ("raw/disputes.csv", "Dispute"),
    ("raw/dispute_timeline.csv", "DisputeTimeline"),
    ("raw/status_events.csv", "StatusEvent"),
    ("processed/invoice_balances.csv", "InvoiceBalance"),
]


def verify_manifest():
    manifest_path = BASE / "manifest.json"

    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    if manifest.get("seed") != 20261022:
        raise ValueError("Unexpected dataset seed")

    for relative, details in manifest["files"].items():
        path = BASE / relative

        digest = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

        if digest != details["sha256"]:
            raise ValueError(
                f"CSV checksum mismatch: {relative}"
            )

    expected = {
        name for name, _ in LOAD_ORDER
    }

    if not expected.issubset(manifest["files"]):
        raise ValueError(
            "Manifest missing database source files"
        )

    truth = (
        BASE / "ground_truth" / "ground_truth.csv"
    )

    with truth.open(
        newline="", encoding="utf-8"
    ) as f:
        if any(csv.DictReader(f)):
            raise ValueError(
                "Expected clean baseline; "
                "ground truth is not empty"
            )

    return manifest


def load_table(
    connection,
    relative,
    table,
    expected_rows
):
    path = BASE / relative

    with path.open(
        newline="", encoding="utf-8"
    ) as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames

        if not columns:
            raise ValueError(
                f"Empty CSV header: {relative}"
            )

        db_columns = {
            r[1]
            for r in connection.execute(
                f'PRAGMA table_info("{table}")'
            )
        }

        if set(columns) != db_columns:
            raise ValueError(
                f"Column mismatch in {relative}: "
                f"{set(columns) ^ db_columns}"
            )

        if "ground_truth" in columns:
            raise ValueError(
                f"Label leakage in operational file: "
                f"{relative}"
            )

        quoted = ", ".join(
            '"' + c + '"' for c in columns
        )

        marks = ", ".join(
            "?" for _ in columns
        )

        statement = (
            f'INSERT INTO "{table}" '
            f"({quoted}) VALUES ({marks})"
        )

        count = 0
        batch = []

        for row in reader:
            batch.append(
                tuple(
                    None
                    if (
                        row[c] == ""
                        and c in (
                            "investigating_at",
                            "resolved_at"
                        )
                    )
                    else row[c]
                    for c in columns
                )
            )

            if len(batch) == 1000:
                connection.executemany(
                    statement, batch
                )
                count += len(batch)
                batch.clear()

        if batch:
            connection.executemany(
                statement, batch
            )
            count += len(batch)

    if count != expected_rows:
        raise ValueError(
            f"Count mismatch for {table}: "
            f"{count} != {expected_rows}"
        )

    print(f"{table:20s} {count:>8,}")


def main():
    manifest = verify_manifest()

    if not SCHEMA.is_file():
        raise FileNotFoundError(
            f"Create schema first: {SCHEMA}"
        )

    DEST.parent.mkdir(
        parents=True, exist_ok=True
    )

    if TEMP.exists():
        TEMP.unlink()

    try:
        con = sqlite3.connect(TEMP)

        try:
            con.execute(
                "PRAGMA foreign_keys = ON"
            )

            con.executescript(
                SCHEMA.read_text(encoding="utf-8")
            )

            if con.execute(
                "PRAGMA foreign_keys"
            ).fetchone()[0] != 1:
                raise RuntimeError(
                    "SQLite foreign keys are disabled"
                )

            con.execute("BEGIN")

            for relative, table in LOAD_ORDER:
                load_table(
                    con,
                    relative,
                    table,
                    manifest["files"][relative]["rows"]
                )

            violations = con.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

            if violations:
                raise ValueError(
                    "SQLite foreign-key check failed"
                )

            integrity = con.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]

            if integrity != "ok":
                raise ValueError(
                    "SQLite integrity check failed"
                )

            con.commit()

        except Exception:
            con.rollback()
            raise

        finally:
            con.close()

        os.replace(TEMP, DEST)

        print("\nDATABASE LOAD PASSED")
        print("Database:", DEST)
        print(
            "Ground truth: excluded from "
            "operational database"
        )

    except Exception:
        if TEMP.exists():
            TEMP.unlink()
        raise


if __name__ == "__main__":
    main()

