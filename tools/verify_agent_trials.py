"""Read-only proof extraction for completed isolated development/QA trials."""
import argparse,json,sys,hashlib
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harness.dashboard import snapshot


def load(root):
    state=json.loads((root/'.harness/tasks/tasks.yaml').read_text())
    events=[json.loads(l) for l in (root/'.harness/logs/events.jsonl').read_text().splitlines()]
    return state,events


def processes(events):
    starts={e['agent_run_id']:e for e in events if e['event_type']=='role_process' and e.get('observed',{}).get('process_state')=='role_process_started'}
    ends={e['agent_run_id']:e for e in events if e['event_type']=='role_process' and e.get('observed',{}).get('process_state')=='role_process_finished'}
    output=[]
    for aid,e in starts.items():
        assert aid in ends
        o=e['observed'];end=ends[aid]['observed']
        output.append({'agent_run_id':aid,'task_id':e['task_id'],'pid':o['pid'],'started_at':o['started_at'],'ended_at':end['ended_at'],'exit_code':end['returncode'],'independent_model_spawned':o['independent_model_spawned'],'thread_ids':end.get('thread_ids',[])})
    return output


def usage_proof(root,run_id):
    d=snapshot(root,'run:'+run_id);rows=d['usage']['rows']
    assert len({(r['session_id'],r['response_id']) for r in rows})==len(rows)
    for key in ('stage','role','task','hour','development_area'):
        groups={}
        for r in rows:groups.setdefault(r[key],[]).append(r)
        assert sum(sum(x['tokens'] for x in rs) for rs in groups.values())==d['usage']['totals']['tokens']
    return {'unique_responses':len(rows),'totals':d['usage']['totals'],'by_task':{tid:sum(r['tokens'] for r in rows if r['task_id']==tid) for tid in {r['task_id'] for r in rows}},'by_area':{area:sum(r['tokens'] for r in rows if r['development_area']==area) for area in {r['development_area'] for r in rows}},'parent_aggregation':'union of exact native response IDs; parent totals are not added again','cost':'UNKNOWN unless an explicit dated price scenario is configured','human_interventions':'UNKNOWN; generated worker instructions and QA returns are not human interventions'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--development-root',type=Path,required=True);p.add_argument('--qa-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    dev=args.development_root.resolve();qa=args.qa_root.resolve();ds,de=load(dev);qs,qe=load(qa)
    dt=json.loads((dev/'.harness/development-trial.json').read_text());qt=json.loads((qa/'.harness/qa-trial.json').read_text())
    parent=ds['tasks']['PARENT'];assert parent['state']=='DONE';assert set(parent['child_task_ids'])=={'CHILD-KMP','CHILD-WEB','CHILD-SERVER'}
    assert all(ds['tasks'][tid]['state']=='DONE' for tid in parent['child_task_ids']);assert not any(t.get('development_area') in {'android','ios'} for t in ds['tasks'].values())
    dp=processes(de);assert len(dp)==3 and all(x['exit_code']==0 and x['independent_model_spawned'] and len(x['thread_ids'])==1 for x in dp)
    boundaries=[]
    for proc in dp:
        boundaries.extend([(proc['started_at'],1),(proc['ended_at'],-1)])
    concurrent=maximum=0
    for _,delta in sorted(boundaries):concurrent+=delta;maximum=max(maximum,concurrent)
    assert maximum==2
    admissions=ds['runtime_budgets'][dt['run_id']]['admissions'];assert len(admissions)==3 and all(a['released_at'] for a in admissions)
    qa_task=qs['tasks']['QA-PLANNING-R3'];attempts=qa_task['qa_config']['attempts'];assert len(attempts)==2 and attempts[0]['outcome']!='PASS' and attempts[1]['outcome']=='PASS'
    assert qs['tasks']['REPAIR']['state']=='DONE'
    issues=[i for i in qs['issues'] if i.get('qa_task_id')=='QA-PLANNING-R3'];assert issues and all(i['status']=='RESOLVED' and i.get('resolution') for i in issues)
    original=qa_task['qa_config']['original_requests'][0];assert hashlib.sha256((qa/original['path']).read_bytes()).hexdigest()==original['sha256']
    qp=processes(qe);assert len(qp)==4 and all(x['independent_model_spawned'] and x['exit_code']==0 for x in qp)
    # One first response was format-invalid; its process success is not a quality PASS.
    assert qs['tasks']['QA-PLANNING-R2']['qa_config']['attempts'][0]['outcome']=='BLOCKED'
    report={'at':datetime.now(timezone.utc).isoformat(),'status':'PASS','scope':'actual native processes on synthetic local fixtures; not platform/product acceptance',
      'development':{'root':str(dev),'run_id':dt['run_id'],'processes':dp,'maximum_observed_parallel_processes':maximum,'shared_slot_admissions':len(admissions),'area_reviews':'PASS','separate_integration':'PASS','feature_complete':False,'usage':usage_proof(dev,dt['run_id'])},
      'qa':{'root':str(qa),'run_id':qt['run_id'],'processes':qp,'first_format_failure_preserved':True,'actual_quality_flow':[a['outcome'] for a in attempts],'owner_repair_state':qs['tasks']['REPAIR']['state'],'original_request_unchanged':True,'resolved_findings':[{'id':i['id'],'classification':i['qa_finding']['kind'],'owner':i['owner'],'status':i['status'],'resolution':i['resolution']} for i in issues],'usage':usage_proof(qa,qt['run_id'])},
      'not_run':['Kotlin/KMP compilation','Android/iOS/native UI acceptance','real server/database product E2E','actual model design/implementation QA cases beyond planning fixture'],
      'source_basis':'native per-event commit/dirty metadata; current source hashes below are after-run observations, not retroactive execution baseline'}
    source=Path(__file__).resolve().parents[1];report['after_run_source_sha256']={str(f.relative_to(source)):hashlib.sha256(f.read_bytes()).hexdigest() for f in list((source/'harness').glob('*.py'))+list((source/'harness/dashboard_assets').glob('*.js'))}
    out=args.output;out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists():
        history=out.parent/'history';history.mkdir(exist_ok=True);(history/(hashlib.sha256(out.read_bytes()).hexdigest()+'.json')).write_bytes(out.read_bytes())
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k not in ('after_run_source_sha256','qa','development')},ensure_ascii=False));print('development',report['development']['usage']);print('qa',report['qa']['usage'])

if __name__=='__main__':main()
