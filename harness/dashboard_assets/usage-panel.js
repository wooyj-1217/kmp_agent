/* Usage is a projection over native facts. Flow and lower node details stay intact. */
(()=>{
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const amount=n=>n==null?'사용량 기록 없음':Number(n).toLocaleString('ko-KR')+' 토큰';
 const domain=p=>p?.work_domain==='agent_development_test'?'에이전트 개발·시험':p?.work_domain==='product_work'?'제품 작업':'기록 범위 미확인';
 const stamp=s=>s?new Date(s).toLocaleString('ko-KR'):'—';
 const colors={orchestrator:'#637c9a',planning:'#9a80b7',design:'#b28e64',development:'#3f8d7c',verification:'#4f83b7',improvement:'#818f75',unknown:'#a3aeb5'};
 let mode='current',task='',execution='',children=false,busy=false,pending=false,flow=null,last=null,signature='',context='';
 const panel=document.createElement('section');panel.className='token-panel';panel.id='token-usage-panel';
 document.querySelector('main .panel')?.before(panel);
 fetch('data.json').then(r=>r.json()).then(d=>flow=d).catch(()=>{});
 function chart(groups,title,colorField=false){
  if(!groups.length)return '<p class="token-empty">사용량 기록 없음</p>';
  const width=Math.max(640,groups.length*135),height=225,max=Math.max(1,...groups.map(g=>g.tokens||0));
  let s=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(title)}"><line x1="45" y1="170" x2="${width-12}" y2="170" stroke="#cddddd"/><text x="8" y="18" font-size="11" fill="#6b8188">토큰</text>`;
  groups.forEach((g,i)=>{
   const x=65+(width-90)*(i+.5)/groups.length,w=Math.min(60,(width-90)/groups.length*.5),h=g.tokens==null?0:g.tokens/max*125;
   if(g.segments){let y=170;g.segments.forEach(seg=>{const sh=seg.tokens/max*125;y-=sh;s+=`<rect x="${x-w/2}" y="${y}" width="${w}" height="${sh}" rx="1" fill="${colors[seg.code]||colors.unknown}"><title>${esc(seg.label)}: ${esc(amount(seg.tokens))}</title></rect>`;});}
   else if(g.tokens!=null)s+=`<rect x="${x-w/2}" y="${170-h}" width="${w}" height="${h}" rx="3" fill="${colorField?(colors[g.code]||colors.unknown):'#5b9486'}"/>`;
   s+=`<text x="${x}" y="${g.tokens==null?153:Math.max(27,163-h)}" text-anchor="middle" font-size="11" fill="#42666a">${g.tokens==null?'기록 없음':Number(g.tokens).toLocaleString('ko-KR')}</text>`;
   const label=g.label||g.code;for(let j=0;j<label.length;j+=13)s+=`<text x="${x}" y="${191+Math.floor(j/13)*15}" text-anchor="middle" font-size="11" fill="#56717a">${esc(label.slice(j,j+13))}</text>`;
  });return '<div class="token-chart">'+s.replaceAll('기록 없음','기록 없음')+'</svg></div>';
 }
 function developerGroups(d){return [...new Set([...d.configured_development_owners,...d.development.map(g=>g.code)])].map(code=>d.development.find(g=>g.code===code)||{code,label:d.taxonomy.development[code],tokens:null});}
 function roleGroups(d){return ['orchestrator','planning','design','development','verification',...d.roles.map(g=>g.code)].filter((v,i,a)=>a.indexOf(v)===i).map(code=>d.roles.find(g=>g.code===code)||{code,label:d.taxonomy.roles[code]||code,tokens:null});}
 function tableRows(d){return d.rows.map(r=>`<tr><td>${esc(r.task_name)}<br><small>${esc(r.task_id||'작업 미연결')}</small></td><td>${esc(d.taxonomy.roles[r.role]||r.role)}<br>${esc(d.taxonomy.development[r.development_owner]||r.development_owner)}</td><td>${esc(d.taxonomy.purposes[r.purpose])}<br>${esc(d.taxonomy.repetitions[r.repetition])}</td><td>${esc(amount(r.tokens))}<details data-token-open="response-${esc(r.session_id+'-'+r.response_id)}"><summary>원본 응답·분류 근거</summary><p>${esc(domain(r.provenance))} · ${r.provenance?.code_state==='unknown'?'당시 코드 상태 미확인':r.provenance?.code_state==='fingerprinted'?'당시 코드 지문 기록됨':'당시 커밋 기록됨'}</p><pre>${esc(JSON.stringify(r,null,2))}</pre></details></td></tr>`).join('');}
 function meta(d){return `${mode==='current'&&!d.active_executions.length?'현재 수집 대상 없음':d.collection_label} · 마지막 수집 ${stamp(d.last_collected_at)} · 마지막 사용량 ${stamp(d.last_usage_at)}`;}
 function render(d){
  const key=[mode,task,execution,children].join('|'),same=context===key,scroll=[window.scrollX,window.scrollY],listScroll=panel.querySelector('.token-task-list')?.scrollTop||0;
  const opened=same?[...panel.querySelectorAll('details[open]')].map(e=>e.dataset.tokenOpen):[];context=key;
  const active=mode==='current',none=active&&!d.active_executions.length;
  panel.innerHTML=`<div class="token-tabs"><h2>토큰 사용량</h2><button data-token-mode="current" aria-pressed="${active}">실시간</button><button data-token-mode="tasks" aria-pressed="${!active}">작업별</button></div><div id="token-filter"></div><p class="token-value">${none?'진행 중인 작업 기록 없음':amount(d.known_tokens)}</p><p class="token-meta" id="token-meta">${esc(meta(d))}</p><div id="token-error" class="token-error" role="status"></div>${none?'<p class="token-empty">과거 사용량은 작업별 화면에서 확인할 수 있습니다.</p>':active?chart(d.time_bars.map(b=>({code:b.hour,label:b.hour.slice(5,10)+' '+b.hour.slice(11)+':00',tokens:b.tokens,segments:b.roles})),'시간대별 사용량 · UTC'):chart(roleGroups(d),'역할별 사용량',true)}<div class="token-legend">${Object.entries(colors).filter(([k])=>['orchestrator','planning','design','development','verification'].includes(k)||d.roles.some(r=>r.code===k)).map(([k,c])=>`<span><i style="background:${c}"></i>${esc(d.taxonomy.roles[k]||k)}</span>`).join('')}</div>${!active?`<div class="token-task-list">${d.tasks.map(t=>`<button class="token-task" data-token-task="${esc(t.task_id)}" aria-pressed="${task===t.task_id}"><span>${esc(t.title)}<small>${esc(t.project_id)} · ${esc(t.task_id)}</small></span><strong>${esc(amount(children?t.including_children_tokens:t.direct_tokens))}</strong></button>`).join('')}</div>`:''}${!none?`<details class="token-detail" data-token-open="development"><summary>개발 담당별 사용량</summary>${chart(developerGroups(d).length?developerGroups(d):[{code:'coordinator',label:'개발 코디네이터',tokens:null}],'개발 담당별 사용량')}<p class="token-source-note">선택된 실제 담당만 표시합니다. QA·기획·디자인의 개발 담당은 해당 없음입니다.</p></details>${!active?`<h3 class="token-chart-title">실행 목적별 사용량</h3>${chart(d.purposes,'실행 목적별 사용량')}`:''}<details class="token-detail" data-token-open="repeat"><summary>최초 수행·보완·재시도·재검증</summary>${chart(d.repetitions,'반복·보완 관계별 사용량')}</details><details class="token-detail" data-token-open="actors"><summary>실행 주체별 사용량</summary>${chart(d.actors,'실행 주체별 사용량')}</details><details class="token-detail" data-token-open="rows"><summary>개별 실행과 원본 사용량 (${d.selected_responses}응답)</summary><table><tr><th>작업</th><th>역할·담당</th><th>목적·반복 관계</th><th>확인된 사용량</th></tr>${tableRows(d)}</table></details>`:''}${!active?`<p class="token-source-note">선택 대상의 확인된 총량 ${esc(amount(d.project_known_tokens))} · 작업 미연결 ${d.unlinked_responses?esc(amount(d.unlinked_tokens)):'기록 없음'}</p>`:''}${d.target_scope?`<p class=token-source-note>등록 대상 ${esc(d.target_scope.selected_project_id)} · 제품 작업 ${esc(amount(d.target_scope.product_work_tokens))} · 다른 대상 ${esc(amount(d.target_scope.other_targets.tokens))} · 대상 미확인 ${esc(amount(d.target_scope.unknown_target.tokens))} · 저장소 전체 ${esc(amount(d.target_scope.repository_known_tokens))} (모든 대상과 대상 미확인 포함, 저장소 내 중복 응답 제외)</p>`:''}${d.unquantified_records.length?`<p class="token-warning">사용량을 확인할 수 없는 기록 ${d.unquantified_records.length}건이 있습니다. 전체 사용량은 미확정입니다.</p>`:''}<details class="token-detail" data-token-open="quality"><summary>분류 근거와 수집 한계</summary><p>역할별·목적별 합계는 같은 사용량을 다른 기준으로 나눈 값입니다. 두 합계를 더하지 않습니다.</p><p>확인된 소계이며 미수집량을 0으로 판정하지 않습니다. 부모 포함 보기에서도 응답을 한 번만 셉니다.</p><pre>${esc(JSON.stringify({quality:d.quality,snapshots_not_added:d.snapshots_not_added,deduplicated_events:d.deduplicated_events,unquantified:d.unquantified_records},null,2))}</pre></details>`;
  const choices=active?d.tasks.filter(t=>d.active_executions.some(e=>e.task_id===t.task_id)):d.tasks;
  panel.querySelector('#token-filter').innerHTML=`<div class="token-tabs" style="margin-top:12px"><label>작업 <select class="token-select" id="token-task-select"><option value="">${active?'현재 작업 전체':'전체 작업 · 미연결 포함'}</option>${choices.map(t=>`<option value="${esc(t.task_id)}" ${task===t.task_id?'selected':''}>${esc(t.title)} · ${esc(t.task_id)}</option>`).join('')}</select></label>${task?`<label>실행 <select class="token-select" id="token-execution-select"><option value="">모든 실행</option>${(d.tasks.find(t=>t.task_id===task)?.execution_ids||[]).map(id=>`<option value="${esc(id)}" ${id===execution?'selected':''}>${esc(id.slice(0,12))}</option>`).join('')}</select></label><label><input type="checkbox" id="token-children" ${children?'checked':''}> 하위 작업 포함</label>`:''}</div>`;
  panel.querySelectorAll('details').forEach(e=>e.open=opened.includes(e.dataset.tokenOpen));
  if(same){const list=panel.querySelector('.token-task-list');if(list)list.scrollTop=listScroll;window.scrollTo(...scroll);}
 }
 async function refresh(){
  if(busy){pending=true;return;}busy=true;const key=[mode,task,execution,children].join('|');
  try{
   const q=new URLSearchParams({mode});if(task)q.set('task',task);if(execution)q.set('execution',execution);if(children)q.set('children','1');
   const r=await fetch('/api/usage?'+q,{cache:'no-store'});if(!r.ok)throw Error('사용량 조회 실패');const d=await r.json();
   if(key!==[mode,task,execution,children].join('|')){pending=true;return;}
   last=d;const sig=JSON.stringify([key,d.known_tokens,d.project_known_tokens,d.rows,d.active_executions,d.quality,d.collection_mode]);
   if(sig!==signature){signature=sig;render(d);}else{const node=panel.querySelector('#token-meta');if(node)node.textContent=meta(d);}
   const error=panel.querySelector('#token-error');if(error)error.textContent='';
  }catch(e){const node=panel.querySelector('#token-error');if(node)node.textContent='사용량 갱신 실패 · 이전 결과 표시';else panel.textContent='사용량을 조회할 수 없습니다.';}
  finally{busy=false;if(pending){pending=false;refresh();}}
 }
 document.addEventListener('click',e=>{
  const tab=e.target.closest('[data-token-mode]'),row=e.target.closest('[data-token-task]'),node=e.target.closest('[data-node]');
  if(tab){mode=tab.dataset.tokenMode;task='';execution='';children=false;refresh();}
  if(row){mode='tasks';task=row.dataset.tokenTask;execution='';refresh();}
  if(node&&flow){const target=flow.nodes.find(n=>n.key===node.dataset.node)?.primary_task_id;if(target){mode='tasks';task=target;execution='';refresh();}}
 });
 document.addEventListener('change',e=>{
  if(e.target.id==='token-task-select'){task=e.target.value;execution='';refresh();}
  if(e.target.id==='token-execution-select'){execution=e.target.value;refresh();}
  if(e.target.id==='token-children'){children=e.target.checked;refresh();}
 });
 refresh();setInterval(()=>{if(!document.hidden&&document.activeElement?.tagName!=='SELECT')refresh();},3000);
})();
