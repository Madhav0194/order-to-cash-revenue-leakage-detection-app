
"""Step 14: Inject five anomalies into a COPY of the clean SQLite DB."""

import json
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "database" / "order_to_cash_full.db"
ANOMALOUS = ROOT / "database" / "order_to_cash_anomalous.db"
TRUTH = (
    ROOT / "data" / "full" / "ground_truth"
    / "sqlite_anomalies.json"
)

D = lambda x: Decimal(str(x))


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def inject(con):
    truth = []
    used_invoices = set()

    # 1. Overbilling: increase one invoice line beyond
    # the total delivered quantity for its order line.
    candidate = require(
        con.execute("""
            SELECT il.invoice_line_id, il.order_line_id,
                   il.invoice_id, il.quantity,
                   COALESCE((
                       SELECT SUM(sl.quantity)
                       FROM ShipmentLine sl
                       WHERE sl.order_line_id = il.order_line_id
                   ), 0) AS delivered,
                   (
                       SELECT SUM(il2.quantity)
                       FROM InvoiceLine il2
                       WHERE il2.order_line_id = il.order_line_id
                   ) AS billed
            FROM InvoiceLine il
            WHERE EXISTS (
                SELECT 1 FROM ShipmentLine sl
                WHERE sl.order_line_id = il.order_line_id
            )
            ORDER BY il.invoice_line_id
            LIMIT 1
        """).fetchone(),
        "No invoice line available for overbilling"
    )

    new_quantity = (
        candidate["quantity"]
        + max(1, candidate["delivered"] - candidate["billed"] + 1)
    )

    con.execute(
        "UPDATE InvoiceLine SET quantity=? "
        "WHERE invoice_line_id=?",
        (new_quantity, candidate["invoice_line_id"])
    )
    used_invoices.add(candidate["invoice_id"])
    truth.append({
        "type": "INVOICE_EXCEEDS_FULFILLMENT",
        "case_id": candidate["order_line_id"],
        "injected_record": candidate["invoice_line_id"]
    })

    # 2. Duplicate an allocation, preferably for a
    # different invoice from the overbilling case.
    allocation = require(
        con.execute("""
            SELECT a.*
            FROM PaymentAllocation a
            WHERE a.invoice_id <> ?
            ORDER BY a.allocation_id
            LIMIT 1
        """, (candidate["invoice_id"],)).fetchone(),
        "No allocation available for duplication"
    )

    duplicate_id = "PAL-STEP14-DUPLICATE"

    require(
        not con.execute(
            "SELECT 1 FROM PaymentAllocation "
            "WHERE allocation_id=?",
            (duplicate_id,)
        ).fetchone(),
        "Duplicate test ID already exists"
    )

    con.execute("""
        INSERT INTO PaymentAllocation
        (allocation_id, payment_id, invoice_id,
         allocated_amount)
        VALUES (?, ?, ?, ?)
    """, (
        duplicate_id,
        allocation["payment_id"],
        allocation["invoice_id"],
        allocation["allocated_amount"]
    ))

    used_invoices.add(allocation["invoice_id"])
    truth.append({
        "type": "DUPLICATE_PAYMENT_ALLOCATION",
        "case_id": (
            f"{allocation['payment_id']}|"
            f"{allocation['invoice_id']}|"
            f"{D(allocation['allocated_amount']):.2f}"
        ),
        "injected_record": duplicate_id
    })

    # 3. Close an order that still has an unpaid invoice.
    order = require(
        con.execute("""
            SELECT i.order_id
            FROM InvoiceBalance b
            JOIN Invoice i ON i.invoice_id = b.invoice_id
            WHERE b.outstanding_balance > 0
            GROUP BY i.order_id
            ORDER BY i.order_id
            LIMIT 1
        """).fetchone(),
        "No order with an outstanding invoice"
    )

    order_id = order["order_id"]
    last = require(
        con.execute("""
            SELECT new_status, event_time
            FROM StatusEvent
            WHERE entity_type='SalesOrder'
              AND entity_id=?
            ORDER BY event_time DESC, event_id DESC
            LIMIT 1
        """, (order_id,)).fetchone(),
        "Order has no status history"
    )

    close_time = (
        datetime.fromisoformat(last["event_time"])
        + timedelta(minutes=1)
    ).isoformat(timespec="seconds")

    con.execute("""
        INSERT INTO StatusEvent
        (event_id, entity_type, entity_id,
         old_status, new_status, event_time, issue_type)
        VALUES (?, 'SalesOrder', ?, ?, 'CLOSED', ?, '')
    """, (
        "EVT-STEP14-CLOSED",
        order_id,
        last["new_status"],
        close_time
    ))

    truth.append({
        "type": "CLOSED_ORDER_WITH_UNPAID_INVOICE",
        "case_id": order_id,
        "injected_record": "EVT-STEP14-CLOSED"
    })

    # 4. Delete the DISPATCHED event from one
    # delivered shipment.
    shipment = require(
        con.execute("""
            SELECT s.shipment_id
            FROM Shipment s
            WHERE EXISTS (
                SELECT 1 FROM StatusEvent e
                WHERE e.entity_type='Shipment'
                  AND e.entity_id=s.shipment_id
                  AND e.new_status='DELIVERED'
            )
            AND EXISTS (
                SELECT 1 FROM StatusEvent e
                WHERE e.entity_type='Shipment'
                  AND e.entity_id=s.shipment_id
                  AND e.new_status='DISPATCHED'
            )
            ORDER BY s.shipment_id
            LIMIT 1
        """).fetchone(),
        "No delivered shipment with dispatch history"
    )

    shipment_id = shipment["shipment_id"]

    con.execute("""
        DELETE FROM StatusEvent
        WHERE entity_type='Shipment'
          AND entity_id=?
          AND new_status='DISPATCHED'
    """, (shipment_id,))

    truth.append({
        "type": "SKIPPED_REQUIRED_STATUS",
        "case_id": shipment_id,
        "injected_record": shipment_id
    })

    # 5. Change receivables for an active dispute
    # without adding a payment or credit.
    placeholders = ",".join("?" for _ in used_invoices)

    dispute = require(
        con.execute(f"""
            SELECT d.invoice_id, d.disputed_amount
            FROM Dispute d
            JOIN InvoiceBalance b
              ON b.invoice_id=d.invoice_id
            WHERE d.status IN ('OPEN', 'INVESTIGATING')
              AND d.invoice_id NOT IN ({placeholders})
              AND b.outstanding_balance > 0
            ORDER BY d.invoice_id
            LIMIT 1
        """, tuple(sorted(used_invoices))).fetchone(),
        "No independent active dispute available"
    )

    invoice_id = dispute["invoice_id"]
    current = require(
        con.execute(
            "SELECT outstanding_balance "
            "FROM InvoiceBalance WHERE invoice_id=?",
            (invoice_id,)
        ).fetchone(),
        "Missing invoice balance"
    )

    reduction = min(
        D(dispute["disputed_amount"]),
        D(current["outstanding_balance"])
    )

    require(
        reduction > 0,
        "Dispute reduction must be positive"
    )

    new_balance = (
        D(current["outstanding_balance"]) - reduction
    )

    con.execute("""
        UPDATE InvoiceBalance
        SET outstanding_balance=?
        WHERE invoice_id=?
    """, (f"{new_balance:.2f}", invoice_id))

    truth.append({
        "type": "DISPUTE_RECEIVABLE_MISMATCH",
        "case_id": invoice_id,
        "injected_record": invoice_id
    })

    return truth


def main():
    require(CLEAN.is_file(), f"Missing clean DB: {CLEAN}")

    # Copy through SQLite's backup API, without
    # modifying the source database.
    if ANOMALOUS.exists():
        ANOMALOUS.unlink()

    source = sqlite3.connect(
        f"file:{CLEAN.as_posix()}?mode=ro",
        uri=True
    )

    target = sqlite3.connect(ANOMALOUS)

    try:
        source.backup(target)
    finally:
        source.close()
        target.close()

    con = sqlite3.connect(ANOMALOUS)
    con.row_factory = sqlite3.Row

    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("BEGIN")
        truth = inject(con)

        violations = con.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        require(
            not violations,
            "Injection produced foreign-key violations"
        )

        con.commit()
    except Exception:
        con.rollback()
        con.close()
        ANOMALOUS.unlink(missing_ok=True)
        raise
    else:
        con.close()

    TRUTH.parent.mkdir(parents=True, exist_ok=True)
    TRUTH.write_text(
        json.dumps(
            {
                "dataset": "full_sqlite_anomalous",
                "cases": truth
            },
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    print("\nFULL-SCALE ANOMALY INJECTION PASSED")
    print("Injected cases:", len(truth))

    for case in truth:
        print(
            case["type"],
            "|", case["case_id"]
        )

    print("Anomalous database:", ANOMALOUS)
    print("Separate ground truth:", TRUTH)
    print("Clean database: unchanged")


if __name__ == "__main__":
    main()
