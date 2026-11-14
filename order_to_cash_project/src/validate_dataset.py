
import csv
import json
import sys
from pathlib import Path
from collections import defaultdict, Counter
from datetime import date, datetime
from decimal import Decimal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DATA_DIR, REPORT_CUTOFF

RAW = DATA_DIR / "raw"
PROCESSED = DATA_DIR / "processed"
ANOMALOUS = DATA_DIR / "anomalous"
TRUTH = DATA_DIR / "ground_truth"
REPORTS = ROOT / "reports"

CUTOFF = date.fromisoformat(REPORT_CUTOFF)
ZERO = Decimal("0.00")

TABLES = {
    "Account": ("accounts.csv", "account_id"),
    "Quote": ("quotes.csv", "quote_id"),
    "QuoteLine": ("quote_lines.csv", "quote_line_id"),
    "SalesOrder": ("sales_orders.csv", "order_id"),
    "OrderLine": ("order_lines.csv", "order_line_id"),
    "Shipment": ("shipments.csv", "shipment_id"),
    "ShipmentLine": ("shipment_lines.csv", "shipment_line_id"),
    "Invoice": ("invoices.csv", "invoice_id"),
    "InvoiceLine": ("invoice_lines.csv", "invoice_line_id"),
    "Payment": ("payments.csv", "payment_id"),
    "PaymentAllocation": (
        "payment_allocations.csv", "allocation_id"
    ),
    "Dispute": ("disputes.csv", "dispute_id"),
    "StatusEvent": ("status_events.csv", "event_id")
}

FOREIGN_KEYS = [
    ("Quote", "account_id", "Account"),
    ("QuoteLine", "quote_id", "Quote"),
    ("SalesOrder", "quote_id", "Quote"),
    ("SalesOrder", "account_id", "Account"),
    ("OrderLine", "order_id", "SalesOrder"),
    ("OrderLine", "quote_line_id", "QuoteLine"),
    ("Shipment", "order_id", "SalesOrder"),
    ("ShipmentLine", "shipment_id", "Shipment"),
    ("ShipmentLine", "order_line_id", "OrderLine"),
    ("Invoice", "order_id", "SalesOrder"),
    ("InvoiceLine", "invoice_id", "Invoice"),
    ("InvoiceLine", "order_line_id", "OrderLine"),
    ("Payment", "account_id", "Account"),
    ("PaymentAllocation", "payment_id", "Payment"),
    ("PaymentAllocation", "invoice_id", "Invoice"),
    ("Dispute", "invoice_id", "Invoice")
]

ALLOWED = {
    "Quote": {
        "": {"DRAFT"},
        "DRAFT": {"SENT"},
        "SENT": {"ACCEPTED", "REJECTED", "EXPIRED"}
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
    "Invoice": {
        "": {"ISSUED"},
        "ISSUED": {
            "PARTIALLY_PAID", "PAID", "OVERDUE"
        },
        "PARTIALLY_PAID": {"PAID", "OVERDUE"},
        "OVERDUE": {"PARTIALLY_PAID", "PAID"}
    },
    "Payment": {
        "": {"RECEIVED"},
        "RECEIVED": {"ALLOCATED"}
    },
    "Dispute": {
        "": {"OPEN"},
        "OPEN": {"INVESTIGATING"},
        "INVESTIGATING": {"RESOLVED"}
    }
}


def money(value):
    return Decimal(str(value)).quantize(
        Decimal("0.01")
    )


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Required file missing: {path}"
        )

    with path.open(
        newline="", encoding="utf-8"
    ) as f:
        return list(csv.DictReader(f))


class Validator:
    def __init__(self, mode):
        self.mode = mode
        self.folder = (
            RAW if mode == "clean" else ANOMALOUS
        )
        self.tables = {}
        self.indexes = {}
        self.issues = []
        self.warnings = []

    def issue(self, rule, entity_id, details):
        self.issues.append({
            "rule": rule,
            "entity_id": str(entity_id),
            "details": str(details)
        })

    def warn(self, rule, entity_id, details):
        self.warnings.append({
            "rule": rule,
            "entity_id": str(entity_id),
            "details": str(details)
        })

    def load(self):
        for table, (filename, pk) in TABLES.items():
            rows = read_csv(self.folder / filename)
            self.tables[table] = rows

            index = {}
            for row in rows:
                key = row.get(pk, "")

                if not key:
                    self.issue(
                        "MISSING_PRIMARY_KEY",
                        table,
                        f"Missing {pk}"
                    )
                elif key in index:
                    self.issue(
                        "DUPLICATE_PRIMARY_KEY",
                        key, table
                    )
                else:
                    index[key] = row

            self.indexes[table] = index

        balance_folder = (
            PROCESSED if self.mode == "clean"
            else ANOMALOUS
        )

        self.tables["InvoiceBalance"] = read_csv(
            balance_folder / "invoice_balances.csv"
        )

    def check_foreign_keys(self):
        for child, field, parent in FOREIGN_KEYS:
            parent_ids = set(
                self.indexes[parent]
            )

            for row in self.tables[child]:
                value = row.get(field, "")

                if value not in parent_ids:
                    self.issue(
                        "FOREIGN_KEY",
                        value,
                        f"{child}.{field} -> {parent}"
                    )

        # Check polymorphic StatusEvent references.
        for event in self.tables["StatusEvent"]:
            entity_type = event["entity_type"]
            entity_id = event["entity_id"]

            if entity_type not in self.indexes:
                self.issue(
                    "UNKNOWN_EVENT_ENTITY",
                    entity_id, entity_type
                )
            elif entity_id not in self.indexes[entity_type]:
                self.issue(
                    "EVENT_FOREIGN_KEY",
                    entity_id, entity_type
                )

    def check_relationships(self):
        quotes = self.indexes["Quote"]
        quote_lines = self.indexes["QuoteLine"]
        orders = self.indexes["SalesOrder"]
        order_lines = self.indexes["OrderLine"]
        shipments = self.indexes["Shipment"]
        invoices = self.indexes["Invoice"]
        payments = self.indexes["Payment"]

        for order in self.tables["SalesOrder"]:
            quote = quotes.get(order["quote_id"])
            if not quote:
                continue

            if quote["status"] != "ACCEPTED":
                self.issue(
                    "ORDER_WITHOUT_ACCEPTED_QUOTE",
                    order["order_id"],
                    order["quote_id"]
                )

            if quote["account_id"] != order["account_id"]:
                self.issue(
                    "ORDER_ACCOUNT_MISMATCH",
                    order["order_id"],
                    order["quote_id"]
                )

        for line in self.tables["OrderLine"]:
            quote_line = quote_lines.get(
                line["quote_line_id"]
            )
            order = orders.get(line["order_id"])

            if not quote_line or not order:
                continue

            if quote_line["quote_id"] != order["quote_id"]:
                self.issue(
                    "ORDER_QUOTE_LINE_MISMATCH",
                    line["order_line_id"],
                    line["quote_line_id"]
                )

        for line in self.tables["ShipmentLine"]:
            shipment = shipments.get(line["shipment_id"])
            order_line = order_lines.get(
                line["order_line_id"]
            )

            if not shipment or not order_line:
                continue

            if shipment["order_id"] != order_line["order_id"]:
                self.issue(
                    "SHIPMENT_ORDER_MISMATCH",
                    line["shipment_line_id"],
                    line["order_line_id"]
                )

        for line in self.tables["InvoiceLine"]:
            invoice = invoices.get(line["invoice_id"])
            order_line = order_lines.get(
                line["order_line_id"]
            )

            if not invoice or not order_line:
                continue

            if invoice["order_id"] != order_line["order_id"]:
                self.issue(
                    "INVOICE_ORDER_MISMATCH",
                    line["invoice_line_id"],
                    line["order_line_id"]
                )

        for allocation in self.tables["PaymentAllocation"]:
            payment = payments.get(
                allocation["payment_id"]
            )
            invoice = invoices.get(
                allocation["invoice_id"]
            )

            if not payment or not invoice:
                continue

            order = orders.get(invoice["order_id"])

            if order and payment["account_id"] != order["account_id"]:
                self.issue(
                    "PAYMENT_ACCOUNT_MISMATCH",
                    allocation["allocation_id"],
                    invoice["invoice_id"]
                )

    def check_quantities(self):
        ordered = {}
        delivered = defaultdict(int)
        billed = defaultdict(int)

        for line in self.tables["OrderLine"]:
            line_id = line["order_line_id"]
            quantity = int(line["quantity"])
            ordered[line_id] = quantity

            if quantity <= 0:
                self.issue(
                    "INVALID_ORDER_QUANTITY",
                    line_id, quantity
                )

        for line in self.tables["ShipmentLine"]:
            line_id = line["order_line_id"]
            quantity = int(line["quantity"])

            if quantity <= 0:
                self.issue(
                    "INVALID_SHIPMENT_QUANTITY",
                    line["shipment_line_id"], quantity
                )

            delivered[line_id] += quantity

        for line_id, quantity in delivered.items():
            if line_id in ordered and quantity > ordered[line_id]:
                self.issue(
                    "OVER_SHIPMENT",
                    line_id,
                    f"{quantity} > {ordered[line_id]}"
                )

        for line in self.tables["InvoiceLine"]:
            line_id = line["order_line_id"]
            quantity = int(line["quantity"])

            if quantity <= 0:
                self.issue(
                    "INVALID_INVOICE_QUANTITY",
                    line["invoice_line_id"], quantity
                )

            billed[line_id] += quantity

        for line_id, quantity in billed.items():
            if quantity > delivered[line_id]:
                self.issue(
                    "INVOICE_EXCEEDS_FULFILLMENT",
                    line_id,
                    f"Billed {quantity}, delivered {delivered[line_id]}"
                )

        return delivered, billed

    def check_payments(self):
        invoice_totals = defaultdict(
            lambda: ZERO
        )
        allocated_by_invoice = defaultdict(
            lambda: ZERO
        )
        allocated_by_payment = defaultdict(
            lambda: ZERO
        )

        for line in self.tables["InvoiceLine"]:
            invoice_totals[
                line["invoice_id"]
            ] += (
                money(line["unit_price"])
                * int(line["quantity"])
            )

        allocation_groups = defaultdict(list)

        for allocation in self.tables["PaymentAllocation"]:
            amount = money(
                allocation["allocated_amount"]
            )

            if amount <= 0:
                self.issue(
                    "INVALID_ALLOCATION_AMOUNT",
                    allocation["allocation_id"], amount
                )

            allocated_by_invoice[
                allocation["invoice_id"]
            ] += amount

            allocated_by_payment[
                allocation["payment_id"]
            ] += amount

            key = (
                allocation["payment_id"],
                allocation["invoice_id"],
                str(amount)
            )

            allocation_groups[key].append(
                allocation["allocation_id"]
            )

        for key, ids in allocation_groups.items():
            if len(ids) > 1:
                self.issue(
                    "DUPLICATE_PAYMENT_ALLOCATION",
                    "|".join(sorted(ids)),
                    f"Same payment, invoice, amount: {key}"
                )

        for payment in self.tables["Payment"]:
            pid = payment["payment_id"]
            amount = money(payment["amount"])
            allocated = allocated_by_payment[pid]

            if amount <= 0:
                self.issue(
                    "INVALID_PAYMENT_AMOUNT",
                    pid, amount
                )

            if allocated > amount:
                self.issue(
                    "PAYMENT_OVERALLOCATED",
                    pid,
                    f"Allocated {allocated}, received {amount}"
                )

            if (
                payment["status"] == "ALLOCATED"
                and allocated != amount
            ):
                self.issue(
                    "PAYMENT_STATUS_RECONCILIATION",
                    pid,
                    f"Allocated {allocated}, payment {amount}"
                )

        for invoice in self.tables["Invoice"]:
            iid = invoice["invoice_id"]
            total = invoice_totals[iid]
            allocated = allocated_by_invoice[iid]

            if allocated > total:
                self.issue(
                    "INVOICE_OVERALLOCATED",
                    iid,
                    f"Allocated {allocated}, total {total}"
                )

        balances = self.tables["InvoiceBalance"]
        balance_ids = [
            row["invoice_id"] for row in balances
        ]

        for iid, count in Counter(balance_ids).items():
            if count > 1:
                self.issue(
                    "DUPLICATE_BALANCE",
                    iid, count
                )

        invoice_ids = set(self.indexes["Invoice"])

        if set(balance_ids) != invoice_ids:
            self.issue(
                "BALANCE_COVERAGE",
                "InvoiceBalance",
                "Balance invoice IDs differ from invoice IDs"
            )

        for balance in balances:
            iid = balance["invoice_id"]

            if iid not in invoice_ids:
                continue

            total = invoice_totals[iid]
            allocated = allocated_by_invoice[iid]
            expected = total - allocated

            recorded_total = money(
                balance["invoice_total"]
            )
            recorded_allocated = money(
                balance["allocated_amount"]
            )
            recorded_outstanding = money(
                balance["outstanding_balance"]
            )

            if recorded_total != total:
                self.issue(
                    "INVOICE_TOTAL_MISMATCH",
                    iid,
                    f"Recorded {recorded_total}, actual {total}"
                )

            if recorded_allocated != allocated:
                self.issue(
                    "ALLOCATION_TOTAL_MISMATCH",
                    iid,
                    f"Recorded {recorded_allocated}, actual {allocated}"
                )

            if recorded_outstanding != expected:
                self.issue(
                    "RECEIVABLE_RECONCILIATION",
                    iid,
                    f"Recorded {recorded_outstanding}, expected {expected}"
                )

            if recorded_outstanding < ZERO:
                self.issue(
                    "NEGATIVE_RECEIVABLE",
                    iid, recorded_outstanding
                )

        return invoice_totals, allocated_by_invoice

    def check_dates(self):
        for quote in self.tables["Quote"]:
            start = date.fromisoformat(
                quote["quote_date"]
            )
            end = date.fromisoformat(
                quote["valid_until"]
            )

            if end < start:
                self.issue(
                    "QUOTE_DATE_ORDER",
                    quote["quote_id"],
                    "valid_until before quote_date"
                )

        for invoice in self.tables["Invoice"]:
            issued = date.fromisoformat(
                invoice["invoice_date"]
            )
            due = date.fromisoformat(
                invoice["due_date"]
            )

            if due < issued:
                self.issue(
                    "INVOICE_DATE_ORDER",
                    invoice["invoice_id"],
                    "due_date before invoice_date"
                )

            if issued > CUTOFF:
                self.warn(
                    "INVOICE_AFTER_CUTOFF",
                    invoice["invoice_id"], issued
                )

        for payment in self.tables["Payment"]:
            paid = date.fromisoformat(
                payment["payment_date"]
            )

            if paid > CUTOFF:
                self.issue(
                    "PAYMENT_AFTER_CUTOFF",
                    payment["payment_id"], paid
                )

        for dispute in self.tables["Dispute"]:
            opened = date.fromisoformat(
                dispute["opened_at"]
            )

            invoice = self.indexes["Invoice"].get(
                dispute["invoice_id"]
            )

            if invoice:
                issued = date.fromisoformat(
                    invoice["invoice_date"]
                )

                if opened < issued:
                    self.issue(
                        "DISPUTE_BEFORE_INVOICE",
                        dispute["dispute_id"], opened
                    )

            if opened > CUTOFF:
                self.issue(
                    "DISPUTE_AFTER_CUTOFF",
                    dispute["dispute_id"], opened
                )

        for allocation in self.tables["PaymentAllocation"]:
            payment = self.indexes["Payment"].get(
                allocation["payment_id"]
            )
            invoice = self.indexes["Invoice"].get(
                allocation["invoice_id"]
            )

            if payment and invoice:
                paid = date.fromisoformat(
                    payment["payment_date"]
                )
                issued = date.fromisoformat(
                    invoice["invoice_date"]
                )

                if paid < issued:
                    self.issue(
                        "PAYMENT_BEFORE_INVOICE",
                        allocation["allocation_id"],
                        f"{paid} < {issued}"
                    )

        # Shipment date is the delivered date in
        # the current synthetic generator.
        for shipment in self.tables["Shipment"]:
            order = self.indexes["SalesOrder"].get(
                shipment["order_id"]
            )

            if not order:
                continue

            delivered = date.fromisoformat(
                shipment["shipment_date"]
            )
            ordered = date.fromisoformat(
                order["order_date"]
            )

            if delivered < ordered:
                self.issue(
                    "SHIPMENT_BEFORE_ORDER",
                    shipment["shipment_id"],
                    f"{delivered} < {ordered}"
                )

    def check_events(self):
        histories = defaultdict(list)

        for event in self.tables["StatusEvent"]:
            key = (
                event["entity_type"],
                event["entity_id"]
            )
            histories[key].append(event)

            when = datetime.fromisoformat(
                event["event_time"]
            )

            if when.date() > CUTOFF:
                self.issue(
                    "EVENT_AFTER_CUTOFF",
                    event["event_id"], when
                )

        for (entity_type, entity_id), history in histories.items():
            history.sort(
                key=lambda x: (
                    x["event_time"], x["event_id"]
                )
            )

            previous = ""

            for event in history:
                old = event["old_status"]
                new = event["new_status"]

                if old != previous:
                    self.issue(
                        "BROKEN_STATUS_CHAIN",
                        entity_id,
                        f"Expected old={previous}, got {old}"
                    )

                if new not in ALLOWED.get(
                    entity_type, {}
                ).get(previous, set()):
                    self.issue(
                        "INVALID_STATUS_TRANSITION",
                        entity_id,
                        f"{previous} -> {new}"
                    )

                previous = new

            if entity_type == "Shipment":
                states = [
                    e["new_status"] for e in history
                ]

                if (
                    "DELIVERED" in states
                    and "DISPATCHED" not in states
                ):
                    self.issue(
                        "SKIPPED_REQUIRED_STATUS",
                        entity_id,
                        "DELIVERED without DISPATCHED"
                    )

        for entity_type in ALLOWED:
            for entity_id in self.indexes[entity_type]:
                if (entity_type, entity_id) not in histories:
                    self.issue(
                        "MISSING_EVENT_HISTORY",
                        entity_id, entity_type
                    )

        # Existing dispute CSV has current statuses,
        # but no actual dated investigation or
        # resolution fields. Report discrepancies
        # as data-quality warnings.
        for dispute in self.tables["Dispute"]:
            key = ("Dispute", dispute["dispute_id"])
            history = histories.get(key, [])

            if history:
                last_status = sorted(
                    history,
                    key=lambda e: e["event_time"]
                )[-1]["new_status"]

                if last_status != dispute["status"]:
                    self.warn(
                        "DISPUTE_HISTORY_INCOMPLETE",
                        dispute["dispute_id"],
                        f"Source={dispute['status']}, "
                        f"history={last_status}"
                    )

    def check_business_rules(self, invoice_totals,
                             allocated_by_invoice):
        orders = self.indexes["SalesOrder"]
        invoices = self.tables["Invoice"]
        balances = {
            b["invoice_id"]: b
            for b in self.tables["InvoiceBalance"]
        }

        invoice_by_order = defaultdict(list)

        for invoice in invoices:
            invoice_by_order[
                invoice["order_id"]
            ].append(invoice)

        closed_orders = {
            e["entity_id"]
            for e in self.tables["StatusEvent"]
            if (
                e["entity_type"] == "SalesOrder"
                and e["new_status"] == "CLOSED"
            )
        }

        for oid in closed_orders:
            if oid not in orders:
                continue

            for invoice in invoice_by_order[oid]:
                iid = invoice["invoice_id"]
                outstanding = (
                    invoice_totals[iid]
                    - allocated_by_invoice[iid]
                )

                if outstanding > ZERO:
                    self.issue(
                        "CLOSED_ORDER_WITH_UNPAID_INVOICE",
                        oid,
                        f"Invoice {iid} outstanding {outstanding}"
                    )

        active_disputes = {
            d["invoice_id"]
            for d in self.tables["Dispute"]
            if d["status"] in (
                "OPEN", "INVESTIGATING"
            )
        }

        for iid in active_disputes:
            if iid not in balances:
                continue

            expected = (
                invoice_totals[iid]
                - allocated_by_invoice[iid]
            )

            actual = money(
                balances[iid]["outstanding_balance"]
            )

            if actual != expected:
                self.issue(
                    "DISPUTE_RECEIVABLE_MISMATCH",
                    iid,
                    f"Actual {actual}, expected {expected}"
                )

    def run(self):
        self.load()
        self.check_foreign_keys()
        self.check_relationships()
        self.check_quantities()

        invoice_totals, allocations = (
            self.check_payments()
        )

        self.check_dates()
        self.check_events()
        self.check_business_rules(
            invoice_totals, allocations
        )

        return {
            "mode": self.mode,
            "table_counts": {
                table: len(rows)
                for table, rows in self.tables.items()
            },
            "issues": self.issues,
            "warnings": self.warnings
        }


def check_expected_anomalies(report):
    truth = read_csv(
        TRUTH / "ground_truth.csv"
    )

    expected_types = {
        row["issue_type"] for row in truth
    }

    detected_types = {
        issue["rule"] for issue in report["issues"]
    }

    missing = sorted(
        expected_types - detected_types
    )

    return {
        "expected_types": sorted(expected_types),
        "detected_types": sorted(detected_types),
        "missing_types": missing,
        "all_five_detected": (
            len(expected_types) == 5
            and len(missing) == 0
        )
    }


def print_report(report):
    print(
        "\nDATASET VALIDATION:",
        report["mode"].upper()
    )
    print("--------------------------------")

    for table, count in report["table_counts"].items():
        print(f"{table:20s}: {count}")

    print("\nIntegrity issues:", len(report["issues"]))
    print("Data-quality warnings:", len(report["warnings"]))

    issue_counts = Counter(
        x["rule"] for x in report["issues"]
    )

    if issue_counts:
        print("\nISSUES BY RULE")
        for rule, count in sorted(issue_counts.items()):
            print(f"{rule}: {count}")
    else:
        print("\nNo integrity issues detected.")

    if report["warnings"]:
        print("\nWARNING SUMMARY")
        warning_counts = Counter(
            x["rule"] for x in report["warnings"]
        )

        for rule, count in sorted(warning_counts.items()):
            print(f"{rule}: {count}")

    if report["mode"] == "anomalous":
        comparison = report["ground_truth_check"]

        print("\nGROUND TRUTH TYPE COVERAGE")
        print("--------------------------------")

        for rule in comparison["expected_types"]:
            status = (
                "DETECTED"
                if rule in comparison["detected_types"]
                else "MISSED"
            )
            print(status, rule)

        print(
            "All five types detected:",
            comparison["all_five_detected"]
        )


def main():
    REPORTS.mkdir(
        parents=True, exist_ok=True
    )

    results = {}

    for mode in ("clean", "anomalous"):
        validator = Validator(mode)
        report = validator.run()

        if mode == "anomalous":
            report["ground_truth_check"] = (
                check_expected_anomalies(report)
            )

        results[mode] = report

        print_report(report)

        output_path = (
            REPORTS / f"validation_{mode}.json"
        )

        with output_path.open(
            "w", encoding="utf-8"
        ) as f:
            json.dump(
                report, f, indent=2
            )

        print("\nSaved:", output_path)

    clean_ok = (
        len(results["clean"]["issues"]) == 0
    )

    anomalous_ok = results[
        "anomalous"
    ]["ground_truth_check"]["all_five_detected"]

    print("\nFINAL VALIDATION RESULT")
    print("--------------------------------")
    print("Clean baseline:", (
        "PASS" if clean_ok else "FAIL"
    ))
    print("Five anomaly types:", (
        "PASS" if anomalous_ok else "FAIL"
    ))

    if clean_ok and anomalous_ok:
        print("\nFULL VALIDATION PASSED")
    else:
        print("\nVALIDATION REQUIRES REVIEW")
        sys.exit(1)


if __name__ == "__main__":
    main()
