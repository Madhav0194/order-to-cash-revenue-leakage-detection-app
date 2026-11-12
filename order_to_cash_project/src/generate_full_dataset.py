import csv
import hashlib
import json
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / 'data' / 'full'
RAW = BASE / 'raw'
PROCESSED = BASE / 'processed'
TRUTH = BASE / 'ground_truth'
SEED = 20261022
CUTOFF = date(2026, 10, 31)
RNG = random.Random(SEED)
CENT = Decimal('0.01')


def cash(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def save(folder, name, fields, rows):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def event_time(day, hour):
    return datetime.combine(day, datetime.min.time()).replace(hour=hour).isoformat(timespec='seconds')


def main():
    RNG.seed(SEED)
    accounts, quotes, quote_lines, orders, order_lines = [], [], [], [], []
    shipments, shipment_lines, invoices, invoice_lines = [], [], [], []
    payments, allocations, disputes, dispute_timeline = [], [], [], []
    balances, events = [], []
    quote_line_seq = order_line_seq = shipment_line_seq = invoice_line_seq = 0
    payment_seq = allocation_seq = 0

    def ev(kind, entity_id, previous, new, day, hour):
        assert day <= CUTOFF, (kind, entity_id, day)
        events.append(dict(event_id='', entity_type=kind, entity_id=entity_id,
                           old_status=previous, new_status=new,
                           event_time=event_time(day, hour), issue_type=''))

    for i in range(1, 251):
        accounts.append(dict(account_id=f'ACC-2026-{i:06d}', account_name=f'Synthetic Account {i:04d}',
                             industry=['Technology', 'Retail', 'Manufacturing', 'Services'][i % 4],
                             created_at='2025-12-01', status='ACTIVE'))

    for i in range(1, 10001):
        qid = f'QUO-2026-{i:06d}'
        aid = accounts[(i - 1) % 250]['account_id']
        qday = date(2026, 1, 1) + timedelta(days=RNG.randint(0, 65))
        valid = qday + timedelta(days=20)
        qstatus = 'ACCEPTED' if i <= 7000 else ['SENT', 'REJECTED', 'EXPIRED'][(i - 7001) // 1000]
        quotes.append(dict(quote_id=qid, account_id=aid, quote_date=qday.isoformat(),
                           valid_until=valid.isoformat(), status=qstatus))
        ev('Quote', qid, '', 'DRAFT', qday, 9)
        ev('Quote', qid, 'DRAFT', 'SENT', qday, 10)
        if qstatus != 'SENT':
            finalday = valid + timedelta(days=1) if qstatus == 'EXPIRED' else qday + timedelta(days=1)
            ev('Quote', qid, 'SENT', qstatus, finalday, 11)

        oid = f'SO-2026-{i:06d}' if i <= 7000 else None
        oday = qday + timedelta(days=2)
        sday = oday + timedelta(days=3)
        if oid:
            orders.append(dict(order_id=oid, quote_id=qid, account_id=aid,
                               order_date=oday.isoformat(), status='FULFILLED'))
            ev('SalesOrder', oid, '', 'CREATED', oday, 9)
            ev('SalesOrder', oid, 'CREATED', 'CONFIRMED', oday, 10)
            sid = f'SHP-2026-{i:06d}'
            shipments.append(dict(shipment_id=sid, order_id=oid, shipment_date=sday.isoformat(),
                                  status='DELIVERED'))
            ev('Shipment', sid, '', 'CREATED', oday, 12)
            ev('Shipment', sid, 'CREATED', 'DISPATCHED', sday - timedelta(days=1), 10)
            ev('Shipment', sid, 'DISPATCHED', 'DELIVERED', sday, 12)
            ev('SalesOrder', oid, 'CONFIRMED', 'FULFILLED', sday, 16)

        nlines = RNG.randint(1, 3)
        local_lines = []
        for j in range(nlines):
            quote_line_seq += 1
            qlid = f'QL-2026-{quote_line_seq:06d}'
            qty = RNG.randint(4, 12)
            price = cash(RNG.randint(150, 25000))
            quote_lines.append(dict(quote_line_id=qlid, quote_id=qid,
                                    product_name=f'Product-{RNG.randint(1, 120):03d}',
                                    quantity=qty, unit_price=str(price)))
            if oid:
                order_line_seq += 1
                olid = f'OL-2026-{order_line_seq:06d}'
                order_lines.append(dict(order_line_id=olid, order_id=oid, quote_line_id=qlid,
                                        quantity=qty, unit_price=str(price)))
                shipment_line_seq += 1
                shipment_lines.append(dict(shipment_line_id=f'SHL-2026-{shipment_line_seq:06d}',
                                           shipment_id=sid, order_line_id=olid, quantity=qty))
                local_lines.append((olid, qty, price))

        if not oid:
            continue

        # First 1,000 orders have two invoices; remaining 6,000 have one.
        invoice_count = 2 if i <= 1000 else 1
        for part in range(invoice_count):
            invoice_index = i * 2 - 1 + part if i <= 1000 else i + 1000
            iid = f'INV-2026-{invoice_index:06d}'
            iday = sday + timedelta(days=1 + part)
            due = iday + timedelta(days=30)
            invoice_total = Decimal('0.00')
            for olid, qty, price in local_lines:
                billed_qty = (qty // 2 if part == 0 else qty - qty // 2) if invoice_count == 2 else qty
                invoice_line_seq += 1
                invoice_lines.append(dict(invoice_line_id=f'IL-2026-{invoice_line_seq:06d}',
                                          invoice_id=iid, order_line_id=olid,
                                          quantity=billed_qty, unit_price=str(price)))
                invoice_total += price * billed_qty

            # Exactly 15,000 payments: first 7,000 invoices get 2, last 1,000 get 1.
            n_payments = 2 if invoice_index <= 7000 else 1
            # Every fifth invoice remains partially unpaid at the reporting cutoff.
            target = cash(invoice_total * (Decimal('0.65') if invoice_index % 5 == 0 else Decimal('1.00')))
            amounts = ([cash(target * Decimal('0.40')), target - cash(target * Decimal('0.40'))]
                       if n_payments == 2 else [target])
            paid = Decimal('0.00')
            invoice_events = []
            for k, amount in enumerate(amounts):
                payment_seq += 1
                allocation_seq += 1
                pid = f'PAY-2026-{payment_seq:06d}'
                pday = iday + timedelta(days=5 + k * 5)
                payments.append(dict(payment_id=pid, account_id=aid, payment_date=pday.isoformat(),
                                     amount=str(amount), status='ALLOCATED'))
                allocations.append(dict(allocation_id=f'PAL-2026-{allocation_seq:06d}',
                                        payment_id=pid, invoice_id=iid, allocated_amount=str(amount)))
                ev('Payment', pid, '', 'RECEIVED', pday, 9)
                ev('Payment', pid, 'RECEIVED', 'ALLOCATED', pday, 10)
                invoice_events.append((pday, amount))
                paid += amount

            outstanding = invoice_total - paid
            invoice_status = 'PAID' if outstanding == 0 else 'OVERDUE'
            invoices.append(dict(invoice_id=iid, order_id=oid, invoice_date=iday.isoformat(),
                                 due_date=due.isoformat(), status=invoice_status))
            ev('Invoice', iid, '', 'ISSUED', iday, 9)
            running = Decimal('0.00')
            previous = 'ISSUED'
            for pday, amount in invoice_events:
                running += amount
                new = 'PAID' if running == invoice_total else 'PARTIALLY_PAID'
                if new != previous:
                    ev('Invoice', iid, previous, new, pday, 11)
                    previous = new
            if outstanding > 0:
                ev('Invoice', iid, previous, 'OVERDUE', due + timedelta(days=1), 9)

            days_overdue = max(0, (CUTOFF - due).days) if outstanding > 0 else 0
            aging = ('PAID' if outstanding == 0 else 'CURRENT' if days_overdue == 0
                     else '1-30' if days_overdue <= 30 else '31-60' if days_overdue <= 60
                     else '61-90' if days_overdue <= 90 else '90+')
            balances.append(dict(invoice_id=iid, account_id=aid, invoice_total=str(invoice_total),
                                 allocated_amount=str(paid), outstanding_balance=str(outstanding),
                                 due_date=due.isoformat(), days_overdue=days_overdue,
                                 aging_bucket=aging, payment_status=invoice_status))

    # 400 disputes, with actual dated transitions and a matching source timeline.
    disputed = [b for b in balances if Decimal(b['outstanding_balance']) > 0]
    for idx, balance in enumerate(disputed[:400], 1):
        iid = balance['invoice_id']
        # Open well after the invoice issue date, and before cutoff.
        due = date.fromisoformat(balance['due_date'])
        opened = due + timedelta(days=2)
        investigated = opened + timedelta(days=1)
        resolved = investigated + timedelta(days=2)
        status = ['OPEN', 'INVESTIGATING', 'RESOLVED'][idx % 3]
        did = f'DSP-2026-{idx:06d}'
        disputed_amount = cash(Decimal(balance['outstanding_balance']) * Decimal('0.50'))
        disputes.append(dict(dispute_id=did, invoice_id=iid, opened_at=opened.isoformat(),
                             disputed_amount=str(disputed_amount), status=status))
        timeline = dict(dispute_id=did, opened_at=opened.isoformat(),
                        investigating_at=investigated.isoformat() if status != 'OPEN' else '',
                        resolved_at=resolved.isoformat() if status == 'RESOLVED' else '')
        dispute_timeline.append(timeline)
        ev('Dispute', did, '', 'OPEN', opened, 9)
        if status != 'OPEN':
            ev('Dispute', did, 'OPEN', 'INVESTIGATING', investigated, 9)
        if status == 'RESOLVED':
            ev('Dispute', did, 'INVESTIGATING', 'RESOLVED', resolved, 9)

    # Deterministic chronological order and IDs; no ground_truth in input data.
    events.sort(key=lambda r: (r['event_time'], r['entity_type'], r['entity_id'], r['new_status']))
    for idx, row in enumerate(events, 1):
        row['event_id'] = f'EVT-2026-{idx:07d}'

    outputs = [
        (RAW, 'accounts.csv', accounts, ['account_id','account_name','industry','created_at','status']),
        (RAW, 'quotes.csv', quotes, ['quote_id','account_id','quote_date','valid_until','status']),
        (RAW, 'quote_lines.csv', quote_lines, ['quote_line_id','quote_id','product_name','quantity','unit_price']),
        (RAW, 'sales_orders.csv', orders, ['order_id','quote_id','account_id','order_date','status']),
        (RAW, 'order_lines.csv', order_lines, ['order_line_id','order_id','quote_line_id','quantity','unit_price']),
        (RAW, 'shipments.csv', shipments, ['shipment_id','order_id','shipment_date','status']),
        (RAW, 'shipment_lines.csv', shipment_lines, ['shipment_line_id','shipment_id','order_line_id','quantity']),
        (RAW, 'invoices.csv', invoices, ['invoice_id','order_id','invoice_date','due_date','status']),
        (RAW, 'invoice_lines.csv', invoice_lines, ['invoice_line_id','invoice_id','order_line_id','quantity','unit_price']),
        (RAW, 'payments.csv', payments, ['payment_id','account_id','payment_date','amount','status']),
        (RAW, 'payment_allocations.csv', allocations, ['allocation_id','payment_id','invoice_id','allocated_amount']),
        (RAW, 'disputes.csv', disputes, ['dispute_id','invoice_id','opened_at','disputed_amount','status']),
        (RAW, 'dispute_timeline.csv', dispute_timeline, ['dispute_id','opened_at','investigating_at','resolved_at']),
        (RAW, 'status_events.csv', events, ['event_id','entity_type','entity_id','old_status','new_status','event_time','issue_type']),
        (PROCESSED, 'invoice_balances.csv', balances, ['invoice_id','account_id','invoice_total','allocated_amount','outstanding_balance','due_date','days_overdue','aging_bucket','payment_status']),
        (TRUTH, 'ground_truth.csv', [], ['anomaly_id','issue_type','entity_type','entity_id','related_id','ground_truth']),
    ]
    files = {}
    for folder, name, rows, fields in outputs:
        path = save(folder, name, fields, rows)
        files[str(path.relative_to(BASE)).replace('\\', '/')] = dict(
            rows=len(rows), sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    assert len(quotes) == 10000 and len(orders) == 7000
    assert len(invoices) == 8000 and len(payments) == 15000
    assert len(events) >= 15000
    assert len({r['invoice_id'] for r in invoices}) == 8000
    assert all(Decimal(b['invoice_total']) == Decimal(b['allocated_amount']) + Decimal(b['outstanding_balance']) for b in balances)
    manifest = dict(seed=SEED, cutoff=CUTOFF.isoformat(), files=files)
    (BASE / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('FULL DATASET GENERATED')
    for name, rows in [('Quotes',quotes),('Orders',orders),('Invoices',invoices),('Payments',payments),('Events',events),('Disputes',disputes)]:
        print(f'{name}: {len(rows):,}')
    print('Manifest:', BASE / 'manifest.json')


if __name__ == '__main__':
    main()
