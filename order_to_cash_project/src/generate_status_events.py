
import csv
import sys
from pathlib import Path
from datetime import date, datetime, time, timedelta
from collections import defaultdict
from decimal import Decimal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DATA_DIR, REPORT_CUTOFF

RAW = DATA_DIR / "raw"
PROCESSED = DATA_DIR / "processed"
CUTOFF = date.fromisoformat(REPORT_CUTOFF)

FIELDS = [
    "event_id", "entity_type", "entity_id",
    "old_status", "new_status", "event_time",
    "issue_type", "ground_truth"
]

events = []


def read_csv(folder, filename):
    with (folder / filename).open(
        newline="", encoding="utf-8"
    ) as f:
        return list(csv.DictReader(f))


def timestamp(day, hour=12):
    return datetime.combine(day, time(hour=hour))


def add_event(entity_type, entity_id, old, new, when):
    if when.date() > CUTOFF:
        raise ValueError(
            f"Event after cutoff: {entity_id}"
        )

    events.append({
        "event_id": "",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "old_status": old or "",
        "new_status": new,
        "event_time": when.isoformat(
            timespec="seconds"
        ),
        "issue_type": "",
        "ground_truth": 0
    })


def quote_events(quotes):
    for q in quotes:
        day = date.fromisoformat(q["quote_date"])
        qid = q["quote_id"]

        add_event(
            "Quote", qid, "", "DRAFT",
            timestamp(day, 9)
        )
        add_event(
            "Quote", qid, "DRAFT", "SENT",
            timestamp(day, 11)
        )

        if q["status"] != "SENT":
            final_day = day + timedelta(days=2)

            if q["status"] == "EXPIRED":
                final_day = date.fromisoformat(
                    q["valid_until"]
                ) + timedelta(days=1)

            if final_day <= CUTOFF:
                add_event(
                    "Quote", qid, "SENT",
                    q["status"], timestamp(final_day)
                )


def order_events(orders, order_lines, shipments, shipment_lines):
    lines = defaultdict(dict)
    shipment_map = {
        s["shipment_id"]: s for s in shipments
    }

    for line in order_lines:
        lines[line["order_id"]][
            line["order_line_id"]
        ] = int(line["quantity"])

    delivery_events = defaultdict(
        lambda: defaultdict(list)
    )

    for sl in shipment_lines:
        shipment = shipment_map[sl["shipment_id"]]

        if shipment["status"] != "DELIVERED":
            continue

        day = date.fromisoformat(
            shipment["shipment_date"]
        )

        delivery_events[
            shipment["order_id"]
        ][day].append(sl)

    for order in orders:
        oid = order["order_id"]
        day = date.fromisoformat(
            order["order_date"]
        )

        add_event(
            "SalesOrder", oid, "", "CREATED",
            timestamp(day, 9)
        )
        add_event(
            "SalesOrder", oid, "CREATED",
            "CONFIRMED", timestamp(day, 11)
        )

        delivered = defaultdict(int)
        current = "CONFIRMED"

        for delivery_day, records in sorted(
            delivery_events[oid].items()
        ):
            for sl in records:
                line_id = sl["order_line_id"]

                if line_id not in lines[oid]:
                    raise ValueError(
                        f"Invalid order line: {line_id}"
                    )

                delivered[line_id] += int(
                    sl["quantity"]
                )

                if delivered[line_id] > lines[oid][line_id]:
                    raise ValueError(
                        f"Over-shipment: {line_id}"
                    )

            total_ordered = sum(lines[oid].values())
            total_delivered = sum(delivered.values())

            if total_delivered == total_ordered:
                next_status = "FULFILLED"
            else:
                next_status = "PARTIALLY_FULFILLED"

            if next_status != current:
                add_event(
                    "SalesOrder", oid, current,
                    next_status,
                    timestamp(delivery_day, 18)
                )
                current = next_status


def shipment_events(shipments):
    for s in shipments:
        sid = s["shipment_id"]
        delivered = date.fromisoformat(
            s["shipment_date"]
        )

        add_event(
            "Shipment", sid, "", "CREATED",
            timestamp(
                delivered - timedelta(days=2), 9
            )
        )
        add_event(
            "Shipment", sid, "CREATED",
            "DISPATCHED",
            timestamp(
                delivered - timedelta(days=1), 10
            )
        )
        add_event(
            "Shipment", sid, "DISPATCHED",
            "DELIVERED",
            timestamp(delivered, 16)
        )


def payment_events(payments):
    for p in payments:
        pid = p["payment_id"]
        day = date.fromisoformat(
            p["payment_date"]
        )

        add_event(
            "Payment", pid, "", "RECEIVED",
            timestamp(day, 9)
        )

        if p["status"] == "ALLOCATED":
            add_event(
                "Payment", pid,
                "RECEIVED", "ALLOCATED",
                timestamp(day, 11)
            )


def invoice_events(invoices, invoice_lines, payments, allocations):
    payments_by_id = {
        p["payment_id"]: p for p in payments
    }

    totals = defaultdict(
        lambda: Decimal("0.00")
    )

    for line in invoice_lines:
        totals[line["invoice_id"]] += (
            Decimal(line["unit_price"])
            * int(line["quantity"])
        )

    allocations_by_invoice = defaultdict(list)

    for allocation in allocations:
        payment = payments_by_id[
            allocation["payment_id"]
        ]

        allocations_by_invoice[
            allocation["invoice_id"]
        ].append({
            "date": date.fromisoformat(
                payment["payment_date"]
            ),
            "amount": Decimal(
                allocation["allocated_amount"]
            )
        })

    for inv in invoices:
        iid = inv["invoice_id"]
        issued = date.fromisoformat(
            inv["invoice_date"]
        )
        due = date.fromisoformat(
            inv["due_date"]
        )
        total = totals[iid]

        add_event(
            "Invoice", iid, "", "ISSUED",
            timestamp(issued, 9)
        )

        current = "ISSUED"
        allocated = Decimal("0.00")

        by_date = defaultdict(
            lambda: Decimal("0.00")
        )

        for allocation in allocations_by_invoice[iid]:
            by_date[allocation["date"]] += (
                allocation["amount"]
            )

        # Due-date event is processed before
        # payments on the same later date.
        timeline = []

        if due < CUTOFF:
            timeline.append((
                due + timedelta(days=1),
                8, "DUE", Decimal("0")
            ))

        for day, amount in by_date.items():
            if day < issued:
                raise ValueError(
                    f"Payment before invoice: {iid}"
                )

            if day <= CUTOFF:
                timeline.append((
                    day, 12, "PAYMENT", amount
                ))

        timeline.sort(key=lambda x: (x[0], x[1]))

        for day, hour, kind, amount in timeline:
            if kind == "DUE":
                if allocated < total and current != "OVERDUE":
                    add_event(
                        "Invoice", iid, current,
                        "OVERDUE", timestamp(day, hour)
                    )
                    current = "OVERDUE"
                continue

            allocated += amount

            if allocated > total:
                raise ValueError(
                    f"Overallocated invoice: {iid}"
                )

            next_status = (
                "PAID" if allocated == total
                else "PARTIALLY_PAID"
            )

            if next_status != current:
                add_event(
                    "Invoice", iid, current,
                    next_status, timestamp(day, hour)
                )
                current = next_status

        # If partially paid but still overdue,
        # the final state must reflect overdue.
        if (
            due < CUTOFF
            and allocated < total
            and current != "OVERDUE"
        ):
            add_event(
                "Invoice", iid, current,
                "OVERDUE",
                timestamp(CUTOFF, 18)
            )


def dispute_events(disputes):
    for d in disputes:
        did = d["dispute_id"]
        opened = date.fromisoformat(
            d["opened_at"]
        )

        add_event(
            "Dispute", did, "", "OPEN",
            timestamp(opened, 9)
        )

        # Existing source data has no investigation
        # or resolution timestamps.
        # Do not fabricate those transitions.
        # Missing evidence will be reported.
        if d["status"] != "OPEN":
            print(
                "WARNING: No dated transition for",
                did, d["status"]
            )


def validate():
    grouped = defaultdict(list)

    allowed = {
        "Quote": {
            "": {"DRAFT"},
            "DRAFT": {"SENT"},
            "SENT": {
                "ACCEPTED", "REJECTED", "EXPIRED"
            }
        },
        "SalesOrder": {
            "": {"CREATED"},
            "CREATED": {"CONFIRMED"},
            "CONFIRMED": {
                "PARTIALLY_FULFILLED", "FULFILLED"
            },
            "PARTIALLY_FULFILLED": {"FULFILLED"}
        },
        "Shipment": {
            "": {"CREATED"},
            "CREATED": {"DISPATCHED"},
            "DISPATCHED": {"DELIVERED"}
        },
        "Payment": {
            "": {"RECEIVED"},
            "RECEIVED": {"ALLOCATED"}
        },
        "Dispute": {
            "": {"OPEN"},
            "OPEN": {"INVESTIGATING"},
            "INVESTIGATING": {"RESOLVED"}
        },
        "Invoice": {
            "": {"ISSUED"},
            "ISSUED": {
                "PARTIALLY_PAID", "PAID", "OVERDUE"
            },
            "PARTIALLY_PAID": {"PAID", "OVERDUE"},
            "OVERDUE": {"PARTIALLY_PAID", "PAID"}
        }
    }

    for event in events:
        grouped[
            (event["entity_type"], event["entity_id"])
        ].append(event)

    for (entity_type, entity_id), history in grouped.items():
        history.sort(
            key=lambda e: e["event_time"]
        )

        previous = ""
        previous_time = None

        for event in history:
            when = datetime.fromisoformat(
                event["event_time"]
            )

            if event["old_status"] != previous:
                raise ValueError(
                    f"Broken chain: {entity_id}"
                )

            if event["new_status"] not in allowed[
                entity_type
            ].get(previous, set()):
                raise ValueError(
                    f"Invalid transition: {entity_id}"
                )

            if previous_time and when < previous_time:
                raise ValueError(
                    f"Date error: {entity_id}"
                )

            previous = event["new_status"]
            previous_time = when


def main():
    events.clear()

    quotes = read_csv(RAW, "quotes.csv")
    orders = read_csv(RAW, "sales_orders.csv")
    order_lines = read_csv(RAW, "order_lines.csv")
    shipments = read_csv(RAW, "shipments.csv")
    shipment_lines = read_csv(
        RAW, "shipment_lines.csv"
    )
    invoices = read_csv(RAW, "invoices.csv")
    invoice_lines = read_csv(
        RAW, "invoice_lines.csv"
    )
    payments = read_csv(RAW, "payments.csv")
    allocations = read_csv(
        RAW, "payment_allocations.csv"
    )
    disputes = read_csv(RAW, "disputes.csv")

    quote_events(quotes)
    order_events(
        orders, order_lines,
        shipments, shipment_lines
    )
    shipment_events(shipments)
    payment_events(payments)
    invoice_events(
        invoices, invoice_lines,
        payments, allocations
    )
    dispute_events(disputes)

    events.sort(
        key=lambda e: (
            e["event_time"],
            e["entity_type"],
            e["entity_id"]
        )
    )

    validate()

    for index, event in enumerate(events, 1):
        event["event_id"] = (
            f"EVT-2026-{index:06d}"
        )

    with (RAW / "status_events.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=FIELDS
        )
        writer.writeheader()
        writer.writerows(events)

    counts = defaultdict(int)

    for event in events:
        counts[event["entity_type"]] += 1

    print("\nCORRECTED STATUS EVENT SUMMARY")
    print("------------------------------")
    print("Total events:", len(events))

    for entity_type in sorted(counts):
        print(entity_type, ":", counts[entity_type])

    print("Reporting cutoff:", REPORT_CUTOFF)
    print("Lifecycle validation PASSED")
    print("Saved: data/raw/status_events.csv")


if __name__ == "__main__":
    main()
