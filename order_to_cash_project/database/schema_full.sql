
PRAGMA foreign_keys = ON;

CREATE TABLE Account (
    account_id TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    industry TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE Quote (
    quote_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES Account(account_id),
    quote_date TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE QuoteLine (
    quote_line_id TEXT PRIMARY KEY,
    quote_id TEXT NOT NULL REFERENCES Quote(quote_id),
    product_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price NUMERIC NOT NULL CHECK(unit_price >= 0)
);

CREATE TABLE SalesOrder (
    order_id TEXT PRIMARY KEY,
    quote_id TEXT NOT NULL UNIQUE REFERENCES Quote(quote_id),
    account_id TEXT NOT NULL REFERENCES Account(account_id),
    order_date TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE OrderLine (
    order_line_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES SalesOrder(order_id),
    quote_line_id TEXT NOT NULL UNIQUE REFERENCES QuoteLine(quote_line_id),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price NUMERIC NOT NULL CHECK(unit_price >= 0)
);

CREATE TABLE Shipment (
    shipment_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES SalesOrder(order_id),
    shipment_date TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE ShipmentLine (
    shipment_line_id TEXT PRIMARY KEY,
    shipment_id TEXT NOT NULL REFERENCES Shipment(shipment_id),
    order_line_id TEXT NOT NULL REFERENCES OrderLine(order_line_id),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    UNIQUE(shipment_id, order_line_id)
);

CREATE TABLE Invoice (
    invoice_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES SalesOrder(order_id),
    invoice_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE InvoiceLine (
    invoice_line_id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL REFERENCES Invoice(invoice_id),
    order_line_id TEXT NOT NULL REFERENCES OrderLine(order_line_id),
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price NUMERIC NOT NULL CHECK(unit_price >= 0)
);

CREATE TABLE Payment (
    payment_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES Account(account_id),
    payment_date TEXT NOT NULL,
    amount NUMERIC NOT NULL CHECK(amount > 0),
    status TEXT NOT NULL
);

CREATE TABLE PaymentAllocation (
    allocation_id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL REFERENCES Payment(payment_id),
    invoice_id TEXT NOT NULL REFERENCES Invoice(invoice_id),
    allocated_amount NUMERIC NOT NULL CHECK(allocated_amount > 0)
);

CREATE TABLE Dispute (
    dispute_id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL REFERENCES Invoice(invoice_id),
    opened_at TEXT NOT NULL,
    disputed_amount NUMERIC NOT NULL CHECK(disputed_amount > 0),
    status TEXT NOT NULL
);

CREATE TABLE DisputeTimeline (
    dispute_id TEXT PRIMARY KEY REFERENCES Dispute(dispute_id),
    opened_at TEXT NOT NULL,
    investigating_at TEXT,
    resolved_at TEXT,
    CHECK (
        investigating_at IS NULL
        OR investigating_at >= opened_at
    ),
    CHECK (
        resolved_at IS NULL
        OR (
            investigating_at IS NOT NULL
            AND resolved_at >= investigating_at
        )
    )
);

CREATE TABLE StatusEvent (
    event_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (
        entity_type IN (
            'Quote',
            'SalesOrder',
            'Shipment',
            'Invoice',
            'Payment',
            'Dispute'
        )
    ),
    entity_id TEXT NOT NULL,
    old_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    event_time TEXT NOT NULL,
    issue_type TEXT NOT NULL DEFAULT ''
);

CREATE TABLE InvoiceBalance (
    invoice_id TEXT PRIMARY KEY REFERENCES Invoice(invoice_id),
    account_id TEXT NOT NULL REFERENCES Account(account_id),
    invoice_total NUMERIC NOT NULL,
    allocated_amount NUMERIC NOT NULL,
    outstanding_balance NUMERIC NOT NULL,
    due_date TEXT NOT NULL,
    days_overdue INTEGER NOT NULL CHECK(days_overdue >= 0),
    aging_bucket TEXT NOT NULL,
    payment_status TEXT NOT NULL
);

CREATE INDEX idx_quote_account
ON Quote(account_id);

CREATE INDEX idx_quoteline_quote
ON QuoteLine(quote_id);

CREATE INDEX idx_order_account
ON SalesOrder(account_id);

CREATE INDEX idx_orderline_order
ON OrderLine(order_id);

CREATE INDEX idx_shipment_order
ON Shipment(order_id);

CREATE INDEX idx_shipmentline_orderline
ON ShipmentLine(order_line_id);

CREATE INDEX idx_invoice_order
ON Invoice(order_id);

CREATE INDEX idx_invoiceline_invoice
ON InvoiceLine(invoice_id);

CREATE INDEX idx_invoiceline_orderline
ON InvoiceLine(order_line_id);

CREATE INDEX idx_payment_account
ON Payment(account_id);

CREATE INDEX idx_allocation_invoice
ON PaymentAllocation(invoice_id);

CREATE INDEX idx_allocation_payment
ON PaymentAllocation(payment_id);

CREATE INDEX idx_dispute_invoice
ON Dispute(invoice_id);

CREATE INDEX idx_event_entity_time
ON StatusEvent(entity_type, entity_id, event_time);

CREATE INDEX idx_event_time
ON StatusEvent(event_time);

CREATE INDEX idx_balance_account
ON InvoiceBalance(account_id);

CREATE INDEX idx_balance_due
ON InvoiceBalance(due_date);

