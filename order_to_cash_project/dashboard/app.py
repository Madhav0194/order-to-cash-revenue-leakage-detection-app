
"""Order-to-Cash Revenue Leakage Analytics Dashboard.

Run from the project root:
    python -m streamlit run dashboard/app.py

The dashboard opens SQLite databases read-only.
"""

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "database"

DATABASES = {
    "Clean Dataset": DB_DIR / "order_to_cash_full.db",
    "Anomalous Dataset": DB_DIR / "order_to_cash_anomalous.db",
}

TRUTH_FILE = (
    ROOT / "data" / "full" / "ground_truth"
    / "sqlite_anomalies.json"
)

CUTOFF = pd.Timestamp("2026-10-31")

st.set_page_config(
    page_title="Order-to-Cash Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.4rem;
        padding-bottom: 2rem;
    }
    div[data-testid="stMetric"] {
        background: rgba(128,128,128,0.06);
        border: 1px solid rgba(128,128,128,0.16);
        border-radius: 12px;
        padding: 15px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def money(value):
    return Decimal(str(value or 0))


def inr(value):
    return f"₹{float(value):,.2f}"


def csv_download(label, frame, filename, key):
    st.download_button(
        label,
        data=frame.to_csv(index=False).encode("utf-8-sig"),
        file_name=filename,
        mime="text/csv",
        key=key,
    )


def read_query(path, sql, params=()):
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as con:
        return pd.read_sql_query(sql, con, params=params)


@st.cache_data(show_spinner=False)
def load_table(path_string, table, version):
    allowed = {
        "Account", "Quote", "QuoteLine", "SalesOrder",
        "OrderLine", "Shipment", "ShipmentLine",
        "Invoice", "InvoiceLine", "Payment",
        "PaymentAllocation", "Dispute",
        "DisputeTimeline", "StatusEvent",
        "InvoiceBalance",
    }

    if table not in allowed:
        raise ValueError("Invalid table")

    return read_query(
        Path(path_string),
        f'SELECT * FROM "{table}"'
    )


def get_table(table):
    return load_table(
        str(db_path),
        table,
        db_path.stat().st_mtime_ns,
    ).copy()


def numeric(frame, columns):
    for column in columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(
                frame[column], errors="coerce"
            ).fillna(0)
    return frame


def filter_accounts(frame):
    if (
        selected_accounts
        and "account_id" in frame.columns
    ):
        return frame[
            frame["account_id"].isin(selected_accounts)
        ].copy()
    return frame.copy()


def filter_dates(frame, column):
    if column not in frame.columns:
        return frame

    dates = pd.to_datetime(
        frame[column], errors="coerce"
    )

    return frame[
        (dates >= pd.Timestamp(start_date))
        & (dates <= pd.Timestamp(end_date))
    ].copy()


def prepare_data():
    accounts = get_table("Account")
    orders = get_table("SalesOrder")
    invoices = get_table("Invoice")
    invoice_lines = get_table("InvoiceLine")
    payments = get_table("Payment")
    allocations = get_table("PaymentAllocation")
    balances = get_table("InvoiceBalance")
    disputes = get_table("Dispute")
    shipments = get_table("Shipment")
    events = get_table("StatusEvent")

    invoice_lines = numeric(
        invoice_lines, ["quantity", "unit_price"]
    )
    payments = numeric(payments, ["amount"])
    allocations = numeric(
        allocations, ["allocated_amount"]
    )
    balances = numeric(
        balances,
        [
            "invoice_total",
            "allocated_amount",
            "outstanding_balance",
            "days_overdue",
        ],
    )
    disputes = numeric(
        disputes, ["disputed_amount"]
    )

    invoice_lines["line_total"] = (
        invoice_lines["quantity"]
        * invoice_lines["unit_price"]
    )

    actual_totals = (
        invoice_lines.groupby(
            "invoice_id", as_index=False
        )["line_total"].sum()
        .rename(
            columns={"line_total": "actual_invoice_total"}
        )
    )

    actual_allocations = (
        allocations.groupby(
            "invoice_id", as_index=False
        )["allocated_amount"].sum()
        .rename(
            columns={
                "allocated_amount": "actual_allocated"
            }
        )
    )

    invoice_view = (
        invoices.merge(
            orders[["order_id", "account_id"]],
            on="order_id",
            how="left",
        )
        .merge(
            accounts[["account_id", "account_name"]],
            on="account_id",
            how="left",
        )
        .merge(
            balances[
                [
                    "invoice_id",
                    "invoice_total",
                    "allocated_amount",
                    "outstanding_balance",
                    "days_overdue",
                    "aging_bucket",
                    "payment_status",
                ]
            ],
            on="invoice_id",
            how="left",
        )
        .merge(
            actual_totals,
            on="invoice_id",
            how="left",
        )
        .merge(
            actual_allocations,
            on="invoice_id",
            how="left",
        )
    )

    invoice_view["actual_invoice_total"] = (
        invoice_view["actual_invoice_total"].fillna(0)
    )
    invoice_view["actual_allocated"] = (
        invoice_view["actual_allocated"].fillna(0)
    )
    invoice_view["recalculated_outstanding"] = (
        invoice_view["actual_invoice_total"]
        - invoice_view["actual_allocated"]
    )

    invoice_view["balance_difference"] = (
        invoice_view["outstanding_balance"]
        - invoice_view["recalculated_outstanding"]
    )

    invoice_view["invoice_date_dt"] = pd.to_datetime(
        invoice_view["invoice_date"], errors="coerce"
    )

    payment_view = (
        payments.merge(
            accounts[["account_id", "account_name"]],
            on="account_id",
            how="left",
        )
    )

    paid_by_payment = (
        allocations.groupby(
            "payment_id", as_index=False
        )["allocated_amount"].sum()
        .rename(
            columns={
                "allocated_amount": "actual_allocated"
            }
        )
    )

    payment_view = payment_view.merge(
        paid_by_payment,
        on="payment_id",
        how="left",
    )

    payment_view["actual_allocated"] = (
        payment_view["actual_allocated"].fillna(0)
    )
    payment_view["allocation_difference"] = (
        payment_view["amount"]
        - payment_view["actual_allocated"]
    )

    dispute_view = disputes.merge(
        invoice_view[
            [
                "invoice_id",
                "account_id",
                "account_name",
                "outstanding_balance",
            ]
        ],
        on="invoice_id",
        how="left",
    )

    return {
        "accounts": accounts,
        "orders": orders,
        "invoices": invoice_view,
        "payments": payment_view,
        "allocations": allocations,
        "disputes": dispute_view,
        "shipments": shipments,
        "events": events,
    }


def detect_anomalies():
    findings = []

    def add(rule, case_id, detail):
        findings.append({
            "anomaly_type": rule,
            "case_id": str(case_id),
            "details": detail,
        })

    # 1. Invoiced quantity exceeds delivered quantity.
    overbilling = read_query(
        db_path,
        """
        WITH delivered AS (
            SELECT order_line_id,
                   SUM(quantity) AS delivered_qty
            FROM ShipmentLine
            GROUP BY order_line_id
        ),
        billed AS (
            SELECT order_line_id,
                   SUM(quantity) AS billed_qty
            FROM InvoiceLine
            GROUP BY order_line_id
        )
        SELECT b.order_line_id,
               b.billed_qty,
               COALESCE(d.delivered_qty, 0)
                   AS delivered_qty
        FROM billed b
        LEFT JOIN delivered d
          ON b.order_line_id=d.order_line_id
        WHERE b.billed_qty >
              COALESCE(d.delivered_qty, 0)
        """,
    )

    for row in overbilling.itertuples(index=False):
        add(
            "INVOICE_EXCEEDS_FULFILLMENT",
            row.order_line_id,
            f"Billed {row.billed_qty}; "
            f"delivered {row.delivered_qty}",
        )

    # 2. Duplicate allocation groups.
    duplicates = read_query(
        db_path,
        """
        SELECT payment_id, invoice_id,
               allocated_amount, COUNT(*) AS copies
        FROM PaymentAllocation
        GROUP BY payment_id, invoice_id,
                 allocated_amount
        HAVING COUNT(*) > 1
        """,
    )

    for row in duplicates.itertuples(index=False):
        case_id = (
            f"{row.payment_id}|{row.invoice_id}|"
            f"{money(row.allocated_amount):.2f}"
        )
        add(
            "DUPLICATE_PAYMENT_ALLOCATION",
            case_id,
            f"{row.copies} matching allocations",
        )

    # 3. Closed order with an unpaid invoice.
    closed = read_query(
        db_path,
        """
        SELECT DISTINCT e.entity_id AS order_id
        FROM StatusEvent e
        JOIN Invoice i
          ON i.order_id=e.entity_id
        JOIN InvoiceBalance b
          ON b.invoice_id=i.invoice_id
        WHERE e.entity_type='SalesOrder'
          AND e.new_status='CLOSED'
          AND b.outstanding_balance > 0
        """,
    )

    for row in closed.itertuples(index=False):
        add(
            "CLOSED_ORDER_WITH_UNPAID_INVOICE",
            row.order_id,
            "Order closed with outstanding receivables",
        )

    # 4. Delivered without dispatch event.
    skipped = read_query(
        db_path,
        """
        SELECT DISTINCT e.entity_id AS shipment_id
        FROM StatusEvent e
        WHERE e.entity_type='Shipment'
          AND e.new_status='DELIVERED'
          AND NOT EXISTS (
              SELECT 1
              FROM StatusEvent d
              WHERE d.entity_type='Shipment'
                AND d.entity_id=e.entity_id
                AND d.new_status='DISPATCHED'
                AND d.event_time<=e.event_time
          )
        """,
    )

    for row in skipped.itertuples(index=False):
        add(
            "SKIPPED_REQUIRED_STATUS",
            row.shipment_id,
            "Delivered without a dispatch transition",
        )

    # 5. Active dispute with mismatched receivables.
    active = read_query(
        db_path,
        """
        SELECT DISTINCT d.invoice_id,
               b.outstanding_balance
        FROM Dispute d
        JOIN InvoiceBalance b
          ON b.invoice_id=d.invoice_id
        WHERE d.status IN ('OPEN','INVESTIGATING')
        """,
    )

    for row in active.itertuples(index=False):
        lines = read_query(
            db_path,
            """
            SELECT quantity, unit_price
            FROM InvoiceLine
            WHERE invoice_id=?
            """,
            (row.invoice_id,),
        )

        allocated = read_query(
            db_path,
            """
            SELECT allocated_amount
            FROM PaymentAllocation
            WHERE invoice_id=?
            """,
            (row.invoice_id,),
        )

        total = sum(
            (
                money(r.unit_price) * int(r.quantity)
                for r in lines.itertuples(index=False)
            ),
            Decimal("0.00"),
        )

        paid = sum(
            (
                money(r.allocated_amount)
                for r in allocated.itertuples(index=False)
            ),
            Decimal("0.00"),
        )

        if money(row.outstanding_balance) != total - paid:
            add(
                "DISPUTE_RECEIVABLE_MISMATCH",
                row.invoice_id,
                f"Recorded {inr(row.outstanding_balance)}; "
                f"expected {inr(total - paid)}",
            )

    return pd.DataFrame(
        findings,
        columns=["anomaly_type", "case_id", "details"],
    )


def evaluation_metrics(findings):
    if not TRUTH_FILE.exists():
        return None

    truth = json.loads(
        TRUTH_FILE.read_text(encoding="utf-8")
    )

    expected = {
        (r["type"], r["case_id"])
        for r in truth["cases"]
    }

    detected = {
        (r.anomaly_type, r.case_id)
        for r in findings.itertuples(index=False)
    }

    tp = len(expected & detected)
    fp = len(detected - expected)
    fn = len(expected - detected)

    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall else 0
    )

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


# ------------------------------
# Sidebar
# ------------------------------

st.sidebar.title("Order-to-Cash")
st.sidebar.caption("Revenue Leakage Analytics")

dataset_name = st.sidebar.selectbox(
    "Dataset",
    list(DATABASES.keys()),
)

db_path = DATABASES[dataset_name]

if not db_path.is_file():
    st.error(
        f"Database not found: {db_path}\n\n"
        "Complete Steps 13 and 14 first."
    )
    st.stop()

accounts_all = get_table("Account")

account_choices = {
    f"{r.account_name} ({r.account_id})": r.account_id
    for r in accounts_all.itertuples(index=False)
}

selected_labels = st.sidebar.multiselect(
    "Filter customers",
    options=list(account_choices),
)

selected_accounts = [
    account_choices[label]
    for label in selected_labels
]

start_date = st.sidebar.date_input(
    "Start date",
    value=pd.Timestamp("2026-01-01").date(),
)

end_date = st.sidebar.date_input(
    "End date",
    value=CUTOFF.date(),
)

if start_date > end_date:
    st.error("Start date must not exceed end date.")
    st.stop()

st.sidebar.caption(
    "Date filters apply to dated transaction views. "
    "Receivables are the stored reporting snapshot "
    "as of 31 October 2026."
)

if st.sidebar.button("Refresh dashboard"):
    st.cache_data.clear()
    st.rerun()

data = prepare_data()

invoices = filter_accounts(data["invoices"])
payments = filter_accounts(data["payments"])
disputes = filter_accounts(data["disputes"])

dated_invoices = filter_dates(
    invoices, "invoice_date"
)
dated_payments = filter_dates(
    payments, "payment_date"
)
dated_disputes = filter_dates(
    disputes, "opened_at"
)

st.title("Order-to-Cash Revenue Leakage")
st.caption(
    f"{dataset_name} | Reporting cutoff: "
    "31 October 2026 | Read-only SQLite analytics"
)

if dataset_name == "Anomalous Dataset":
    st.warning(
        "This dataset contains deliberately injected "
        "synthetic anomalies. Financial totals may "
        "not reconcile."
    )

tabs = st.tabs([
    "Overview",
    "Receivables",
    "Payments",
    "Anomalies",
    "Disputes",
    "Transactions",
])


# ------------------------------
# Tab 1: Overview
# ------------------------------

with tabs[0]:
    st.subheader("Financial overview")

    total_invoiced = dated_invoices[
        "actual_invoice_total"
    ].sum()

    total_payments = dated_payments[
        "amount"
    ].sum()

    total_outstanding = invoices[
        "outstanding_balance"
    ].sum()

    overdue = invoices[
        (pd.to_numeric(
            invoices["outstanding_balance"],
            errors="coerce"
        ) > 0)
        & (
            pd.to_datetime(
                invoices["due_date"],
                errors="coerce"
            ) < CUTOFF
        )
    ]

    a, b, c, d = st.columns(4)

    a.metric("Invoiced in period", inr(total_invoiced))
    b.metric("Payments in period", inr(total_payments))
    c.metric(
        "Outstanding at cutoff",
        inr(total_outstanding)
    )
    d.metric("Overdue invoices", len(overdue))

    st.caption(
        "Invoiced and payments follow the selected "
        "date range. Outstanding and overdue values "
        "are cutoff-date snapshots."
    )

    monthly = dated_invoices.copy()

    if not monthly.empty:
        monthly["month"] = (
            monthly["invoice_date_dt"]
            .dt.to_period("M")
            .astype(str)
        )

        monthly = (
            monthly.groupby(
                "month", as_index=False
            )["actual_invoice_total"].sum()
        )

        fig = px.bar(
            monthly,
            x="month",
            y="actual_invoice_total",
            title="Monthly invoiced revenue",
            labels={
                "month": "Month",
                "actual_invoice_total": "Amount (INR)",
            },
        )
        st.plotly_chart(
            fig, use_container_width=True
        )

    left, right = st.columns(2)

    with left:
        st.markdown("#### Invoice payment status")

        if not invoices.empty:
            summary = (
                invoices.groupby(
                    "payment_status", as_index=False
                ).size()
            )

            fig = px.pie(
                summary,
                names="payment_status",
                values="size",
                hole=0.55,
            )
            st.plotly_chart(
                fig, use_container_width=True
            )

    with right:
        st.markdown("#### Dataset records")

        counts = pd.DataFrame([
            {
                "Entity": "Orders",
                "Records": len(data["orders"]),
            },
            {
                "Entity": "Invoices",
                "Records": len(data["invoices"]),
            },
            {
                "Entity": "Payments",
                "Records": len(data["payments"]),
            },
            {
                "Entity": "Shipments",
                "Records": len(data["shipments"]),
            },
            {
                "Entity": "Disputes",
                "Records": len(data["disputes"]),
            },
            {
                "Entity": "Status events",
                "Records": len(data["events"]),
            },
        ])

        st.dataframe(
            counts,
            hide_index=True,
            use_container_width=True,
        )


# ------------------------------
# Tab 2: Receivables
# ------------------------------

with tabs[1]:
    st.subheader("Accounts receivable analysis")

    aging = (
        invoices.groupby(
            "aging_bucket", as_index=False
        )["outstanding_balance"].sum()
    )

    fig = px.bar(
        aging,
        x="aging_bucket",
        y="outstanding_balance",
        title="Outstanding by aging bucket",
        labels={
            "aging_bucket": "Aging bucket",
            "outstanding_balance": "Amount (INR)",
        },
    )
    st.plotly_chart(
        fig, use_container_width=True
    )

    customer_balances = (
        invoices.groupby(
            ["account_id", "account_name"],
            as_index=False,
            dropna=False,
        )["outstanding_balance"].sum()
        .sort_values(
            "outstanding_balance",
            ascending=False,
        )
    )

    st.markdown("#### Largest customer receivables")

    fig = px.bar(
        customer_balances.head(15),
        x="outstanding_balance",
        y="account_name",
        orientation="h",
        title="Top 15 customer balances",
    )
    fig.update_layout(
        yaxis={"categoryorder": "total ascending"}
    )
    st.plotly_chart(
        fig, use_container_width=True
    )

    st.markdown("#### Invoice-level receivables")

    aging_filter = st.multiselect(
        "Aging bucket",
        sorted(
            invoices["aging_bucket"]
            .dropna()
            .unique()
            .tolist()
        ),
        key="aging_filter",
    )

    receivable_view = invoices.copy()

    if aging_filter:
        receivable_view = receivable_view[
            receivable_view["aging_bucket"].isin(
                aging_filter
            )
        ]

    columns = [
        "invoice_id",
        "account_name",
        "invoice_date",
        "due_date",
        "invoice_total",
        "allocated_amount",
        "outstanding_balance",
        "days_overdue",
        "aging_bucket",
        "payment_status",
    ]

    st.dataframe(
        receivable_view[columns],
        use_container_width=True,
        hide_index=True,
    )

    csv_download(
        "Export receivables CSV",
        receivable_view[columns],
        "receivables.csv",
        "export_receivables",
    )


# ------------------------------
# Tab 3: Payments
# ------------------------------

with tabs[2]:
    st.subheader("Payment reconciliation")

    reconciled = dated_payments.copy()

    st.metric(
        "Total received in period",
        inr(reconciled["amount"].sum())
    )

    st.caption(
        "A difference of zero means payment amount "
        "equals its allocated total. Nonzero values "
        "may indicate unallocated or overallocated "
        "payments and require review."
    )

    mismatches = reconciled[
        reconciled["allocation_difference"].abs()
        > 0.005
    ]

    a, b = st.columns(2)
    a.metric(
        "Payments with allocation differences",
        len(mismatches),
    )
    b.metric(
        "Absolute allocation differences",
        inr(
            mismatches[
                "allocation_difference"
            ].abs().sum()
        ),
    )

    st.markdown("#### Payment allocation details")

    cols = [
        "payment_id",
        "account_name",
        "payment_date",
        "amount",
        "actual_allocated",
        "allocation_difference",
        "status",
    ]

    st.dataframe(
        reconciled[cols],
        hide_index=True,
        use_container_width=True,
    )

    csv_download(
        "Export payment reconciliation CSV",
        reconciled[cols],
        "payment_reconciliation.csv",
        "export_payments",
    )

    st.markdown("#### Invoice reconciliation")

    invoice_mismatches = invoices[
        invoices["balance_difference"].abs()
        > 0.005
    ]

    st.metric(
        "Invoice balance mismatches",
        len(invoice_mismatches),
    )

    st.dataframe(
        invoice_mismatches[
            [
                "invoice_id",
                "account_name",
                "actual_invoice_total",
                "actual_allocated",
                "outstanding_balance",
                "recalculated_outstanding",
                "balance_difference",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )

    csv_download(
        "Export invoice mismatches CSV",
        invoice_mismatches,
        "invoice_reconciliation_issues.csv",
        "export_invoice_mismatches",
    )


# ------------------------------
# Tab 4: Anomalies
# ------------------------------

with tabs[3]:
    st.subheader("Revenue leakage and process anomalies")

    with st.spinner("Running SQL detection rules..."):
        findings = detect_anomalies()

    # Resolve the customer for each anomaly so that
    # the sidebar account filter also works here.
    order_account = dict(
        zip(
            data["orders"]["order_id"],
            data["orders"]["account_id"],
        )
    )

    invoice_order = dict(
        zip(
            get_table("Invoice")["invoice_id"],
            get_table("Invoice")["order_id"],
        )
    )

    shipment_order = dict(
        zip(
            data["shipments"]["shipment_id"],
            data["shipments"]["order_id"],
        )
    )

    line_order = dict(
        zip(
            get_table("OrderLine")["order_line_id"],
            get_table("OrderLine")["order_id"],
        )
    )

    def finding_account(row):
        kind = row["anomaly_type"]
        case = row["case_id"]

        if kind == "INVOICE_EXCEEDS_FULFILLMENT":
            return order_account.get(
                line_order.get(case)
            )

        if kind == "CLOSED_ORDER_WITH_UNPAID_INVOICE":
            return order_account.get(case)

        if kind == "SKIPPED_REQUIRED_STATUS":
            return order_account.get(
                shipment_order.get(case)
            )

        if kind == "DISPUTE_RECEIVABLE_MISMATCH":
            return order_account.get(
                invoice_order.get(case)
            )

        if kind == "DUPLICATE_PAYMENT_ALLOCATION":
            invoice_id = case.split("|")[1]
            return order_account.get(
                invoice_order.get(invoice_id)
            )

        return None

    if not findings.empty:
        findings["account_id"] = findings.apply(
            finding_account, axis=1
        )

    visible_findings = filter_accounts(findings)

    a, b, c = st.columns(3)

    a.metric(
        "Detected anomaly cases",
        len(visible_findings),
    )
    b.metric(
        "Anomaly types",
        visible_findings[
            "anomaly_type"
        ].nunique(),
    )
    c.metric(
        "Clean baseline expected",
        "0",
    )

    if not visible_findings.empty:
        distribution = (
            visible_findings.groupby(
                "anomaly_type", as_index=False
            ).size()
        )

        fig = px.bar(
            distribution,
            x="size",
            y="anomaly_type",
            orientation="h",
            title="Findings by anomaly type",
            labels={
                "size": "Cases",
                "anomaly_type": "Anomaly type",
            },
        )
        st.plotly_chart(
            fig, use_container_width=True
        )

    st.dataframe(
        visible_findings,
        hide_index=True,
        use_container_width=True,
    )

    csv_download(
        "Export anomaly findings CSV",
        visible_findings,
        "anomaly_findings.csv",
        "export_anomalies",
    )

    if dataset_name == "Anomalous Dataset":
        st.markdown("#### Controlled-test evaluation")

        if selected_accounts:
            st.info(
                "Evaluation metrics use the complete "
                "dataset, not the customer-filtered view."
            )

        metrics = evaluation_metrics(findings)

        if metrics:
            x, y, z = st.columns(3)

            x.metric(
                "Precision",
                f"{metrics['precision']:.1%}",
            )
            y.metric(
                "Recall",
                f"{metrics['recall']:.1%}",
            )
            z.metric(
                "F1-score",
                f"{metrics['f1']:.1%}",
            )

            st.caption(
                "These metrics describe five controlled "
                "synthetic anomaly cases, not real-world "
                "production accuracy."
            )


# ------------------------------
# Tab 5: Disputes
# ------------------------------

with tabs[4]:
    st.subheader("Dispute management")

    active_disputes = dated_disputes[
        dated_disputes["status"].isin(
            ["OPEN", "INVESTIGATING"]
        )
    ]

    a, b, c = st.columns(3)

    a.metric(
        "Disputes opened in period",
        len(dated_disputes),
    )
    b.metric(
        "Currently active among selected disputes",
        len(active_disputes),
    )
    c.metric(
        "Disputed value in period",
        inr(
            dated_disputes[
                "disputed_amount"
            ].sum()
        ),
    )

    by_status = (
        dated_disputes.groupby(
            "status", as_index=False
        )["disputed_amount"].sum()
    )

    if not by_status.empty:
        fig = px.bar(
            by_status,
            x="status",
            y="disputed_amount",
            title="Disputed amount by current status",
        )
        st.plotly_chart(
            fig, use_container_width=True
        )

    st.markdown("#### Dispute records")

    st.dataframe(
        dated_disputes,
        hide_index=True,
        use_container_width=True,
    )

    csv_download(
        "Export disputes CSV",
        dated_disputes,
        "disputes.csv",
        "export_disputes",
    )

    st.markdown("#### Dispute lifecycle timeline")

    timeline = get_table("DisputeTimeline")

    if not dated_disputes.empty:
        timeline = timeline[
            timeline["dispute_id"].isin(
                dated_disputes["dispute_id"]
            )
        ]

    timeline_long = timeline.melt(
        id_vars="dispute_id",
        value_vars=[
            "opened_at",
            "investigating_at",
            "resolved_at",
        ],
        var_name="milestone",
        value_name="date",
    ).dropna(subset=["date"])

    timeline_long = timeline_long[
        timeline_long["date"].astype(str) != ""
    ]

    st.dataframe(
        timeline_long,
        hide_index=True,
        use_container_width=True,
    )

    csv_download(
        "Export dispute timeline CSV",
        timeline_long,
        "dispute_timeline.csv",
        "export_dispute_timeline",
    )


# ------------------------------
# Tab 6: Transactions
# ------------------------------

with tabs[5]:
    st.subheader("Transaction explorer")

    table_options = [
        "Account",
        "Quote",
        "QuoteLine",
        "SalesOrder",
        "OrderLine",
        "Shipment",
        "ShipmentLine",
        "Invoice",
        "InvoiceLine",
        "Payment",
        "PaymentAllocation",
        "Dispute",
        "DisputeTimeline",
        "StatusEvent",
        "InvoiceBalance",
    ]

    table_name = st.selectbox(
        "Select transaction table",
        table_options,
    )

    transaction_data = get_table(table_name)

    search = st.text_input(
        "Search across all columns",
        placeholder="Enter an ID, status or keyword",
    )

    if search:
        mask = transaction_data.astype(str).apply(
            lambda col: col.str.contains(
                search,
                case=False,
                regex=False,
                na=False,
            )
        ).any(axis=1)

        transaction_data = transaction_data[mask]

    st.caption(
        f"{len(transaction_data):,} matching records"
    )

    st.dataframe(
        transaction_data.head(5000),
        hide_index=True,
        use_container_width=True,
    )

    if len(transaction_data) > 5000:
        st.info(
            "Showing the first 5,000 records. "
            "CSV export includes all matching records."
        )

    csv_download(
        "Export matching transactions CSV",
        transaction_data,
        f"{table_name.lower()}_export.csv",
        "export_transactions",
    )


st.divider()
st.caption(
    "Order-to-Cash Revenue Leakage Detection System | "
    "Synthetic demonstration dataset | "
    "SQLite read-only analytics"
)
