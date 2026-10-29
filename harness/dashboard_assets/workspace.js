/* Three views, one canonical response projection. Approved card/flow layout reused. */
(()=>{
 const $=s=>document.querySelector(s),esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const amount=x=>x==null?'사용량 기록 없음':Number(x).toLocaleString('ko-KR')+' 토큰';
 const date=x=>x?new Date(x).toLocaleString('ko-KR'):'—';
 const states={TODO:'대기',READY:'준비됨',IN_PROGRESS:'진행 중',IN_REVIEW:'확인 중',REWORK:'보완 중',BLOCKED:'막힘',DONE:'완료'};
 const roles={orchestrator:'오케스트레이터',planning:'기획',design:'디자인',development:'개발',verification:'QA'};
 const verdicts={PASS:'검증 통과',FAIL:'검증 실패',NOT_RUN:'미검증',RECHECK_REQUIRED:'다시 확인 필요'};
 let saved={};try{saved=JSON.parse(localStorage.getItem('dashboard-menus-v1')||'{}');}catch{}
 let s={menu:'main',project:'',request:'',task:'',node:'',start:'',end:'',children:false,...saved},data,projects=[],busy=false,pending=false,signature='',scopeKey='',openMemory=new Map(),scrollMemory=new Map();
 const persist=()=>localStorage.setItem('dashboard-menus-v1',JSON.stringify(s));
 const task=id=>data.tasks.find(t=>t.task_id===id);
 const req=()=>data.requests.find(r=>r.id===s.request);
 const sum=rows=>rows.length?rows.reduce((n,r)=>n+r.tokens,0):null;
 function graph(groups,title){
  if(!groups.length)return '<p class=muted>사용량 기록 없음</p>';
  const width=Math.max(600,groups.length*130),max=Math.max(1,...groups.map(r=>r.tokens||0));
  return `<div class=chart><svg viewBox="0 0 ${width} 235" role=img aria-label="${esc(title)}"><line x1=30 y1=170 x2="${width-10}" y2=170 stroke="#cfdddd"/>${groups.map((r,i)=>{const x=50+(width-60)*(i+.5)/groups.length,h=r.tokens==null?0:r.tokens/max*125,label=r.label||r.code;return `<rect x="${x-23}" y="${170-h}" width=46 height="${h}" rx=3 fill="#5c9487"><title>${esc(label)} · ${esc(amount(r.tokens))}</title></rect><text x="${x}" y="${Math.max(20,160-h)}" text-anchor=middle font-size=11 fill="#496b69">${r.tokens==null?'기록 없음':r.tokens.toLocaleString('ko-KR')}</text>${[label.slice(0,14),label.slice(14,28)].filter(Boolean).map((l,j)=>`<text x="${x}" y="${193+j*16}" text-anchor=middle font-size=11 fill="#56717a">${esc(l)}</text>`).join('')}`;}).join('')}</svg></div>`;
 }
 function rowsFor(ids=null){return data.usage.rows.filter(r=>(ids===null||ids.includes(r.task_id))&&(s.menu!=='tokens'||!s.start||(r.occurred_at||'').slice(0,10)>=s.start)&&(s.menu!=='tokens'||!s.end||(r.occurred_at||'').slice(0,10)<=s.end));}
 function selectedIds(){
  let ids=s.task?[s.task]:s.request?(req()?.task_ids||[]):null;
  if(s.task&&s.children){let set=new Set(ids),before=-1;while(before!==set.size){before=set.size;data.usage.rows.forEach(r=>{if(set.has(r.parent_task_id))set.add(r.task_id);});}ids=[...set];}
  return ids;
 }
 function bars(rows,field,labels){const m=new Map();rows.forEach(r=>{const code=r[field]||'unknown';m.set(code,(m.get(code)||0)+r.tokens);});return [...m].map(([code,tokens])=>({code,label:labels[code]||code,tokens}));}
 function scopeNote(){
  const b=data.usage.target_scope;if(!b)return "";
  return `<p class=muted>전체 기록 기준 대상 ${esc(b.selected_project_id)} · 대상 작업 ${esc(amount(b.selected_target.tokens))} (제품 작업 ${esc(amount(b.product_work_tokens))}) · 다른 대상 ${esc(amount(b.other_targets.tokens))} · 대상 미확인 ${esc(amount(b.unknown_target.tokens))}</p><p class=muted>저장소 전체 ${esc(amount(b.repository_known_tokens))} · 모든 기간·모든 대상·대상 미확인 포함, 이 저장소 안의 중복 응답 제외. 위 선택 범위의 사용량과 구분합니다.</p>`;
 }
 function tokenSummary(ids,current=false){
  const rows=rowsFor(s.task?selectedIds():ids);
  const streaming=rows.length>0&&rows.every(r=>data.incremental_usage_execution_ids.includes(r.execution_id));const mixed=!streaming&&rows.some(r=>data.incremental_usage_execution_ids.includes(r.execution_id));
  return `<section class="panel compact-chart"><h2>${s.task?'선택 작업의 토큰':'선택 요청의 토큰'}</h2><p class=metric>${esc(amount(sum(rows)))}</p><p class=muted>${!rows.length&&current?'수집 연결 없음':streaming?'응답별 반영':mixed?'응답별·종료 후 반영':'종료 후 반영'} · 마지막 수집 ${esc(date(rows.length?rows.map(r=>r.collected_at).sort().at(-1):null))}</p><button class=action data-go=tokens>상세 내역</button>${scopeNote()}</section>`;
 }
 function relatedTasks(){
  let ids=s.task?[s.task]:s.request?req()?.task_ids||[]:[];
  const set=new Set(ids);let size=-1;
  while(size!==set.size){size=set.size;data.usage.rows.forEach(r=>{if(set.has(r.task_id)&&r.parent_task_id)set.add(r.parent_task_id);if(set.has(r.parent_task_id))set.add(r.task_id);});data.assigned_children.forEach(a=>{if(set.has(a.child_task_id))set.add(a.parent_task_id);if(set.has(a.parent_task_id))set.add(a.child_task_id);});}
  // QA targets are explicit recorded relationships, not workflow-order guesses.
  data.tasks.forEach(t=>{if(set.has(t.qa_config?.target_task_id)||set.has(t.qa_config?.repair_task_id))set.add(t.task_id);});
  data.issues.forEach(i=>{if(set.has(i.qa_task_id)||set.has(i.task_id)){if(i.resolution?.qa_task_id)set.add(i.resolution.qa_task_id);(i.history||[]).forEach(h=>{if(h.qa_task_id)set.add(h.qa_task_id);});}});
  return data.tasks.filter(t=>set.has(t.task_id));
 }
 let renderedNodes=[];
 function flow(){
  const linked=relatedTasks(),node=(role,list)=>{
   const active=list.filter(t=>data.active_task_ids.includes(t.task_id)),t=active[0]||list.at(-1);
   return {key:role,label:roles[role]||data.usage.taxonomy.development[role]||role,tasks:list,t,
           status:t?(verdicts[t.view.verdict]==='다시 확인 필요'?'다시 확인 필요':states[t.state]||'기록 없음'):'활동 기록 없음',active:list.some(t=>data.observed_active_task_ids.includes(t.task_id))};
  };
  const roots=linked.filter(t=>!data.assigned_children.some(a=>a.child_task_id===t.task_id)&&!data.usage.rows.some(r=>r.task_id===t.task_id&&r.parent_task_id));
  renderedNodes=Object.keys(roles).map(r=>node(r,roots.filter(t=>t.role===r)));
  const children=linked.filter(t=>data.assigned_children.some(a=>a.child_task_id===t.task_id)||data.usage.rows.some(r=>r.task_id===t.task_id&&r.parent_task_id));
  const byOwner=new Map();children.forEach(t=>{const owner=data.assigned_children.find(a=>a.child_task_id===t.task_id)?.development_owner||data.usage.rows.find(r=>r.task_id===t.task_id)?.development_owner||'unknown';if(!byOwner.has(owner))byOwner.set(owner,[]);byOwner.get(owner).push(t);});
  byOwner.forEach((ts,k)=>renderedNodes.push(node(k,ts)));
  function card(n){return `<button class="node ${n.active?'active':''} ${n.t?.view.verdict==='PASS'?'done':''} ${s.node===n.key?'selected':''}" data-node="${esc(n.key)}"><span class=role>${esc(n.label)}</span><span class=state>${n.active?'● ':''}${esc(n.status)}</span><span class=task title="${esc(n.t?.title)}">${esc(n.t?.title||'—')}</span></button>`;}
  return `<section class=panel><h2>${esc(s.task?task(s.task)?.title:req()?.summary||'선택한 기록')}</h2><p class=subtitle>${s.request?'선택한 요청에 연결된 작업':'선택 작업과 확인된 관계'} · ${data.active_task_ids.some(id=>linked.some(t=>t.task_id===id))?'진행 기록':'과거 기록'}</p><div class=canvas><svg class=links aria-label="조율 관계와 기록된 보완 연결"></svg><div class=orch>${card(renderedNodes[0])}</div><div class=roles>${renderedNodes.slice(1,5).map(n=>`<div>${card(n)}${n.key==='development'?'<div class=children>'+renderedNodes.slice(5).map(card).join('')+'</div>':''}</div>`).join('')}</div></div><div id=node-detail>${s.node?nodeDetail(renderedNodes.find(n=>n.key===s.node)):''}</div></section>`;
 }
 function nodeDetail(n){
  if(!n)return '';const t=n.t;if(!t)return `<div class=detail><h2>${esc(n.label)}</h2><p>활동 기록 없음</p></div>`;
  const issues=data.issues.filter(i=>n.tasks.some(t=>[i.task_id,i.repair_task_id,i.qa_task_id].includes(t.task_id))&&i.status!=='RESOLVED');
  const history=n.tasks.flatMap(t=>t.executions.filter(e=>e.role===(roles[n.key]?n.key:'development')).map(e=>({t,e}))).sort((a,b)=>(b.e.started_at||'').localeCompare(a.e.started_at||''));
  const rows=data.usage.rows;
  return `<div class=detail><div class=detail-title><h2>${esc(n.label)}</h2><button data-close-node>닫기 ×</button></div><h3>하는 일</h3><p>${esc(t.title)} · ${esc(n.status)}</p><h3>체크리스트</h3>${(t.view.criteria||t.criteria||[]).map(c=>`<div class=check-row><span>${esc(verdicts[c.current_result||c.result]||'미검증')}</span><span>${esc(c.description||c.id)}</span></div>`).join('')||'<p class=muted>연결된 체크리스트 없음</p>'}<h3>문제와 다음 행동</h3>${issues.map(i=>`<p class=warning>${esc(i.observed)}</p>`).join('')}${t.blocked_reason?`<p class=warning>${esc(t.blocked_reason)}</p>`:''}<p>${esc(t.view.next&&!['연결 필요','handoff'].includes(t.view.next)?t.view.next:'다음 행동 미등록')}</p><details data-fold="history-${esc(n.key)}"><summary>${esc(n.label)} 실행 이력 (${history.length}건)</summary>${history.map(({t,e})=>{const r=rows.find(r=>r.execution_id===e.agent_run_id);return `<article class=history-row><strong>${esc(t.title)}</strong><p>호출 시각: ${esc(date(e.started_at))}</p><p>호출 이유: ${esc(t.title)}</p><p>수행: ${esc(r?data.usage.taxonomy.actors[r.actor]:e.execution_mode==='local_check'?'로컬 검사 · 별도 모델 실행 없음':'실행 주체 확인 불가')}</p><p>결과: ${esc(e.ended_at?'실행 종료':'종료 기록 없음')}${e.kind==='review'?' · 검토 실행':''}</p>${r&&r.repetition!=='initial'&&r.repetition!=='unknown'?`<p>${esc(data.usage.taxonomy.repetitions[r.repetition])} · ${esc(r.classification?.basis||'원인 근거는 아래 상세 참조')}</p>`:''}${t.delegation_reason?`<p>보완 이유: ${esc(t.delegation_reason)}</p>`:''}</article>`;}).join('')}</details><details data-source-task="${esc(t.task_id)}" data-fold="evidence-${esc(n.key)}"><summary>결과 및 근거 펼쳐보기</summary><p>${esc(verdicts[t.view.verdict]||'검증 기록 없음')}</p>${(t.view.reasons||[]).map(r=>`<p>${esc(r)}</p>`).join('')}${(t.outputs||[]).map((o,i)=>`<p><a href="/api/artifact?${esc(new URLSearchParams({project:s.project,task:t.task_id,index:i}))}">${esc(o.path)} · 기록된 산출물 조회</a></p>`).join('')}<pre>${esc(JSON.stringify({criteria:t.view.criteria,outputs:t.outputs,reviews:t.reviews,history:t.view.historical_reviews,executions:t.executions},null,2))}</pre></details></div>`;
 }
 function draw(){
  const c=$('.canvas');if(!c)return;const box=c.getBoundingClientRect(),svg=c.querySelector('svg'),rect=k=>c.querySelector(`[data-node="${CSS.escape(k)}"]`)?.getBoundingClientRect(),o=rect('orchestrator');if(!o)return;
  svg.setAttribute('viewBox',`0 0 ${box.width} ${box.height}`);let paths=['planning','design','development','verification'].map(k=>{const r=rect(k);return `<path class=relation d="M${o.left+o.width/2-box.left} ${o.bottom-box.top} V${o.bottom-box.top+18} H${r.left+r.width/2-box.left} V${r.top-box.top}"><title>조율 관계</title></path>`;});
  // Route returns through a dedicated lane below every card, including children.
  const qa=rect("verification"),returns=new Map();
  data.issues.filter(i=>i.status!=="RESOLVED").forEach(i=>{
   const target=renderedNodes.find(n=>n.tasks.some(t=>[i.repair_task_id,i.task_id].includes(t.task_id)));
   if(!target||target.key==="verification")return;
   const group=returns.get(target.key)||{target,issues:[]};group.issues.push(i);returns.set(target.key,group);
  });
  const bottom=Math.max(...renderedNodes.map(n=>rect(n.key)?.bottom||box.top))-box.top;
  c.style.paddingBottom=(returns.size?76+Math.max(0,returns.size-1)*40:20)+"px";
  const height=c.getBoundingClientRect().height;svg.setAttribute("viewBox",`0 0 ${box.width} ${height}`);
  [...returns.values()].forEach(({target,issues},index)=>{
   const r=rect(target.key);if(!r||!qa)return;
   const lane=bottom+38+index*40,startX=qa.left+qa.width/2-box.left,endX=r.right-box.left+8,gutter=endX+14,y=r.top+r.height/2-box.top;
   paths.push(`<path class="actual qa-return" d="M${startX} ${qa.bottom-box.top+8} V${lane} H${gutter} V${y} H${endX}" marker-end="url(#return-arrow)"><title>QA → ${esc(target.label)} · 보완 요청 ${issues.length}건</title></path><text class="edge-label" x="${(startX+gutter)/2}" y="${lane+21}" text-anchor="middle">QA → ${esc(target.label)} · 보완 요청 ${issues.length}건</text>`);
  });
  renderedNodes.forEach(from=>from.tasks.forEach(t=>(t.handoffs||[]).forEach(h=>{const to=renderedNodes.find(n=>n.tasks.some(t=>t.task_id===h.to_task_id));if(!to||to.key===from.key||!(from.active||to.active))return;const a=rect(from.key),b=rect(to.key);if(!a||!b)return;paths.push(`<path class=actual d="M${a.right-box.left} ${a.top+a.height/2-box.top} H${b.left-box.left}" marker-end="url(#return-arrow)"><title>기록된 작업 인계</title></path>`);})));
  svg.innerHTML='<defs><marker id=return-arrow viewBox="0 0 10 10" refX=9 refY=5 markerWidth=6 markerHeight=6 orient=auto><path d="M0 0L10 5L0 10Z" fill="#28736b"/></marker></defs>'+paths.join('');
 }
 function requestOptions(){return '<option value="">요청 전체</option>'+data.requests.filter(r=>s.menu!=='main'||r.active).map(r=>`<option value="${esc(r.id)}" ${s.request===r.id?'selected':''}>${esc(r.summary)}</option>`).join('');}
 function taskOptions(ids=null){return '<option value="">작업 전체 · 미연결 포함</option>'+data.tasks.filter(t=>!ids||ids.includes(t.task_id)).map(t=>`<option value="${esc(t.task_id)}" ${s.task===t.task_id?'selected':''}>${esc(t.title)} · ${esc(roles[t.role]||'담당 기록 없음')}${data.tasks.filter(x=>x.title===t.title).length>1?' · 항목 '+(data.tasks.filter(x=>x.title===t.title).indexOf(t)+1)+' · '+esc(date(t.executions[0]?.started_at)):''}</option>`).join('');}
 function filters(){return `<div class=filters><label>요청 <select id=request-select>${requestOptions()}</select></label><label>작업 <select id=task-select>${taskOptions(s.request?req()?.task_ids:null)}</select></label></div>`;}
 function activities(ids){return `<section class=recent><h2>최근 주요 활동</h2>${data.activity.filter(a=>ids.includes(a.task_id)).slice(0,5).map(a=>`<div class=activity-row><time>${esc(date(a.at))}</time><span>${esc(a.text)}</span></div>`).join('')||'<p class=muted>주요 활동 기록 없음</p>'}</section>`;}
 function main(){
  const current=data.requests.filter(r=>r.active);const r=current.find(r=>r.id===s.request)||current[0];
  if(!r)return `<section class=panel><h2>현재 진행 중인 요청 없음</h2><p>현재 실행 중인 모델 호출이 없습니다. 요청 전체의 완료를 뜻하지 않습니다.</p><p>과거 요청의 작업 상태와 남은 문제는 작업 이력에서 확인할 수 있습니다.</p><button class=action data-go=history>작업 이력 보기</button>${data.unlinked_active_task_ids.length?`<p class=warning>요청에 연결되지 않은 진행 기록 ${data.unlinked_active_task_ids.length}개가 있습니다.</p>`:''}</section>`;
  s.request=r.id;if(s.task&&!r.task_ids.includes(s.task))s.task='';
  const ids=s.task?[s.task]:r.task_ids,active=data.usage.active_executions.filter(a=>ids.includes(a.task_id));
  return `${filters()}${overview(r,ids)}${problems(r.task_ids)}<div class="records workflow">${flow()}</div>${tokenSummary(ids,true)}<section class="panel evidence"><h2>전체 기록과 근거</h2><details data-fold=task-list><summary>연결 작업 전체 (${r.task_ids.length}개)</summary>${r.task_ids.map(id=>`<button class=other-row data-current-task="${esc(id)}"><span>${esc(task(id)?.title)}</span><span>${esc(states[task(id)?.state]||"기록 없음")}</span></button>`).join("")}</details><details data-fold=original><summary>원문 요청 펼쳐보기</summary><p>${esc(date(r.at))}</p><pre>${esc(r.text)}</pre></details></section>`;
 }
 function problems(ids){
  const tasks=data.tasks.filter(t=>ids.includes(t.task_id)),lines=[];
  const add=(t,text)=>{if(text)lines.push({id:t?.task_id||"",title:t?.title||"연결 작업 미확인",text:typeof text==="string"?text:JSON.stringify(text)});};
  data.issues.filter(i=>i.status!=="RESOLVED"&&[i.task_id,i.repair_task_id,i.qa_task_id].some(id=>ids.includes(id))).forEach(i=>add(task(i.task_id)||task(i.qa_task_id)||task(i.repair_task_id),i.observed));
  tasks.forEach(t=>[t.blocked_reason,...(Array.isArray(t.view.blocked)?t.view.blocked:t.view.blocked?[t.view.blocked]:[]),...(t.view.verdict==="RECHECK_REQUIRED"?["다시 검증해야 합니다."]:[])].forEach(text=>add(t,text)));
  const unique=[...new Map(lines.map(l=>[JSON.stringify([l.id,l.text]),l])).values()];
  return unique.length?`<section class="panel problem-summary"><h2>확인할 사항 ${unique.length}건</h2><p>${esc([...new Set(unique.map(l=>l.title))].join(" · "))}</p><details data-fold=problems><summary>문제 상세와 대상 작업 확인</summary><p class=muted>선택 작업 외에 초기·보완 작업의 미해결 기록도 포함합니다. 각 항목의 대상 작업을 확인하세요.</p>${unique.map(l=>`<div class=warning><strong>${esc(l.title)}${l.id?" · "+esc(l.id):""}</strong><p>${esc(l.text)}</p></div>`).join("")}</details></section>`:"";
 }
 function overview(r,ids){
  const last=data.activity.find(a=>ids.includes(a.task_id)),active=data.usage.active_executions.filter(a=>ids.includes(a.task_id));
  return `<section class="panel overview"><div><h2>${esc(r?.summary||task(s.task)?.title||"선택 작업")}</h2><p class=status-line>${esc(r?.status||states[task(s.task)?.state]||"기록 있음")} · ${active.length?"실행 중인 모델 호출 "+active.length+"개":"실행 중인 모델 호출 없음"}</p><p class=muted>작업 상태에는 초기·보완 이력이 포함됩니다. 모델 실행 종료는 요청 전체 완료와 다릅니다.</p></div><div class=latest><h3>마지막 주요 활동</h3>${last?`<p>${esc(last.text)}</p><p class=muted>${esc(date(last.at))}</p>`:"<p class=muted>활동 기록 없음</p>"}<details data-fold=recent><summary>최근 활동 더 보기</summary>${activities(ids)}</details></div></section>`;
 }
 function history(){
  const r=req(),linked=s.task?data.requests.filter(x=>x.task_ids.includes(s.task)):[],ids=r?r.task_ids:s.task?[s.task]:[];
  const list=`<section class=panel>${data.requests.map(r=>`<button class=request-row data-request="${esc(r.id)}"><strong>${esc(r.summary)}</strong><small>${esc(date(r.at))} · ${esc(r.status)} · ${esc(amount(r.tokens))}</small></button>`).join("")||"<p>연결된 사용자 요청 원문이 없습니다.</p>"}</section><details data-fold=unlinked-tasks><summary>원문 요청과 연결되지 않은 작업</summary>${data.tasks.filter(t=>!data.requests.some(r=>r.task_ids.includes(t.task_id))).map(t=>`<button class=request-row data-task="${esc(t.task_id)}">${esc(t.title)} · ${esc(states[t.state]||"기록 없음")}</button>`).join("")||"<p>해당 기록 없음</p>"}</details>`;
  return `<h2>작업 이력</h2>${filters()}${!r&&!s.task?list:`${overview(r,ids)}${!r?(linked.length?`<p class=muted>연결된 원문 요청: ${linked.map(x=>esc(x.summary)).join(" · ")}</p>`:"<p class=warning>사용자 원문과 연결되지 않은 작업 기록입니다.</p>"):""}${problems(ids)}<div class="records workflow">${flow()}</div>${tokenSummary(ids)}<section class="panel evidence"><h2>전체 기록과 근거</h2><details data-fold=task-list><summary>연결 작업 전체 (${ids.length}개)</summary><p class=muted>초기 작업과 보완 작업의 기록된 상태입니다.</p>${ids.map(id=>`<p>${esc(task(id)?.title)} · ${esc(states[task(id)?.state]||"기록 없음")}</p>`).join("")}</details>${r?`<details data-fold=original><summary>원문 요청과 첨부 자료</summary><p class=muted>${esc(date(r.at))}</p><pre>${esc(r.text)}</pre>${r.attachments.length?`<pre>${esc(JSON.stringify(r.attachments,null,2))}</pre>`:""}</details><details data-fold=request-links><summary>수정 지시와 범위 변경 근거</summary><pre>${esc(JSON.stringify(r.links,null,2))}</pre></details>`:""}<details data-fold=history-all><summary>주요 실행·보완·재검증 이력 전체</summary>${data.activity.filter(a=>ids.includes(a.task_id)).map(a=>`<p>${esc(date(a.at))} · ${esc(a.text)}</p><pre>${esc(JSON.stringify(a.detail,null,2))}</pre>`).join("")}</details><details data-fold=outputs><summary>산출물과 검증 결과</summary>${ids.map(id=>`<h3>${esc(task(id)?.title)}</h3><p>${esc(verdicts[task(id)?.view.verdict]||"검증 기록 없음")}</p><pre>${esc(JSON.stringify({outputs:task(id)?.outputs,reviews:task(id)?.reviews},null,2))}</pre>`).join("")}</details></section>`}`;
 }
 function tokens(){
  const ids=selectedIds(),rows=rowsFor(ids),u=data.usage;
  return `<h2>토큰 사용 내역</h2><div class=filters><label>시작일 <input id=date-start type=date value="${esc(s.start)}"></label><label>종료일 <input id=date-end type=date value="${esc(s.end)}"></label></div>${filters()}${scopeNote()}${s.task?`<label><input type=checkbox id=include-children ${s.children?'checked':''}> 하위 작업 포함</label>`:''}<section class=panel><p class=metric>${esc(amount(sum(rows)))}</p><p class=muted>${s.children?'하위 작업을 포함한 확인된 합계':'선택 범위의 직접 사용량'} · 마지막 수집 ${esc(date(rows.map(r=>r.collected_at).sort().at(-1)))}</p><p>작업 미연결 ${esc(rows.some(r=>!r.task_id)?amount(sum(rows.filter(r=>!r.task_id))):'해당 기록 없음')} · 역할 미분류 ${esc(rows.some(r=>r.role==='unknown')?amount(sum(rows.filter(r=>r.role==='unknown'))):'해당 기록 없음')}</p>${graph(data.tasks.filter(t=>!ids||ids.includes(t.task_id)).map(t=>({code:t.task_id,label:t.title+(data.tasks.filter(x=>x.title===t.title).length>1?' · 항목 '+(data.tasks.filter(x=>x.title===t.title).indexOf(t)+1)+' · '+date(t.executions[0]?.started_at):''),tokens:sum(rows.filter(r=>r.task_id===t.task_id))})).concat(rows.some(r=>!r.task_id)?[{label:'작업 미연결',tokens:sum(rows.filter(r=>!r.task_id))}]:[]),'작업별 사용량')}<h3>담당 역할별 사용량</h3>${graph(bars(rows,'role',u.taxonomy.roles),'담당 역할별 사용량')}<details data-fold=developers><summary>개발 코디네이터·담당별 내역</summary>${graph([...new Set([...u.configured_development_owners,...rows.filter(r=>r.role==='development').map(r=>r.development_owner)])].map(code=>({code,label:u.taxonomy.development[code]||code,tokens:sum(rows.filter(r=>r.role==='development'&&r.development_owner===code))})),'개발 담당별 사용량')}<p class=muted>기획·디자인·QA의 개발 담당은 해당 없음입니다.</p></details><h3>실행 목적별 사용량</h3>${graph(bars(rows,'purpose',u.taxonomy.purposes),'실행 목적별 사용량')}<details data-fold=repeats><summary>최초 수행·보완·재시도·재검증</summary>${graph(bars(rows,'repetition',u.taxonomy.repetitions),'수행 관계별 사용량')}</details><details data-fold=actors><summary>메인 직접 수행과 독립 실행</summary>${graph(bars(rows,'actor',u.taxonomy.actors),'실행 주체별 사용량')}</details><details data-fold=traces><summary>개별 실행과 원본 사용량 (${rows.length}응답)</summary><table class=token-trace><tr><th>작업</th><th>역할·목적</th><th>사용량·근거</th></tr>${rows.map(r=>`<tr><td><button class=action data-history-task="${esc(r.task_id||'')}">${esc(task(r.task_id)?.title||r.task_name)}</button><small>${esc(r.task_id)}</small></td><td>${esc(u.taxonomy.roles[r.role])}<br>${esc(u.taxonomy.purposes[r.purpose])}<br>${esc(u.taxonomy.repetitions[r.repetition])}</td><td>${esc(amount(r.tokens))}<details data-source-session="${esc(r.session_id)}" data-source-response="${esc(r.response_id)}" data-fold="row-${esc(r.session_id+'-'+r.response_id)}"><summary>실행과 분류 근거</summary><pre>${esc(JSON.stringify(r,null,2))}</pre></details></td></tr>`).join('')}</table></details><details data-fold=quality><summary>분류와 수집 범위</summary><p>역할별·목적별은 같은 사용량을 각각 나눈 결과입니다.</p><p>미수집을 0으로 처리하지 않습니다. 과거 기록에 없는 관계는 만들지 않았습니다.</p><pre>${esc(JSON.stringify({quality:u.quality,unquantified:u.unquantified_records,snapshots_not_added:u.snapshots_not_added,deduplicated:u.deduplicated_events},null,2))}</pre></details></section>`;
 }
 function render(){
  if(!data)return;
  const key=[s.menu,s.project,s.request,s.task].join('|'),same=key===scopeKey,scroll=window.scrollY,opened=same?[...document.querySelectorAll('details[open][data-fold]')].map(e=>e.dataset.fold):openMemory.get(key)||[];
  scopeKey=key;$('#content').innerHTML=s.menu==='main'?main():s.menu==='history'?history():tokens();
  document.querySelectorAll('nav button').forEach(b=>b.setAttribute('aria-current',b.dataset.menu===s.menu?'page':'false'));
  opened.forEach(k=>{const e=document.querySelector(`[data-fold="${CSS.escape(k)}"]`);if(e)e.open=true;});draw();const targetScroll=same?scroll:scrollMemory.get(key)||0;window.scrollTo(0,targetScroll);requestAnimationFrame(()=>{if(scopeKey===key)window.scrollTo(0,targetScroll);});persist();
 }
 function remember(keepScroll=false){openMemory.set(scopeKey,[...document.querySelectorAll('details[open][data-fold]')].map(e=>e.dataset.fold));if(!keepScroll||!scrollMemory.has(scopeKey))scrollMemory.set(scopeKey,window.scrollY);}
 function go(menu){remember(true);s.menu=menu;render();}
 document.addEventListener('click',e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.menu){go(b.dataset.menu);return;}if(b.dataset.go){go(b.dataset.go);return;}
  if(b.hasAttribute('data-node')){s.node=b.dataset.node;render();return;}
  if(b.hasAttribute('data-close-node')){s.node='';render();return;}
  if(b.dataset.request){remember();s.request=b.dataset.request;s.task='';s.node='';render();return;}
  if(b.dataset.currentTask){remember();s.task=b.dataset.currentTask;s.node='';render();return;}
  if(b.dataset.task){remember();s.task=b.dataset.task;s.request='';s.node='';render();return;}
  if(b.dataset.historyTask){s.task=b.dataset.historyTask;s.request='';go('history');}
 });
 document.addEventListener('change',e=>{
  const id=e.target.id;remember();
  if(id==='project-select'){s.project=e.target.value;$('#project-title').textContent=projects.find(p=>p.id===s.project)?.name||'작업 대시보드';s.request='';s.task='';s.node='';signature='';data=null;$('#content').textContent='기록을 불러오는 중입니다.';refresh();return;}
  if(id==='request-select'){s.request=e.target.value;s.task='';s.node='';}
  if(id==='task-select'){s.task=e.target.value;s.node='';}
  if(id==='date-start')s.start=e.target.value;if(id==='date-end')s.end=e.target.value;
  if(id==='include-children')s.children=e.target.checked;
  render();
 });
 document.addEventListener('toggle',async e=>{const d=e.target;if(!d.open||d.dataset.loaded||!d.matches('[data-source-task],[data-source-response]'))return;const q=new URLSearchParams({project:s.project});let route;if(d.dataset.sourceTask){route='task-record';q.set('task',d.dataset.sourceTask);}else{route='usage-response';q.set('session',d.dataset.sourceSession);q.set('response',d.dataset.sourceResponse);}try{const r=await fetch('/api/'+route+'?'+q);if(!r.ok)throw Error();d.querySelector('pre').textContent=JSON.stringify(await r.json(),null,2);d.dataset.loaded='1';}catch{d.querySelector('pre').textContent='원본 상세를 조회할 수 없습니다. 집계 결과는 유지됩니다.';}},true);
 const rememberPosition=()=>requestAnimationFrame(()=>requestAnimationFrame(()=>scrollMemory.set(scopeKey,window.scrollY)));
 document.addEventListener('click',e=>{if(e.target.closest('#content')&&!e.target.closest('[data-go]'))rememberPosition();});
 window.addEventListener('wheel',rememberPosition,{passive:true});
 window.addEventListener('touchend',rememberPosition,{passive:true});
 window.addEventListener('pointerup',e=>{if(!e.target.closest('nav,[data-go]'))rememberPosition();});
 window.addEventListener('keydown',e=>{if(['PageDown','PageUp','Home','End','ArrowDown','ArrowUp'].includes(e.key))rememberPosition();});
 window.addEventListener('resize',draw);
 async function refresh(){if(busy){pending=true;return;}busy=true;const key=s.project;try{
  const r=await fetch('/api/workspace?'+new URLSearchParams({project:key}),{cache:'no-store'});if(!r.ok)throw Error();const d=await r.json();if(key!==s.project)return;
  const sig=JSON.stringify(d);if(sig!==signature){signature=sig;data=d;$('#record-origin').textContent=d.origin==='SYNTHETIC_PREVIEW'?'KMP AGENT · 합성 검증 예시':'KMP AGENT · 실제 기록';render();}
  $('#error').textContent='';$('#refresh-time').textContent='화면 갱신 '+date(new Date())+' · 마지막 작업 활동 '+date(data.activity[0]?.at);
 }catch{$('#error').textContent='기록을 갱신하지 못했습니다. 이전 결과를 유지합니다.';}finally{busy=false;if(pending){pending=false;refresh();}}}
 fetch('/api/projects').then(r=>r.json()).then(p=>{projects=p;if(!p.some(p=>p.id===s.project))s.project=p[0].id;$('#project-select').innerHTML=p.map(p=>`<option value="${esc(p.id)}" ${p.id===s.project?'selected':''}>${esc(p.name)}</option>`).join('');$('#project-title').textContent=p.find(p=>p.id===s.project).name;refresh();}).catch(()=>$('#error').textContent='프로젝트 목록을 읽을 수 없습니다.');
 setInterval(()=>{if(!document.hidden&&!['SELECT','INPUT'].includes(document.activeElement?.tagName))refresh();},5000);
})();
