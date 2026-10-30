"""Read-only execution version selection; collector envelopes are never origin proof."""
import copy
import hashlib
import json
from harness.usage_provenance import execution_proof
from harness.dashboard_live import time_value

UNKNOWN = 'UNKNOWN'


def version_identity(task, run, events):
    identity = execution_proof(task, run, events)['execution_identity']
    if not identity or identity.get('version') in (None, '', UNKNOWN):
        return UNKNOWN, None
    if not identity.get('source_sha256') and not (identity.get('commit') not in (None, '', UNKNOWN) and identity.get('dirty') is False):
        return UNKNOWN, None
    identity = {k: identity.get(k) for k in ('version', 'commit', 'dirty', 'source_sha256')}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return key, identity


def select(tasks, events, scope, selected=None, start=None, end=None, project_selected=False):
    lo=time_value(start) if start else None; hi=time_value(end) if end else None
    if (start and not lo) or (end and not hi) or (lo and hi and lo >= hi):
        raise ValueError('invalid period')
    def overlap(run):
        a=time_value(run.get('started_at')); b=time_value(run.get('ended_at'))
        return not (lo or hi) or bool(a and (not hi or a < hi) and (not lo or b is None or b >= lo))
    identities={}; run_keys={}; options={}
    for task in tasks.values():
        for run in task.get('executions', []):
            aid=run.get('agent_run_id'); key, identity=version_identity(task, run, events)
            if aid in run_keys and run_keys[aid] != key: key, identity=UNKNOWN,None
            run_keys[aid]=key; identities[aid]=identity
    for aid,key in run_keys.items():
        identity=identities[aid]
        label='미확인' if key==UNKNOWN else str(identity['version'])+' · '+str(identity.get('commit') or '커밋 미확인')[:12]+(' · '+('변경 소스 ' if identity.get('dirty') else '소스 ')+hashlib.sha256(json.dumps(identity['source_sha256'],sort_keys=True).encode()).hexdigest()[:12] if identity.get('source_sha256') else '')
        options[key]={'key':key,'label':label,'identity':identity}
    if any(e.get('event_type')=='model_usage' and e.get('agent_run_id') not in run_keys for e in events):
        options.setdefault(UNKNOWN,{'key':UNKNOWN,'label':'미확인','identity':None})
    if selected and selected not in options: raise ValueError('unknown agent_version selection')
    active=bool(selected or start or end or project_selected)
    if not active: return tasks, events, scope, list(options.values()), run_keys, False
    allowed=set(scope.get('agent_run_ids', [])) if scope else set(run_keys)
    allowed={aid for aid in allowed if not selected or run_keys.get(aid,UNKNOWN)==selected}
    filtered={}
    for tid,task in tasks.items():
        runs=[r for r in task.get('executions',[]) if r.get('agent_run_id') in allowed and overlap(r)]
        if not runs: continue
        item=copy.deepcopy(task); item['executions']=runs
        item['reviews']=[r for r in item.get('reviews',[]) if r.get('agent_run_id') in {r.get('agent_run_id') for r in runs}]
        if len(runs)!=len(task.get('executions',[])):
            item['_filter_partial']=True
        if item.get('_filter_partial'):
            item['state']='IN_PROGRESS' if any(not r.get('ended_at') for r in runs) else 'IN_REVIEW'
            item.pop('qa_config',None)
        filtered[tid]=item
    allowed={r['agent_run_id'] for t in filtered.values() for r in t['executions']}
    # Explicit usage bindings can connect an imported envelope without changing its source identity.
    bindings={}
    for task in tasks.values():
        for run in task.get('executions',[]):
            for b in run.get('usage_bindings',[]):
                bindings.setdefault((b.get('session_id'),b.get('response_id')),set()).add(run.get('agent_run_id'))
    kept=[]
    for event in events:
        at=time_value(event.get('timestamp'))
        if (lo or hi) and not (at and (not lo or at>=lo) and (not hi or at<hi)):continue
        aid=event.get('agent_run_id')
        if event.get('event_type')=='model_usage':
            owners=bindings.get((event.get('source',{}).get('session_id'),event.get('observed',{}).get('response_id')),set())
            if owners & allowed:
                kept.append(event); continue
            if len(owners)==1 and aid in (None,'',UNKNOWN):aid=next(iter(owners))
            if selected==UNKNOWN and aid not in run_keys and not scope and not project_selected:
                kept.append(event); continue
        if aid in allowed:kept.append(event)
    scoped=copy.deepcopy(scope) if scope else None
    if scoped:
        scoped['agent_run_ids']=list(allowed)
        scoped['tasks']={tid:cfg for tid,cfg in scoped.get('tasks',{}).items() if tid in filtered}
    return filtered, kept, scoped, list(options.values()), run_keys, True
