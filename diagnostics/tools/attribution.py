#!/usr/bin/env python3
"""Isolated-replay attribution diagnostic (read-only).

Compares materialized result documents edition by edition, using bottle states
and trigger numbers only as locators. Holding-time findings can only be
attributed where a bottle is actually `received` (full field -> transport ->
lab custody, ordered, starting at sample time) and the assay happens after lab
receipt. Every other assay failure blocks the holding-time question, so any
holding change there is NOT attributable from this evidence.
"""
import argparse
import json


def bottle_locator(result):
    out = {}
    for b in result['bottles']:
        if b['bottle'] is None:
            continue
        out[b['bottle']] = b
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('labeled', nargs='+', help='label=result.json')
    ap.add_argument('--holds', default='m1=60,m2=20',
                    help='method hold_s from the sealed input contract')
    args = ap.parse_args()
    holds = dict((k, int(v)) for k, v in (p.split('=') for p in args.holds.split(',')))
    editions = {}
    for item in args.labeled:
        label, _, path = item.partition('=')
        with open(path, encoding='utf-8') as fh:
            editions[label] = json.load(fh)

    report = {'editions': {}, 'cross_edition_attribution': []}
    detail = {}
    for label, doc in editions.items():
        bottles = bottle_locator(doc)
        assays = []
        for ev in doc['assays']:
            b = bottles[ev['bottle']]
            max_hold = holds[ev['method']]
            # sampled/received times are only available for received bottles
            attributable = (b['state'] == 'received')
            if ev['state'] == 'holding_expired':
                verdict = 'holding_violation_attributable'
            elif ev['state'] == 'supported':
                verdict = 'holding_ok_attributable'
            else:
                verdict = ('holding_question_blocked_'
                           + ('custody_incomplete' if b['state'] != 'received'
                              else ev['state']))
            assays.append({
                'assay': ev['assay'], 'bottle': ev['bottle'], 'method': ev['method'],
                'trigger_locator_only': ev['trigger'],
                'bottle_state': b['state'], 'assay_state': ev['state'],
                'method_hold_s': max_hold,
                'holding_time_attributable': attributable and ev['state'] in
                ('supported', 'holding_expired'),
                'verdict': verdict,
            })
        report['editions'][label] = {
            'bottles': [{'bottle': b['bottle'], 'trigger_locator': b['trigger'],
                         'state': b['state'], 'sampled_s': b['sampled_s'],
                         'received_s': b['received_s']}
                        for b in doc['bottles'] if b['bottle']],
            'assays': assays,
            'methods': doc['methods'],
        }
        detail[label] = {a['assay']: a for a in assays}

    names = list(editions)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            x, y = names[i], names[j]
            for key in sorted(detail[x]):
                ax, ay = detail[x][key], detail[y][key]
                if ax['verdict'] == ay['verdict']:
                    continue
                blocked = ('blocked' in ax['verdict'] or 'blocked' in ay['verdict'])
                report['cross_edition_attribution'].append({
                    'assay': key, 'between': [x, y],
                    'from_verdict': ax['verdict'], 'to_verdict': ay['verdict'],
                    'holding_change_attributable': not blocked,
                    'reason': ('a non-received bottle or pre-receipt/invalid assay '
                               'blocks the holding-time question; custody, not hold '
                               'time, is the proximate gate') if blocked
                    else 'both editions reach the holding test',
                })
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
