
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS Account (
    account_id TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    industry TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK(status IN ('ACTIVE', 'INACTIVE'))
);

CREATE TABLE IF NOT EXISTS Quote (
    quote_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    quote_date TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK(status IN (
            'DRAFT', 'SENT', 'ACCEPTED',
            'REJECTED', 'EXPIRED'
        )),
    FOREIGN KEY(account_id) REFERENCES Account(account_id),
    CHECK(valid_until >= quote_date)
);

CREATE TABLE IF NOT EXISTS QuoteLine (
    quote_line_id TEXT PRIMARY KEY,
    quote_id TEXT NOT NULL,
    product_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price NUMERIC NOT NULL CHECK(unit_price >= 0),
    FOREIGN KEY(quote_id) REFERENCES Quote(quote_id)
);

CREATE TABLE IF NOT EXISTS SalesOrder (
    order_id TEXT PRIMARY KEY,
    quote_id TEXT NOT NULL UNIQUE,
    account_id TEXT NOT NULL,
    order_date TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK(status IN (
            'CREATED', 'CONFIRMED',
            'PARTIALLY_FULFILLED',
            'FULFILLED', 'CLOSED', 'CANCELLED'
        )),
    FOREIGN KEY(quote_id) REFERENCES Quote(quote_id),
    FOREIGN KEY(account_id) REFERENCES Account(account_id)
);

CREATE TABLE IF NOT EXISTS OrderLine (
    order_line_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    quote_line_id TEXT NOT NULL UNIQUE,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price NUMERIC NOT NULL CHECK(unit_price >= 0),
    FOREIGN KEY(order_id) REFERENCES SalesOrder(order_id),
    FOREIGN KEY(quote_line_id) REFERENCES QuoteLine(quote_line_id)
);

CREATE TABLE IF NOT EXISTS Shipment (
    shipment_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    shipment_date TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK(status IN (
            'CREATED', 'DISPATCHED', 'DELIVERED'
        )),
    FOREIGN KEY(order_id) REFERENCES SalesOrder(order_id)
);

CREATE TABLE IF NOT EXISTS ShipmentLine (
    shipment_line_id TEXT PRIMARY KEY,
    shipment_id TEXT NOT NULL,
    order_line_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    FOREIGN KEY(shipment_id) REFERENCES Shipment(shipment_id),
    FOREIGN KEY(order_line_id) REFERENCES OrderLine(order_line_id),
    UNIQUE(shipment_id, order_line_id)
);

CREATE TABLE IF NOT EXISTS Invoice (
    invoice_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    invoice_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK(status IN (
            'ISSUED', 'PARTIALLY_PAID',
            'PAID', 'OVERDUE', 'VOID'
        )),
    FOREIGN KEY(order_id) REFERENCES SalesOrder(order_id),
    CHECK(due_date >= invoice_date)
);

CREATE TABLE IF NOT EXISTS InvoiceLine (
    invoice_line_id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL,
    order_line_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price NUMERIC NOT NULL CHECK(unit_price >= 0),
    FOREIGN KEY(invoice_id) REFERENCES Invoice(invoice_id),
    FOREIGN KEY(order_line_id) REFERENCES OrderLine(order_line_id)
);

CREATE TABLE IF NOT EXISTS Payment (
    payment_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    payment_date TEXT NOT NULL,
    amount NUMERIC NOT NULL CHECK(amount > 0),
    status TEXT NOT NULL
        CHECK(status IN ('RECEIVED', 'ALLOCATED', 'REFUNDED')),
    FOREIGN KEY(account_id) REFERENCES Account(account_id)
);

CREATE TABLE IF NOT EXISTS PaymentAllocation (
    allocation_id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL,
    allocated_amount NUMERIC NOT NULL
        CHECK(allocated_amount > 0),
    FOREIGN KEY(payment_id) REFERENCES Payment(payment_id),
    FOREIGN KEY(invoice_id) REFERENCES Invoice(invoice_id)
);

CREATE TABLE IF NOT EXISTS Dispute (
    dispute_id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    disputed_amount NUMERIC NOT NULL
        CHECK(disputed_amount > 0),
    status TEXT NOT NULL
        CHECK(status IN ('OPEN', 'INVESTIGATING', 'RESOLVED')),
    FOREIGN KEY(invoice_id) REFERENCES Invoice(invoice_id)
);

CREATE TABLE IF NOT EXISTS StatusEvent (
    event_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    event_time TEXT NOT NULL,
    issue_type TEXT,
    ground_truth INTEGER NOT NULL DEFAULT 0
        CHECK(ground_truth IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_quote_account
ON Quote(account_id);

CREATE INDEX IF NOT EXISTS idx_order_account
ON SalesOrder(account_id);

CREATE INDEX IF NOT EXISTS idx_invoice_order
ON Invoice(order_id);

CREATE INDEX IF NOT EXISTS idx_payment_account
ON Payment(account_id);

CREATE INDEX IF NOT EXISTS idx_event_entity
ON StatusEvent(entity_type, entity_id, event_time);
