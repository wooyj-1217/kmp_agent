"""Read-only, loopback project dashboard. Never instantiate Tasks/Logger (reads mutate).

Scope connections live in .harness/dashboard-scopes.json; task status remains canonical.
No inferred run membership, model calls, writes, or raw log endpoints.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import re
import select
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs, quote
from harness.dashboard_usage import token_parts, enrich_usage, apply_recorded_labels
from harness.dashboard_live import runtime_scopes, activity_view
from harness.dashboard_events import NativeEvents
from harness.dashboard_filter import filter_result

STAGES = ['planning', 'design', 'development', 'verification', 'report']
LABELS = dict(zip(STAGES, ['기획', '디자인', '개발', '검증', '리포트']))
UNKNOWN = 'UNKNOWN'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path, fallback):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return fallback


def stamp():
    return datetime.now(timezone.utc).isoformat()


def registered_files(registry):
    refs = []
    for scope in registry.get('scopes', []):
        refs.extend(scope.get('artifacts', []) + scope.get('approved_baselines', []))
        for t in scope.get('tasks', {}).values():
            refs.extend(t.get('documents', []))
        for c in scope.get('comparisons', []):
            refs.extend(c.get('images', []))
    return {r.get('path') for r in refs}


def document_html(root, name, allowed):
    """Small escaped document reader, not arbitrary Markdown/HTML execution."""
    path = safe_file(root, name); text = path.read_text()
    def inline(text):
        result = []; end = 0
        for m in re.finditer(r'\[([^\]]+)\]\(([^)]+)\)', text):
            result.append(html.escape(text[end:m.start()])); label, target = m.groups()
            bits = urlparse(target)
            dest = (path.parent / bits.path).resolve()
            relative = str(dest.relative_to(root)) if dest.is_relative_to(root) else None
            if not bits.scheme and relative in allowed:
                result.append('<a href="/document?path=' + quote(relative) + ('#' + quote(bits.fragment) if bits.fragment else '') + '">' + html.escape(label) + '</a>')
            else:
                result.append(html.escape(label + ' (' + target + ')'))
            end = m.end()
        return ''.join(result) + html.escape(text[end:])
    if path.suffix == '.json':
        body = '<pre>' + html.escape(json.dumps(json.loads(text), ensure_ascii=False, indent=2)) + '</pre>'
    else:
        lines = []; code = False; table = False; first_row = False
        for line in text.splitlines():
            is_row = line.strip().startswith('|') and line.strip().endswith('|')
            if table and not is_row:
                lines.append('</table>'); table = False
            if line.startswith('```'):
                lines.append('</pre>' if code else '<pre>'); code = not code
            elif code:
                lines.append(html.escape(line) + '\n')
            elif is_row:
                if not table:
                    lines.append('<table style="border-collapse:collapse" border="1" cellpadding="8">'); table = True; first_row = True
                cells = line.strip().strip('|').split('|')
                if all(re.fullmatch(r'\s*:?-+:?\s*', c) for c in cells):
                    continue
                tag = 'th' if first_row else 'td'
                lines.append('<tr>' + ''.join(f'<{tag}>' + inline(c.strip()) + f'</{tag}>' for c in cells) + '</tr>'); first_row = False
            elif line.startswith('#'):
                level = min(6, len(line) - len(line.lstrip('#')))
                lines.append(f'<h{level}>' + inline(line[level:].strip()) + f'</h{level}>')
            else:
                lines.append('<p>' + inline(line) + '</p>')
        if code:
            lines.append('</pre>')
        if table:
            lines.append('</table>')
        body = ''.join(lines)
    return ('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>' + html.escape(name) + '</title><style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:16px;color:#182b3c}p{line-height:1.7;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f8;padding:16px}a{color:#155ea1}</style><p>읽기 전용 원문 문서 · <a href="/">대시보드로</a></p>' + body).encode()


def safe_file(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root) or any(p.startswith('.') for p in path.relative_to(root).parts):
        raise ValueError('private or outside-project file')
    if path.suffix.lower() not in {'.md', '.json', '.txt', '.html', '.css', '.png', '.jpg', '.svg', '.pdf'}:
        raise ValueError('unsupported document')
    if any(p in {'node_modules', 'build', 'data', 'logs'} for p in path.relative_to(root).parts):
        raise ValueError('private directory')
    if not path.is_file() or path.stat().st_size > 10_000_000:
        raise ValueError('missing or oversized document')
    return path


def reference(root, ref):
    if not isinstance(ref, dict):
        return {'label': '근거 미등록', 'state': 'UNKNOWN'}
    out = {'label': ref.get('label', ref.get('path', '문서')), 'path': ref.get('path'), 'state': 'UNKNOWN'}
    try:
        path = safe_file(root, ref['path'])
        out.update(url='/document?path=' + quote(ref['path']), extension=path.suffix.lower(),
                   state='CURRENT' if ref.get('sha256') == sha(path) else 'RECHECK_REQUIRED')
    except (OSError, ValueError, KeyError):
        out['state'] = 'MISSING'
    return out


def artifact_valid(root, ref):
    try:
        # Immutable artifacts may be private: inspect locally, never serve their directory.
        p = (root / ref['snapshot']).resolve()
        return p.is_relative_to(root) and p.is_file() and sha(p) == ref['snapshot_sha256']
    except (KeyError, TypeError, OSError):
        return False


def observation_summary(root, raw):
    """Read older nested test schemas without returning commands, env or memo bodies."""
    tests=[]; reports=[]; scopes=[]
    numeric={'tests','failures','failed','errors','skipped','exit_code','exit','passedTests','failedTests','skippedTests','totalTestCount','expectedFailures'}
    def add_report(path, expected):
        if not isinstance(path,str) or not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):
            return
        p=(root/path).resolve()
        reports.append({'path':path,'state':'현재 원본 해시 일치' if p.is_relative_to(root) and p.is_file() and sha(p)==expected else '현재 파일 변경/누락 · 당시 리포트 재검증 필요'})
    def walk(value, context='관측 기록', depth=0):
        if depth>6:return
        if isinstance(value,list):
            for i,child in enumerate(value):walk(child,context+f' / {i+1}',depth+1)
        elif isinstance(value,dict):
            row={k:v for k,v in value.items() if k in numeric and type(v) is int}
            if row:tests.append({'context':context,**row})
            for k,v in value.items():
                if k in {'reports','report_hashes'} and isinstance(v,dict):
                    for p,h in v.items():add_report(p,h)
                elif k.endswith('_sha256') and isinstance(v,str) and isinstance(value.get(k[:-7]),str):
                    add_report(value[k[:-7]],v)
                elif k in {'scope','covered','passed_scope','limits','NOT_RUN'}:
                    strings=v if isinstance(v,list) else [v]
                    scopes.extend({'context':context,'kind':k,'text':s} for s in strings if isinstance(s,str))
                elif k not in {'command','argv','environment','body','response_body','request_body'} and isinstance(v,(dict,list)):
                    walk(v,context+' / '+k,depth+1)
    walk(raw.get('observations'))
    for p,h in (raw.get('report_hashes') or {}).items() if isinstance(raw.get('report_hashes'),dict) else []:
        add_report(p,h)
    return tests,reports,scopes


def task_view(root, task, scope, tasks):
    tid = task['task_id']
    allowed = scope.get('agent_run_ids', []) if scope else []
    runs = [r for r in task.get('executions', []) if r.get('agent_run_id') in allowed]
    review = next((r for r in reversed(task.get('reviews', [])) if r.get('agent_run_id') in allowed), None)
    reasons = []
    verdict = 'NOT_RUN'
    if review:
        results = {r['criterion_id']: r for r in review.get('results', [])}
        required = [c['id'] for c in task.get('criteria', []) if c.get('required')]
        if any(results.get(c, {}).get('result') == 'FAIL' for c in required):
            verdict = 'FAIL'
        elif required and all(results.get(c, {}).get('result') == 'PASS' and artifact_valid(root, results[c].get('evidence')) for c in required):
            verdict = 'PASS'
        else:
            reasons.append('필수 기준의 실행 근거가 누락됐습니다')
        tracked = task.get('validation_status', {}).get(review['agent_run_id'], {})
        if tracked.get('state') == 'RECHECK_REQUIRED':
            reasons.extend(tracked.get('reasons') or ['기준·코드 변경 후 재검증이 필요합니다'])
            verdict = 'RECHECK_REQUIRED'
        if verdict == 'PASS':
            proof = review.get('development_evidence', {})
            if task.get('development_tracking'):
                try:
                    from harness.development_tracking import capture, baseline
                    current = capture(SimpleNamespace(root=root), task)
                    if current['state_sha256'] != proof.get('code_state', {}).get('state_sha256') or baseline(task) != proof.get('baseline'):
                        reasons.append('검증 후 코드 또는 입력 기준이 변경됐습니다')
                    for a in task.get('inputs', []):
                        p = (root / a.get('path', '')).resolve()
                        if not p.is_relative_to(root) or not p.is_file() or sha(p) != a.get('sha256') or not artifact_valid(root, a):
                            reasons.append('고정 입력과 현재 원본이 다릅니다')
                except (ValueError, OSError, KeyError):
                    reasons.append('현재 코드·입력의 검증 유효성을 확인할 수 없습니다')
            elif not review.get('outputs') or any(not artifact_valid(root, a) or not (root / a.get('path', '')).is_file() or sha(root / a['path']) != a.get('sha256') for a in review.get('outputs', [])):
                reasons.append('현재 산출물과 검토 대상의 일치를 확인할 수 없습니다')
            if task.get('visual_required') and any(task.get('design_status', {}).get('checks', {}).get(k, {}).get('result') != 'PASS' for k in ('structure', 'interaction', 'visual')):
                reasons.append('구조·상태·시각 비교 근거가 부족합니다')
            if reasons:
                verdict = 'RECHECK_REQUIRED'
    from harness.verification import current_reasons, artifact_status
    if review:
        extra = current_reasons(SimpleNamespace(root=root), task, review)
        if extra:
            reasons.extend(extra)
            verdict = 'RECHECK_REQUIRED'
    applied = {a.get('path'): a.get('sha256') for a in task.get('inputs', [])}
    input_alignment = 'CURRENT'
    for ref in (scope or {}).get('approved_baselines', []):
        # Only explicit applicable baseline bindings are compared; no title inference.
        if tid in ref.get('task_ids', []):
            if applied.get(ref.get('path')) != ref.get('sha256') or reference(root, ref)['state'] != 'CURRENT':
                reasons.append('작업 입력과 현재 승인 기준이 다릅니다')
                input_alignment = 'MISMATCH'
                if review:
                    verdict = 'RECHECK_REQUIRED'
    active = [r for r in runs if not r.get('ended_at')]
    compliance = 'UNKNOWN'
    if review and verdict == 'PASS' and any(Path(a.get('path', '')).name == 'acceptance-contract.json' for a in task.get('inputs', [])):
        try:
            from harness.acceptance_contract import review_gate
            review_gate(SimpleNamespace(root=root, _valid_artifact=lambda a: artifact_valid(root, a)), task, review['results'])
            compliance = 'PASS'
        except (ValueError, OSError, KeyError, TypeError):
            compliance = 'RECHECK_REQUIRED'
    mapping = (scope or {}).get('tasks', {}).get(tid, {})
    if mapping.get('compliance_result') in {'NON_COMPLIANT', 'WEB_UNDECIDED'} and reference(root, mapping.get('compliance_basis'))['state'] == 'CURRENT':
        compliance = mapping['compliance_result']
    state = task.get('state', UNKNOWN)
    status = {'TODO': '예정', 'READY': '시작 준비', 'IN_PROGRESS': '진행 기록 있음', 'IN_REVIEW': '검토 대기', 'BLOCKED': '차단', 'DONE': '완료 보고 · 검증 미확인'}.get(state, '상태 미확인')
    if verdict == 'PASS':
        status = '해당 작업 필수 검토 통과'
    if verdict == 'RECHECK_REQUIRED':
        status = '재검증 필요'
    mapping = (scope or {}).get('tasks', {}).get(tid, {})
    summary_current = reference(root, mapping.get('summary_basis'))['state'] == 'CURRENT'
    criterion_applicability = None
    if mapping.get('assessment_scope') == 'document_configuration' and reference(root, mapping.get('assessment_basis'))['state'] == 'CURRENT':
        # Separate, task-specific read-only applicability. Never overwrite the original verdict.
        checks=[]
        inputs_current=all(artifact_valid(root,a) and (root/a['path']).is_file() and sha(root/a['path'])==a.get('sha256') for a in task.get('inputs',[]))
        for c in task.get('criteria',[]):
            if not c.get('required'):continue
            r=next((r for r in (review or {}).get('results',[]) if r['criterion_id']==c['id']),{})
            outputs=r.get('tested_outputs', (review or {}).get('outputs',[]))
            changed=[a['path'] for a in outputs if not artifact_valid(root,a) or not (root/a['path']).is_file() or sha(root/a['path'])!=a.get('sha256')]
            files=(review or {}).get('development_evidence',{}).get('code_state',{}).get('files',{})
            paths=task.get('development_tracking',{}).get('code_paths',[])
            tracking_current=all(p in files and (root/p).is_file() and sha(root/p)==files[p] for p in paths)
            check_state='PASS' if r.get('result')=='PASS' and outputs and not changed and inputs_current and tracking_current and artifact_valid(root,r.get('evidence')) else 'RECHECK_REQUIRED' if r else 'NOT_RUN'
            checks.append({'id':c['id'],'description':c.get('description'), 'state':check_state,'changed_outputs':changed,'inputs_current':inputs_current,'declared_files_current':tracking_current})
        criterion_applicability={'scope':'문서·설정 필수 기준만 · 제품 인수와 별개','checks':checks,
            'status':'설정 범위 검토 근거 유효' if checks and all(c['state']=='PASS' for c in checks) else '문서·설정 변경 영향 재검토 필요',
            'explanation':'필수 기준의 스냅샷·입력·제출 파일 및 선언 추적 파일을 비교. Git 커밋·인덱스만 달라진 것은 파일 변경과 분리. 원본 상태/검증 결과와 제품 완료 판정은 변경하지 않음.'}
    archived = []
    for record in task.get('reviews', []):
        if record['agent_run_id'] not in allowed:
            continue
        for result in record.get('results', []):
            a = result.get('evidence') or {}
            tested = result.get('tested_outputs', record.get('outputs', []))
            matches = []
            for o in tested:
                p = (root / o['path']).resolve()
                current_hash = sha(p) if p.is_relative_to(root) and p.is_file() else None
                matches.append({'path': o['path'], 'tested_sha256': o.get('sha256'), 'current_sha256': current_hash,
                                'state': '동일' if current_hash and current_hash == o.get('sha256') else '변경/누락'})
            execution = next((r for r in runs if r['agent_run_id'] == record['agent_run_id']), {})
            archived.append({'criterion': result['criterion_id'], 'result': result['result'],
                             'integrity': 'PASS' if artifact_valid(root, a) else artifact_status(root, a)['state'],
                             'recovery': artifact_status(root, a)['recovery'],
                             'url': '/evidence?task=' + quote(tid) + '&review=' + quote(record['agent_run_id']) + '&criterion=' + quote(result['criterion_id']),
                             'snapshot_sha256': a.get('snapshot_sha256'), 'tested_files': matches,
                             'reviewed_at': execution.get('ended_at') or execution.get('started_at')})
    bindings = []
    for a in task.get('inputs', []):
        path = (root / a.get('path', '')).resolve()
        h = sha(path) if path.is_relative_to(root) and path.is_file() else None
        bindings.append({'path': a.get('path'), 'frozen_sha256': a.get('sha256'), 'current_sha256': h,
                         'state': '일치' if h == a.get('sha256') else '변경 또는 원본 누락'})
    if task.get('_filter_partial'):
        verdict='UNKNOWN'; compliance='UNKNOWN'; status='선택 실행만 표시 · 작업 전체 판정 제외'
        reasons.append('다른 버전 또는 기간의 실행을 제외한 일부 보기')
    verification_summary = None
    if task.get('verification_contract'):
        contract=task['verification_contract']; rows=[]
        latest_results={x['criterion_id']:x for x in (review or {}).get('results',[])}
        for definition in contract['criteria']:
            result=latest_results.get(definition['id'],{})
            platforms=[]
            try:
                if artifact_valid(root,result.get('evidence')):
                    platforms=json.loads((root/result['evidence']['snapshot']).read_text()).get('platform_results',[])
            except (OSError,ValueError,KeyError): pass
            rows.append({'id':definition['id'],'required':next(c['required'] for c in task['criteria'] if c['id']==definition['id']),
                         'kind':definition['kind'],'result':'UNKNOWN' if task.get('_filter_partial') else 'RECHECK_REQUIRED' if verdict=='RECHECK_REQUIRED' else result.get('result','NOT_RUN'),
                         'platforms':[{'platform':p,'result':'UNKNOWN' if task.get('_filter_partial') else 'RECHECK_REQUIRED' if verdict=='RECHECK_REQUIRED' else next((x.get('result','NOT_RUN') for x in platforms if x.get('platform')==p),'NOT_RUN')} for p in definition['platforms']]})
        verification_summary={'goal':contract['goal'],'integrator':contract['integrator'],'criteria':rows,
                              'required':sum(c['required'] for c in rows),'passed':sum(c['required'] and c['result']=='PASS' for c in rows)}
    return {'id': tid, 'title': mapping.get('display_title') or task.get('title', tid), 'stage': mapping.get('stage'),
            'status': status, 'verdict': verdict, 'compliance': compliance, 'active': bool(active), 'raw_state': state,
            'criterion_applicability': criterion_applicability,
            'execution_gate': task.get('execution_gate'),
            'work_plan': task.get('work_plan'),
            'verification_summary': verification_summary,
            'verification_contract': task.get('verification_contract'),
            'verification_required': bool(task.get('verification_required')),
            'goal': task.get('verification_contract', {}).get('goal'),
            'scope': task.get('scope'), 'result': mapping.get('result_summary') if summary_current else None,
            'revalidation_summary': mapping.get('revalidation_summary') if summary_current else None,
            'display_kind': mapping.get('display_kind') if summary_current else None,
            'historical_reviews': archived, 'input_comparison': bindings,
            'input_alignment': input_alignment,
            'related_documents': [reference(root, r) for r in mapping.get('documents', [])],
            'output_documents':[reference(root,r) for r in task.get('outputs',[])],
            'input_documents':[reference(root,r) for r in task.get('inputs',[]) if not r.get('path','').startswith('.')],
            'design_previews':[{**reference(root,r),'interactive_preview':r.get('interactive_preview',False)} for r in (scope or {}).get('artifacts',[]) if r.get('kind')=='프로토타입' and any(a.get('path') in applied for a in r.get('derived_from',[]))],
            'historical_blocked': task.get('blocked_reason'),
            'next': mapping.get('next_action'), 'reasons': reasons, 'blocked': task.get('blocked_reason'),
            'kind': task.get('execution_scope') or '실행 종류 미확인',
            'dependencies': [{'title': tasks.get(d, {}).get('title', '연결 작업 미확인'), 'state': tasks.get(d, {}).get('state', UNKNOWN)} for d in task.get('dependencies', [])],
            'criteria': task.get('criteria', []), 'runs': [{'id': r.get('agent_run_id'), 'started_at': r.get('started_at'), 'ended_at': r.get('ended_at'), 'kind': r.get('kind')} for r in runs],
            'review_id': review.get('agent_run_id') if review else None}


def usage_view(events, scope, taskviews, pricing, source_tasks=None, collision_events=None):
    from harness.dashboard_usage import native_identity_conflict
    allowed = set(scope.get('agent_run_ids', []))
    bindings = {}
    for tid, task in (source_tasks or {}).items():
        for run in task.get('executions', []):
            for b in run.get('usage_bindings', []):
                bindings.setdefault((b.get('session_id'), b.get('response_id')), set()).add((tid, run.get('agent_run_id')))
    selected = []; conflicts = set(); identity_conflicts = set()
    collision_values={}; global_collisions=set()
    for original in collision_events or events:
        if original.get('event_type')!='model_usage':continue
        obs=original.get('observed',{});key=(original.get('source',{}).get('session_id'),obs.get('response_id'))
        value=(obs.get('usage'),obs.get('model'),obs.get('usage_semantics'))
        if key in collision_values and collision_values[key]!=value:global_collisions.add(key)
        collision_values[key]=value
    for event in events:
        if event.get('event_type') != 'model_usage':
            continue
        key = ((event.get('source') or {}).get('session_id'), (event.get('observed') or {}).get('response_id'))
        owners = bindings.get(key, set())
        within = [(tid, aid) for tid, aid in owners if aid in allowed]
        if within:
            if len(owners) != 1 or event.get('agent_run_id') not in (None, '', UNKNOWN, within[0][1]) or event.get('task_id') not in (None,'',UNKNOWN,within[0][0]):
                conflicts.add(key)
            event = {**event, 'task_id': within[0][0], 'agent_run_id': within[0][1]}
        if event.get('agent_run_id') in allowed:
            if key in global_collisions:conflicts.add(key)
            if native_identity_conflict(event):
                conflicts.add(key)
                identity_conflicts.add(key)
                continue
            canonical=[tid for tid,task in (source_tasks or {}).items() if any(r.get('agent_run_id')==event.get('agent_run_id') for r in task.get('executions',[]))]
            if len(canonical)==1:
                if event.get('task_id') not in (None,'',UNKNOWN,canonical[0]):conflicts.add(key)
                event={**event,'task_id':canonical[0]}
            elif len(canonical)>1:conflicts.add(key)
            if owners and not within:
                conflicts.add(key)
            selected.append(event)
    unique = {}; missing = 0
    for e in selected:
        obs = e.get('observed', {})
        key = (e.get('source', {}).get('session_id'), obs.get('response_id'))
        if not all(k and k != UNKNOWN for k in key):
            missing += 1
            continue
        value = (obs.get('usage'), obs.get('model'), e.get('task_id'), e.get('agent_run_id'), obs.get('usage_semantics'))
        if key in unique and unique[key][0] != value:
            conflicts.add(key)
        unique[key] = (value, e)
    rows = []; excluded = missing + len(conflicts)
    for key, ((u, model, tid, aid, semantics), e) in unique.items():
        if key in conflicts:
            continue
        if token_parts(u, e.get('observed',{}).get('usage_semantics')) is None:
            excluded += 1
            continue
        tokens = [u['input_tokens'] - u['cached_input_tokens'], u['cached_input_tokens'], u['output_tokens']]
        rate = pricing.get(model, {}) if isinstance(model, str) else {}
        rates = rate.get('usd_per_million', [])
        cost = sum(a*b for a, b in zip(tokens, rates))/1e6 if len(rates) == 3 and all(type(x) in (int, float) and x >= 0 for x in rates) and rate.get('as_of') and rate.get('source') else None
        t = next((t for t in taskviews if t['id'] == tid and any(r['id'] == aid for r in t['runs'])), None)
        rows.append({'project_id': (source_tasks or {}).get(tid,{}).get('project_id'), 'task': t['title'] if t else '귀속 불명', 'stage': LABELS.get(t['stage'], '귀속 불명') if t else '귀속 불명', 'hour': str(e.get('timestamp') or '시각 미확인')[:13], 'occurred_at':e.get('timestamp'), 'session_id':key[0], 'response_id':key[1], 'agent_run_id':aid, 'task_id':tid, 'attribution':'원장 명시 연결' if key in bindings else '이벤트 직접 연결', 'semantics':e.get('observed',{}).get('usage_semantics') or '기록에 의미 구분 없음', 'tokens': sum(tokens), 'normal_input': tokens[0], 'cached_input': tokens[1], 'output': tokens[2], 'cost': cost, 'model': model})
    return {'rows': rows, 'excluded': excluded,
            'identity_conflicts':[{'session_id':k[0],'response_id':k[1],'reason':'native_identity_conflict','tokens':None} for k in sorted(identity_conflicts,key=str)],
            'conflicts':[{'session_id':k[0],'response_id':k[1],'reason':'원본 세션/스레드 ID 불일치 · 합산 제외' if k in identity_conflicts else '응답 값 또는 명시 귀속 충돌 · 합산 제외'} for k in sorted(conflicts,key=str)], 'pricing': pricing, 'coverage': '연결된 응답만 집계합니다. 실행 전체 수집 완전성은 미확인입니다.'}


def snapshot(root, scope_id=None, start=None, end=None, agent_version=None, project_id=None):
    root = Path(root).resolve()
    state = load(root / '.harness/tasks/tasks.yaml', {'tasks': {}})
    registry = load(root / '.harness/dashboard-scopes.json', {'project_name': root.name, 'scopes': []})
    tasks = state.get('tasks', {})
    events = []; bad = 0
    path = root / '.harness/logs/events.jsonl'
    if path.exists():
        with path.open() as f:
            for line in f:
                try:
                    e = json.loads(line)
                    e['timestamp'] = (e.get('observed') or {}).get('occurred_at') or e.get('timestamp') or e.get('recorded_at')
                    for k in ('harness', 'source', 'observed'):
                        e[k] = e.get(k) or {}
                    events.append({k:e.get(k) for k in ('event_type','event_id','timestamp','recorded_at','agent_run_id','task_id','run_id','work_type','project_id','agent_summary','harness','source','observed')})
                except json.JSONDecodeError:
                    bad += 1
    scopes = registry.get('scopes', []) + runtime_scopes(tasks,events)
    # Live plan membership comes from native tasks/attempts, not manual status edits.
    for entry in scopes:
        rid=entry.get('plan_run_id');plan=state.get('execution_plans',{}).get(rid)
        if not plan:continue
        members=set(plan['task_ids'])
        links={e.get('task_id'):e.get('observed',{}).get('from_task_id') for e in events if e.get('event_type')=='stage_rework_created'}
        changed=True
        while changed:
            changed=False
            for tid,t in tasks.items():
                parent=t.get('parent_task_id') or (t.get('delegation') or {}).get('parent_task_id') or links.get(tid) or (t.get('qa_config') or {}).get('target_task_id')
                repair=next(((q.get('qa_config') or {}).get('target_task_id') for q in tasks.values() if (q.get('qa_config') or {}).get('repair_task_id')==tid),None)
                if tid not in members and (parent in members or repair in members) and t.get('project_id')==entry.get('project_id') and t.get('work_type')==entry.get('work_type'):
                    members.add(tid);changed=True
        ordered=[tid for tid in plan['task_ids'] if tid in tasks]+[tid for tid in tasks if tid in members and tid not in plan['task_ids']]
        entry['tasks']={tid:{'stage':tasks[tid].get('pipeline_stage'),'required':True} for tid in ordered}
        entry['agent_run_ids']=[r['agent_run_id'] for tid in ordered for r in tasks[tid].get('executions',[]) if r.get('run_id')==rid]
    if len({s['id'] for s in scopes}) != len(scopes):
        raise ValueError('duplicate scope identifiers')
    scope = next((s for s in scopes if s['id'] == scope_id), None)
    if scope:
        # Membership must name both tasks and exact attempts, never just a feature or time range.
        linked_runs = {r.get('agent_run_id') for tid in scope.get('tasks', {}) for r in tasks.get(tid, {}).get('executions', [])}
        if not set(scope.get('agent_run_ids', [])).issubset(linked_runs):
            raise ValueError('attempt belongs outside declared tasks')
        for tid in scope.get('tasks', {}):
            if tid in tasks and (scope.get('project_id') in (None, '', UNKNOWN) or not scope.get('work_type') or tasks[tid].get('project_id') != scope['project_id'] or tasks[tid].get('work_type') != scope['work_type']):
                raise ValueError('scope mixes project/work types or lacks explicit identity')
    # No automatic all-history funnel. Active hints are observed only within declared membership.
    choices = []
    for s in scopes:
        active=any(activity_view(tasks[tid],s,events)['kind']=='observed' for tid in s.get('tasks',{}) if tid in tasks)
        choices.append({'id':s['id'],'name':s.get('name',s['id']),'active':active,'project_id':s.get('project_id'),'work_type':s.get('work_type')})
    if state.get('execution_policy'):
        from harness.execution_policy import status as execution_status
        selected_run=(scope or {}).get('recorded_run_id') or (scope or {}).get('plan_run_id')
        for task in tasks.values():
            if task.get('execution_contract'):
                task['execution_gate']=execution_status(state,task,selected_run)
    source_tasks=tasks
    if project_id:
        if project_id not in {t.get('project_id') for t in tasks.values()}: raise ValueError('unknown project selection')
        if scope and scope.get('project_id') != project_id: raise ValueError('scope outside selected project')
        tasks={tid:t for tid,t in tasks.items() if t.get('project_id')==project_id}
    proof_events=events
    from harness.dashboard_versions import select as select_versions
    tasks, events, scope, version_options, run_versions, filtered = select_versions(tasks, events, scope, agent_version, start, end, bool(project_id))
    views = [task_view(root, tasks[tid], scope, tasks) for tid in (scope or {}).get('tasks', {}) if tid in tasks]
    for view in views:
        view['delegation']={k:tasks[view['id']][k] for k in ('parent_task_id','development_area','delegation_state','delegation_reason','changed_files','verification_evidence','child_task_ids','contract_change_request','change_reference') if k in tasks[view['id']]}
        if view['delegation'] and view.get('verdict')=='RECHECK_REQUIRED':
            view['delegation'].update(recorded_state=view['delegation'].get('delegation_state'),delegation_state='RECHECK_REQUIRED',delegation_reason='적용 기준·코드·검증 근거 변경; 과거 PASS 보존')
        source=tasks[view['id']]
        if source.get('qa_config'):
            cfg=source['qa_config'];attempts=cfg.get('attempts',[]);last=attempts[-1] if attempts else {};checks={}
            if last.get('report') and artifact_valid(root,last['report']):
                try:checks=json.loads((root/last['report']['path']).read_text()).get('criteria',{})
                except (ValueError,OSError):pass
            required=[c['id'] for c in source['criteria'] if c['required']]
            quality=last.get('outcome','NOT_RUN')
            if quality=='PASS' and view.get('verdict')=='RECHECK_REQUIRED':quality='RECHECK_REQUIRED'
            view['qa']={'stage':cfg['stage'],'stage_label':{'requirements':'원본·파생 명세 QA','planning':'기획 QA','design':'디자인 QA','implementation':'구현 QA','retest':'QA 재검증'}.get(cfg['stage'],cfg['stage']),
                'target_task_id':cfg['target_task_id'],'target_title':tasks.get(cfg['target_task_id'],{}).get('title','대상 미확인'),'qa_task_id':view['id'],
                'attempts':attempts,'required':{'total':len(required),'passed':sum(checks.get(c)=='PASS' for c in required),'failed':sum(checks.get(c)=='FAIL' for c in required),'not_run':sum(checks.get(c) in {'NOT_RUN','BLOCKED'} for c in required),'unknown':sum(c not in checks for c in required)},
                'open_findings':[i for i in state.get('issues',[]) if i.get('task_id')==cfg['target_task_id'] and i.get('qa_finding') and i.get('status')!='RESOLVED'],
                'quality_outcome':quality,'execution_observation':('실제 독립 QA 프로세스 생성 확인 · 품질 판정은 별도' if any(e.get('event_type')=='role_process' and e.get('agent_run_id') in {r['agent_run_id'] for r in source.get('executions',[]) if r.get('kind')=='work'} and e.get('observed',{}).get('independent_model_spawned') is True for e in events) else '독립 QA 프로세스 실행 근거 미확인')}
        view['activity']=activity_view(tasks[view['id']],scope,events)
        view['active']=view['activity']['kind']=='observed'

    gaps = []
    if scope:
        for tid in scope.get('tasks', {}):
            if tid not in tasks:
                gaps.append('등록한 작업을 원본에서 찾을 수 없습니다: ' + tid)
        if not scope.get('agent_run_ids'):
            gaps.append('실행 연결이 등록되지 않았습니다')
    stages = []
    for name in STAGES:
        members = [t for t in views if t['stage'] == name]
        required = [t for t in members if scope['tasks'][t['id']].get('required') is True]
        contract = (scope or {}).get('stage_requirements', {}).get(name)
        required_ids = set(contract.get('task_ids', [])) if isinstance(contract, dict) else set()
        valid_contract = bool(required_ids) and required_ids == {t['id'] for t in required} and bool(contract.get('basis'))
        if not valid_contract:
            status = '완료 여부 확인 불가'
        elif any(t['verdict'] == 'RECHECK_REQUIRED' for t in required):
            status = '수정·재검증 필요'
        elif any(t['blocked'] for t in required):
            status = '차단된 작업 있음'
        elif all(t['verdict'] == 'PASS' and (t['kind'] != 'code_implementation' or t['compliance'] == 'PASS') for t in required):
            status = '등록된 필수 작업 검토 통과'
        else:
            status = '필수 작업 미완료'
        stages.append({'name': LABELS[name], 'note': (scope or {}).get('stage_notes', {}).get(name), 'status': status,
                       'completion_evidence_missing':not valid_contract, 'active': any(t['active'] for t in members), 'count': len(members)})
    scoped_events = [e for e in events if e.get('agent_run_id') in (scope or {}).get('agent_run_ids', [])]
    selected_version_keys={run_versions.get(aid,'UNKNOWN') for aid in (scope or {}).get('agent_run_ids',[])}
    versions = sorted({str(o['identity']['version']) for o in version_options if o['key'] in selected_version_keys and o['identity']})
    history = [{'title': t.get('title', tid), 'id': tid, 'kind': t.get('execution_scope'), 'state': t.get('state'), 'feature': t.get('feature_id')} for tid, t in tasks.items()]
    overall = '전체 완료 여부 확인 불가'
    if scope:
        if scope.get('outcome', {}).get('status') == 'BLOCKED' or any(t['blocked'] for t in views):
            overall = '차단 · 필수 조건 미충족'
        elif any(t['verdict'] == 'FAIL' for t in views):
            overall = '필수 검증 실패'
        elif stages and all(s['status'] == '등록된 필수 작업 검토 통과' for s in stages) and not gaps:
            overall = '등록된 실행 범위의 필수 검토 통과'
    from harness.stage_readiness import assess
    readiness=[{'feature_id':fid,**assess(root,state,fid)} for fid in sorted({tasks[v['id']]['feature_id'] for v in views})]
    result = {'readiness':readiness, 'project': registry.get('project_name', root.name), 'choices': sorted(choices, key=lambda x: not x['active']),
            'project_goals':list(dict.fromkeys(s['goal'] for s in registry.get('scopes',[]) if s.get('goal'))), 'selected': scope_id if scope else None, 'scope': {k: v for k, v in (scope or {}).items() if k not in {'tasks', 'agent_run_ids'}},
            'tasks': views, 'stages': stages if scope else [], 'history': history, 'overall': overall,
            'baselines': [reference(root, r) for r in (scope or {}).get('approved_baselines', [])],
            'artifacts': [{**reference(root, r), 'kind': r.get('kind'), 'featured': r.get('featured', True), 'interactive_preview': r.get('interactive_preview', False), 'derived_from': r.get('derived_from', []), 'approval': r.get('approval', '승인 여부 미확인')} for r in (scope or {}).get('artifacts', [])],
            'comparisons': [{**c, 'images': [reference(root, a) for a in c.get('images', [])]} for c in (scope or {}).get('comparisons', [])],
            'related_history': [{'title': tasks.get(r['task_id'], {}).get('title', '원본 작업 누락'), 'state': tasks.get(r['task_id'], {}).get('state', UNKNOWN), **r} for r in (scope or {}).get('related_history', [])],
            'versions': versions, 'harness_identities':[o['identity'] for o in version_options if o['key'] in selected_version_keys and o['identity']], 'agent_versions':version_options, 'agent_version':agent_version, 'filtered_subset':filtered, 'project_filter':project_id, 'gaps': gaps, 'invalid_log_lines': bad,
            'last_activity': max((e['timestamp'] for e in scoped_events if e.get('timestamp')), default=None),
            'last_collection': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat() if path.exists() else None,
            'refreshed_at': stamp(), 'usage': apply_recorded_labels(enrich_usage(root, usage_view(events, scope or {}, views, registry.get('pricing', {}), source_tasks, proof_events), scope or {}),tasks,proof_events,root,state)}
    result['rework_links']=[{'task_id':e.get('task_id'),'from_task_id':e.get('observed',{}).get('from_task_id')} for e in events if e.get('event_type')=='stage_rework_created']
    result['execution_plan']=state.get('execution_plans',{}).get((scope or {}).get('recorded_run_id'))
    visible_ids={v['id'] for v in views}
    result['required_questions']=[{
        'id':q['id'], 'question':q['question'], 'status':q['status'],
        'human_review_required':q.get('human_review_required',False),
        'options':q.get('options',[]),
        'affected_task_ids':[tid for tid in q.get('propagated_task_ids',[]) if tid in visible_ids]
    } for q in state.get('required_questions',{}).values()
       if visible_ids.intersection(q.get('propagated_task_ids',[]))]
    from harness.project_progress import summarize
    decision_scopes=([scope] if scope else [s for s in scopes if set(s.get('tasks',{})) & set(tasks)]) if filtered else scopes
    result['project_progress']=summarize(root,tasks,events,decision_scopes,(scope or {}).get('project_id'),state.get('execution_plans',{}))
    from harness.agent_flow import project as agent_flow
    result['agent_flow']=agent_flow(root,tasks,events,state.get('issues',[]),result['project_progress'],list((scope or {}).get('tasks',{})),state.get('execution_plans',{}),(scope or {}).get('provenance'))
    result['last_activity']=max((g['last_activity'] for g in result['agent_flow']['groups'] if g.get('last_activity')),default=result['last_activity'])
    result=filter_result(result,events,start,end)
    from harness.human_progress import project, message
    result['human_progress']=project(result,tasks,root)
    if filtered:
        result['overall']='선택 조건에 해당하는 일부 기록 · 전체 완료 여부 확인 불가'
        result['project_progress']['scope']='선택 실행·기간·Agent 버전의 교집합'
        result['project_progress']['note']='선택한 기록의 일부 보기입니다. 프로젝트 전체 완료를 뜻하지 않습니다.'
        result['usage']['universe']['scope']='선택 실행·프로젝트·기간·Agent 버전에 해당하는 수집 기록'
        result['usage']['universe']['note']='선택 조건의 분모입니다. 수집 누락과 프로젝트 전체 사용량은 미확인입니다.'
        result['readiness']=[]
        result['related_history']=[]
        result['execution_plan']=None
        for stage in result['stages']:
            stage.update(status='선택 기록 · 단계 전체 완료 여부 확인 불가',completion_evidence_missing=True)
        result['human_progress']['filtered_subset']=True
    result['human_progress']['agent_message']=message(result['human_progress'])
    return result


def create_server(root, port):
    root = Path(root).resolve(); assets = Path(__file__).with_name('dashboard_assets')
    events = NativeEvents(root)
    class Handler(BaseHTTPRequestHandler):
        def event_stream(self):
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host', ''):
                self.send_error(403); return
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; object-src 'none'; base-uri 'none'")
            self.end_headers()
            revision = events.revision
            def send(kind):
                payload = json.dumps({'revision': revision, 'status': events.status})
                self.wfile.write(('id: ' + revision + '\nevent: ' + kind + '\ndata: ' + payload + '\n\n').encode())
                self.wfile.flush()
            try:
                send('connected')
                heartbeat = time.monotonic()
                while not events.closed:
                    if events.status != 'native':
                        send('manual'); return
                    current = events.wait(revision)
                    # Check only the network peer, never read state for a heartbeat.
                    if select.select([self.connection], [], [], 0)[0] and not self.connection.recv(1, socket.MSG_PEEK):
                        return
                    if current != revision:
                        revision = current
                        send('changed')
                    elif time.monotonic() - heartbeat >= 10:
                        self.wfile.write(b': keepalive\n\n'); self.wfile.flush()
                        heartbeat = time.monotonic()
            except (OSError, ValueError):
                return
        def do_GET(self):
            if self.headers.get('Host', '').split(':')[0] not in {'127.0.0.1', 'localhost'}:
                self.send_error(403); return
            parsed = urlparse(self.path); query = parse_qs(parsed.query)
            if parsed.path == '/api/events':
                self.event_stream(); return
            interactive = False
            try:
                if parsed.path == '/api/snapshot':
                    body = json.dumps(snapshot(root, query.get('scope', [None])[0],query.get('from',[None])[0],query.get('to',[None])[0],query.get('agent_version',[None])[0],query.get('project',[None])[0]), ensure_ascii=False).encode(); mime = 'application/json'
                elif parsed.path == '/evidence':
                    tasks = load(root / '.harness/tasks/tasks.yaml', {}).get('tasks', {})
                    registry = load(root / '.harness/dashboard-scopes.json', {})
                    tid = query.get('task', [''])[0]
                    from harness.context import identify
                    if not any(tid in s.get('tasks', {}) for s in registry.get('scopes', [])) and (tasks.get(tid,{}).get('project_id')!=identify(root)['project_id'] or not tasks.get(tid,{}).get('reviews')):
                        raise ValueError('unregistered task')
                    review = next(r for r in tasks[tid].get('reviews', []) if r['agent_run_id'] == query.get('review', [''])[0])
                    result = next(r for r in review['results'] if r['criterion_id'] == query.get('criterion', [''])[0])
                    a = result.get('evidence') or {}
                    if not artifact_valid(root, a):
                        raise ValueError('evidence integrity unavailable')
                    try:
                        raw = json.loads((root / a['snapshot']).read_text())
                    except json.JSONDecodeError:
                        raw = {}
                    raw = raw if isinstance(raw, dict) else {}
                    # Never expose the raw snapshot, response bodies, commands, env or session data.
                    summary = {k: raw[k] for k in ('result', 'scope', 'execution_mode', 'product_compliance', 'overall_v1') if isinstance(raw.get(k), (str, bool, int))}
                    summary['remaining'] = [v for v in raw.get('remaining', []) if isinstance(v, str)] if 'remaining' in raw else None
                    observed = raw.get('observations') or {}
                    hashes = raw.get('report_hashes') or {}
                    summary['reported_test_results'],report_files,scope_notes=observation_summary(root,raw)
                    summary['reported_scope']=scope_notes
                    summary['report_file_integrity'] = report_files
                    summary['tested_outputs'] = [{'path': o.get('path'), 'sha256': o.get('sha256')} for o in result.get('tested_outputs', review.get('outputs', []))]
                    report = {'task': tasks[tid]['title'], 'historical_result': result['result'], 'criterion': result['criterion_id'], 'evidence_sha256': a['snapshot_sha256'], 'observation_format': type(observed).__name__, 'report_hash_format': type(hashes).__name__, 'current_applicability': '별도 재검증 필요. 당시 결과가 현재 목표 준수 PASS는 아닙니다.', 'scope_summary': summary}
                    body = ('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>당시 검토 근거</title><style>body{font:16px system-ui;max-width:1000px;margin:32px auto;padding:16px;color:#182b3c}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f8;padding:16px}li,p{line-height:1.7}summary{cursor:pointer}</style><h1>' + html.escape(tasks[tid]['title']) + '</h1><h2>당시 검토: ' + html.escape(result['result']) + '</h2><p>이것은 당시 범위의 검토 기록입니다. 현재 목표 준수 PASS나 제품 전체 완료가 아닙니다. 원본은 보존하며 세션 로그·메모 본문은 제공하지 않습니다.</p><h3>당시 기록이 보고한 시험 결과</h3><pre>' + html.escape(json.dumps(summary['reported_test_results'], ensure_ascii=False, indent=2) if summary['reported_test_results'] else '숫자형 시험 결과는 이 근거에 등록되지 않았습니다. 연결된 작업별 검증 문서를 확인하세요.') + '</pre><h3>검증 범위와 미검증 항목</h3><ul>' + ''.join('<li>'+html.escape(s['kind']+' · '+s['text'])+'</li>' for s in scope_notes) + '</ul><h3>시험 리포트 원본의 현재 상태</h3>' + ('<ul>' + ''.join('<li>'+html.escape(r['path']+' · '+r['state'])+'</li>' for r in report_files) + '</ul>' if report_files else '<p>이 근거에 구조화된 리포트 파일 해시 연결이 없습니다. 작업별 검증 문서·실행 증거를 확인하세요. 검토 스냅샷만으로 자동 시험 성공을 판정하지 않습니다.</p>') + '<details><summary>검토 ID·제출 파일·해시 상세</summary><pre>' + html.escape(json.dumps(report, ensure_ascii=False, indent=2)) + '</pre></details></html>').encode(); mime = 'text/html'
                elif parsed.path == '/document':
                    name = query.get('path', [''])[0]
                    registry = load(root / '.harness/dashboard-scopes.json', {})
                    allowed = registered_files(registry)
                    taskstate=load(root/'.harness/tasks/tasks.yaml',{}).get('tasks',{})
                    for task in taskstate.values():
                        for ref in task.get('outputs',[])+task.get('inputs',[]):
                            try:safe_file(root,ref.get('path',''));allowed.add(ref['path'])
                            except (ValueError,OSError):pass
                    if name not in allowed:
                        raise ValueError('unregistered document')
                    p = safe_file(root, name); body = p.read_bytes()
                    interactive = any(r.get('path') == name and r.get('interactive_preview') is True and r.get('sha256') == sha(p) for s in registry.get('scopes', []) for r in s.get('artifacts', []))
                    mime = {'.html': 'text/html', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.pdf': 'application/pdf'}.get(p.suffix.lower(), 'text/plain; charset=utf-8')
                    if p.suffix in {'.md', '.json'}:
                        body = document_html(root, name, allowed); mime = 'text/html'
                elif parsed.path in ('/', '/app.js', '/record-details.js', '/usage.js', '/style.css'):
                    name = {'/': 'index.html', '/app.js': 'app.js', '/record-details.js': 'record-details.js', '/usage.js':'usage.js', '/style.css': 'style.css'}[parsed.path]
                    body = (assets / name).read_bytes(); mime = {'index.html': 'text/html', 'app.js': 'text/javascript', 'record-details.js': 'text/javascript', 'usage.js':'text/javascript', 'style.css': 'text/css'}[name]
                else:
                    self.send_error(404); return
                self.send_response(200); self.send_header('Content-Type', mime); self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; form-action 'none'" if interactive else "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:" if parsed.path in {'/document', '/evidence'} else "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-src 'self'; object-src 'none'; base-uri 'none'")
                self.end_headers(); self.wfile.write(body)
            except (ValueError, OSError, KeyError, TypeError, StopIteration, json.JSONDecodeError):
                self.send_error(422, 'Input missing, invalid or not allowed; source records unchanged')
        def log_message(self, *_):
            pass
    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def server_close(self):
            events.close()
            super().server_close()

        def shutdown(self):
            events.close()
            super().shutdown()

    try:
        server = Server(('127.0.0.1', port), Handler)
    except BaseException:
        events.close()
        raise
    server.events = events
    return server


def serve(root, port):
    server = create_server(root, port)
    print(f'http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8780)
    args = parser.parse_args()
    serve(args.root, args.port)
