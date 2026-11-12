import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / 'data' / 'full'
RAW = BASE / 'raw'
PROCESSED = BASE / 'processed'
TRUTH = BASE / 'ground_truth'
CUTOFF = date(2026, 10, 31)


def read(folder, name):
    with (folder / name).open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    tables = {}
    keys = {
        'accounts': 'account_id', 'quotes': 'quote_id', 'quote_lines': 'quote_line_id',
        'sales_orders': 'order_id', 'order_lines': 'order_line_id',
        'shipments': 'shipment_id', 'shipment_lines': 'shipment_line_id',
        'invoices': 'invoice_id', 'invoice_lines': 'invoice_line_id',
        'payments': 'payment_id', 'payment_allocations': 'allocation_id',
        'disputes': 'dispute_id', 'dispute_timeline': 'dispute_id',
        'status_events': 'event_id'}
    for name, key in keys.items():
        rows = read(RAW, name + '.csv')
        require(len({r[key] for r in rows}) == len(rows), 'Duplicate primary key: ' + name)
        tables[name] = rows

    for name, count in [('quotes',10000), ('sales_orders',7000), ('invoices',8000), ('payments',15000)]:
        require(len(tables[name]) == count, f'Wrong {name} count')
    require(len(tables['status_events']) >= 15000, 'Not enough status events')
    require(len(tables['disputes']) == len(tables['dispute_timeline']), 'Dispute timeline count mismatch')
    require('ground_truth' not in tables['status_events'][0], 'Label leakage in events')
    require(all(r['issue_type'] == '' for r in tables['status_events']), 'Baseline contains labelled anomalies')
    require(len(read(TRUTH, 'ground_truth.csv')) == 0, 'Clean baseline must have empty ground truth')

    idx = {name: {r[key]: r for r in rows} for name, (rows, key) in
           ((n, (tables[n], k)) for n, k in keys.items())}
    fks = [
        ('quotes','account_id','accounts'), ('quote_lines','quote_id','quotes'),
        ('sales_orders','quote_id','quotes'), ('sales_orders','account_id','accounts'),
        ('order_lines','order_id','sales_orders'), ('order_lines','quote_line_id','quote_lines'),
        ('shipments','order_id','sales_orders'), ('shipment_lines','shipment_id','shipments'),
        ('shipment_lines','order_line_id','order_lines'), ('invoices','order_id','sales_orders'),
        ('invoice_lines','invoice_id','invoices'), ('invoice_lines','order_line_id','order_lines'),
        ('payments','account_id','accounts'), ('payment_allocations','payment_id','payments'),
        ('payment_allocations','invoice_id','invoices'), ('disputes','invoice_id','invoices'),
        ('dispute_timeline','dispute_id','disputes')]
    for child, field, parent in fks:
        for row in tables[child]:
            require(row[field] in idx[parent], f'Foreign key: {child}.{field} -> {parent}')

    for o in tables['sales_orders']:
        q = idx['quotes'][o['quote_id']]
        require(q['status'] == 'ACCEPTED' and q['account_id'] == o['account_id'], 'Order quote mismatch')
        require(date.fromisoformat(o['order_date']) >= date.fromisoformat(q['quote_date']), 'Order before quote')
    for sl in tables['shipment_lines']:
        s = idx['shipments'][sl['shipment_id']]
        ol = idx['order_lines'][sl['order_line_id']]
        require(s['order_id'] == ol['order_id'], 'Shipment line wrong order')
    for il in tables['invoice_lines']:
        inv = idx['invoices'][il['invoice_id']]
        ol = idx['order_lines'][il['order_line_id']]
        require(inv['order_id'] == ol['order_id'], 'Invoice line wrong order')
    for a in tables['payment_allocations']:
        inv = idx['invoices'][a['invoice_id']]
        order = idx['sales_orders'][inv['order_id']]
        p = idx['payments'][a['payment_id']]
        require(p['account_id'] == order['account_id'], 'Cross-account payment')
        require(date.fromisoformat(p['payment_date']) >= date.fromisoformat(inv['invoice_date']), 'Payment before invoice')

    ordered = {r['order_line_id']: int(r['quantity']) for r in tables['order_lines']}
    shipped, billed = defaultdict(int), defaultdict(int)
    for r in tables['shipment_lines']:
        shipped[r['order_line_id']] += int(r['quantity'])
    for r in tables['invoice_lines']:
        billed[r['order_line_id']] += int(r['quantity'])
    for lid, qty in ordered.items():
        require(qty > 0 and shipped[lid] == qty and billed[lid] == qty,
                'Order/shipment/invoice quantity mismatch: ' + lid)

    totals = defaultdict(lambda: Decimal('0.00'))
    paid = defaultdict(lambda: Decimal('0.00'))
    allocated_payment = defaultdict(lambda: Decimal('0.00'))
    for line in tables['invoice_lines']:
        totals[line['invoice_id']] += Decimal(line['unit_price']) * int(line['quantity'])
    for a in tables['payment_allocations']:
        amt = Decimal(a['allocated_amount'])
        paid[a['invoice_id']] += amt
        allocated_payment[a['payment_id']] += amt
    for p in tables['payments']:
        require(allocated_payment[p['payment_id']] == Decimal(p['amount']), 'Payment mismatch')
    balances = read(PROCESSED, 'invoice_balances.csv')
    require(len(balances) == 8000, 'Wrong invoice balance count')
    for b in balances:
        iid = b['invoice_id']
        require(totals[iid] == Decimal(b['invoice_total']), 'Invoice total mismatch: ' + iid)
        require(paid[iid] == Decimal(b['allocated_amount']), 'Allocation mismatch: ' + iid)
        require(totals[iid] - paid[iid] == Decimal(b['outstanding_balance']), 'Receivable mismatch: ' + iid)
        require(Decimal(b['outstanding_balance']) >= 0, 'Negative balance: ' + iid)

    allowed = {
        'Quote': {'': {'DRAFT'}, 'DRAFT': {'SENT'}, 'SENT': {'ACCEPTED','REJECTED','EXPIRED'}},
        'SalesOrder': {'': {'CREATED'}, 'CREATED': {'CONFIRMED'}, 'CONFIRMED': {'FULFILLED'}},
        'Shipment': {'': {'CREATED'}, 'CREATED': {'DISPATCHED'}, 'DISPATCHED': {'DELIVERED'}},
        'Invoice': {'': {'ISSUED'}, 'ISSUED': {'PARTIALLY_PAID','PAID'},
                    'PARTIALLY_PAID': {'PAID','OVERDUE'}},
        'Payment': {'': {'RECEIVED'}, 'RECEIVED': {'ALLOCATED'}},
        'Dispute': {'': {'OPEN'}, 'OPEN': {'INVESTIGATING'}, 'INVESTIGATING': {'RESOLVED'}}}
    entity_tables = {'Quote':'quotes','SalesOrder':'sales_orders','Shipment':'shipments',
                     'Invoice':'invoices','Payment':'payments','Dispute':'disputes'}
    history = defaultdict(list)
    for e in tables['status_events']:
        require(e['entity_type'] in entity_tables, 'Unknown event entity')
        require(e['entity_id'] in idx[entity_tables[e['entity_type']]], 'Orphan event')
        require(datetime.fromisoformat(e['event_time']).date() <= CUTOFF, 'Future event')
        history[(e['entity_type'],e['entity_id'])].append(e)
    for (kind, entity), rows in history.items():
        rows.sort(key=lambda r: (r['event_time'],r['event_id']))
        prev = ''
        for row in rows:
            require(row['old_status'] == prev, f'Broken event chain: {kind} {entity}')
            require(row['new_status'] in allowed[kind].get(prev,set()),
                    f'Invalid event transition: {kind} {entity} {prev}->{row["new_status"]}')
            prev = row['new_status']
    for kind, table in entity_tables.items():
        for entity in idx[table]:
            require((kind,entity) in history, f'Missing history: {kind} {entity}')

    timeline = idx['dispute_timeline']
    for dispute in tables['disputes']:
        did = dispute['dispute_id']
        t = timeline[did]
        actual = history[('Dispute',did)]
        require(actual[-1]['new_status'] == dispute['status'], 'Dispute status mismatch: ' + did)
        require(actual[0]['event_time'][:10] == t['opened_at'], 'Dispute open date mismatch')
        if dispute['status'] in ('INVESTIGATING','RESOLVED'):
            require(actual[1]['event_time'][:10] == t['investigating_at'], 'Investigation date mismatch')
        if dispute['status'] == 'RESOLVED':
            require(actual[2]['event_time'][:10] == t['resolved_at'], 'Resolution date mismatch')

    manifest = json.loads((BASE / 'manifest.json').read_text(encoding='utf-8'))
    require(manifest['seed'] == 20261022, 'Wrong seed')
    for rel, info in manifest['files'].items():
        path = BASE / rel
        require(hashlib.sha256(path.read_bytes()).hexdigest() == info['sha256'], 'Checksum mismatch: ' + rel)
    print('FULL DATASET VALIDATION PASSED')
    print('Quotes:',len(tables['quotes']))
    print('Orders:',len(tables['sales_orders']))
    print('Invoices:',len(tables['invoices']))
    print('Payments:',len(tables['payments']))
    print('Events:',len(tables['status_events']))
    print('Dispute history warnings: 0')
    print('All file checksums verified')


if __name__ == '__main__':
    try:
        main()
    except (AssertionError, FileNotFoundError, KeyError, ValueError) as error:
        print('VALIDATION FAILED:', error)
        sys.exit(1)
