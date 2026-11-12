"""Minimal process transport fixture; no application or model behavior."""
import json
import sys


def produce(packet):
    revision = 'revised' if packet['delivery'].get('change_id') else 'initial'
    if packet['role'] == 'planning':
        files = {'requirements.md': 'Synthetic contract input; REQ-001 and REQ-002; '+revision}
    else:
        html = '<!doctype html><html><meta charset="utf-8"><link rel="stylesheet" href="tokens.css"><p data-screen-id="SCREEN-001">Synthetic asset '+revision+'</p></html>'
        files = {'design.md':'Synthetic asset contract; source-only checks, no browser observation.',
                 'prototype/index.html':html,
                 'prototype/components.html':'<!doctype html><html><link rel="stylesheet" href="tokens.css"><p>Contract element</p></html>',
                 'prototype/tokens.css':':root{--ink:#123}body{color:var(--ink)}',
                 'prototype/system.md':'Synthetic shared stylesheet contract.'}
    return {'status':'submitted','files':[{'path':p,'content':c} for p,c in files.items()],
            'summary':'Synthetic protocol output; no product or model claim','questions':[],'completed':['transport']}


if __name__ == '__main__':
    print(json.dumps(produce(json.load(sys.stdin))))
