function qaStageLabel(q){return ({planning:'기획',design:'디자인',implementation:'구현',retest:'재검증'})[q.stage]||q.stage_label||'단계 미확인';}
function qaOwnerLabel(value){return ({planning:'기획 담당',design:'디자인 담당',development:'개발 담당',verification:'검증 담당',improvement:'개선 담당',orchestrator:'전체 조율 담당'})[value]||'담당 미등록';}
function qaQualityLabel(value){return ({PASS:'품질 검토 통과',FAIL:'필수 조건 실패',REWORK:'보완 후 재검증 필요',BLOCKED:'품질 판정 차단',NOT_RUN:'품질 검증 미실행',UNKNOWN:'품질 판정 미확인',RECHECK_REQUIRED:'변경 영향 재검증 필요'})[value]||'품질 판정 미확인';}
function qaExecutionLabel(t){
 const p=t.activity?.process_evidence||{},q=t.qa||{};
 if(p.spawned===true)return p.finished_at?`실제 프로세스 종료 · 종료 코드 ${p.exit_code??'미수집'}`:'실제 프로세스 시작 기록 · 현재 생존 미확인';
 return typeof q.execution_observation==='string'?q.execution_observation:'실제 프로세스 실행 근거 미확인';
}
function qaRequiredText(q){
 const r=q.required||{},amount=k=>Number.isInteger(r[k])?r[k].toLocaleString('ko-KR'):'미확인';
 return `필수 시험 항목 ${amount('total')}개 · 통과 ${amount('passed')} · 실패 ${amount('failed')} · 미실행 ${amount('not_run')} · 판정 미확인 ${amount('unknown')}`;
}
function qaFindingCard(f){
 const x=f.qa_finding||{},kind=({specification_violation:'명세 불일치',baseline_gap:'기준 누락',baseline_contradiction:'기준 충돌',usability:'사용성',improvement:'추가 개선 제안'})[x.kind]||'분류 미확인';
 return `<article class="qa-finding"><p><strong>${esc(kind)}</strong> · 반환 ${esc(qaOwnerLabel(f.owner||x.owner_role))}${x.blocking===true?' · 후속 진행 차단':''}</p>${x.expected?`<p>기대: ${esc(x.expected)}</p>`:''}${x.actual?`<p>관측: ${esc(x.actual)}</p>`:''}${detail('재현·근거·반환 상세',json(f),`qa-finding-${f.id}`)}</article>`;
}
function qaDetail(t){
 const q=t.qa;if(!q)return '';
 const p=t.activity?.process_evidence||{},attempts=q.attempts||[];
 return `<section class="qa-detail"><h3>${esc(qaStageLabel(q))} QA · 실행과 품질 판정</h3><p>${esc(qaExecutionLabel(t))}</p><p><strong>${esc(qaQualityLabel(q.quality_outcome))}</strong></p><p>검토 대상: ${esc(q.target_title||'대상 작업 미확인')}</p><p>${esc(qaRequiredText(q))}</p><small>시험 항목 수이며 고유 요구사항 수가 아닙니다. QA 작업 종료·문서 수신만으로 품질 통과가 되지 않습니다.</small>${(q.open_findings||[]).length?`<h4>미해결 사항과 반환 담당</h4>${q.open_findings.map(qaFindingCard).join('')}`:'<p>현재 연결된 미해결 발견 사항 없음. 전체 완료 판정과는 별개입니다.</p>'}<h4>실행 → 판정 → 보완 → 재검증</h4>${attempts.length?`<ol class="qa-attempts">${attempts.map((a,i)=>`<li><strong>${i+1}차 · ${esc(qaQualityLabel(a.outcome))}</strong><p>발견 기록 ${(a.finding_ids||[]).length}건 · 이 검토에서 해소 확인 ${(a.resolved_issue_ids||[]).length}건</p><p>보완: ${esc(typeof a.repair==='object'&&a.repair?({REPORTED_COMPLETE_NOT_VERIFIED:'담당자 보완 보고 · 재검증 필요',BLOCKED:'보완 차단',COMPLETE:'보완 완료 보고'})[a.repair.status]||'보완 상태 상세 확인':a.repair==='NOT_RUN'?'보완 실행 미등록':a.repair||'보완 실행 미등록')}</p>${detail('검토 보고서·보완·재검증 연결',`${a.report?.url?`<p><a href="${esc(a.report.url)}" target="_blank" rel="noopener">실행 보고서 보기</a></p>`:''}${json(a)}`,`qa-attempt-${t.id}-${i}`)}</li>`).join('')}</ol>`:'<p>QA 실행 시도가 등록되지 않았습니다.</p>'}${detail('실제 호출·시각·프로세스 근거',`<p>시작 ${date(p.started_at)} · 종료 ${date(p.finished_at)} · 현재 생존 미확인</p>${json(p)}${json(q.execution_observation)}`)}</section>`;
}
function delegationDetail(t){
 const d=t.delegation||{},a=t.activity||{};
 if(!d.parent_task_id&&!d.child_task_ids?.length&&!a.parent_task_id)return '';
 const parent=data.tasks.find(p=>p.id===(d.parent_task_id||a.parent_task_id));
 const children=(d.child_task_ids||[]).map(id=>data.tasks.find(p=>p.id===id)).filter(Boolean);
 const proof=a.process_evidence||{};
 return `<section><h3>개발 위임 관계</h3>${d.parent_task_id||a.parent_task_id?`<p>상위 개발 작업: ${parent?`<button data-task="${esc(parent.id)}">${esc(parent.title)}</button>`:'현재 조회 범위 밖 · 원본 ID는 상세에서 확인'}</p><p>담당 영역: ${esc(a.area_label||d.development_area)} · 원래 담당 역할: ${esc(a.role_label||t.role)}</p>`:''}${children.length?`<ul>${children.map(c=>`<li><button data-task="${esc(c.id)}">${esc(c.title)}</button> · ${esc(c.activity?.area_label)} · ${esc(c.activity?.status)}</li>`).join('')}</ul>`:''}<p>${esc(d.delegation_reason||a.delegation_reason||'별도 차단·반환 사유 미등록')}</p>${detail('위임 실행·변경·검증 근거',`<p>프로세스 생성 기록: ${proof.spawned===true?'확인':'미수집'} · 어댑터 ${esc(proof.adapter||'UNKNOWN')}</p><p>독립 모델 실행 기록: ${proof.independent_model_spawned===true?'실제 프로세스 시작 이벤트에서 확인':proof.independent_model_spawned===false?'시작 이벤트에서 독립 모델 실행 확인 안 됨':'미수집'}. PID: ${esc(proof.pid||'UNKNOWN')} · 현재 생존: 미확인</p><p>프로세스 시작 ${date(proof.started_at)} · 종료 ${date(proof.finished_at)} · 종료 코드 ${esc(proof.exit_code??'UNKNOWN')}</p><p>변경 파일</p>${json(d.changed_files||[])}<p>검증 근거 참조</p>${json(d.verification_evidence||[])}<p>아래 값은 원본 조율 상태이며 영역 검증 PASS와 전체 통합 완료를 대신하지 않습니다.</p>${json(d)}`)}</section>`;
}
function statusLabel(value) {
  return ({TODO:'예정',READY:'시작 준비',IN_PROGRESS:'진행 기록 있음',IN_REVIEW:'검토 대기',DONE:'당시 완료 보고',BLOCKED:'당시 차단'})[value] || '상태 미확인';
}
function complianceLabel(value) {
  return ({PASS:'합의·상태 비교 계약 검토 통과',NON_COMPLIANT:'합의 목표와 불일치 확인',WEB_UNDECIDED:'웹 UI 범위 결정 전',RECHECK_REQUIRED:'합의·상태 비교 재검토 필요'})[value] || '합의·상태 비교 검증 미확인';
}
function taskDetail(t) {
 const rows=data.agent_flow?.groups.flatMap(g=>g.nodes).flatMap(n=>n.tasks||[])||[],r=rows.find(r=>r.task_id===t.id),latest=(t.historical_reviews||[]).slice(-1)[0],v=t.verdict;
 const next=t.next&&!/^(연결 필요|후속 작업 연결 미확인)$/.test(t.next)?t.next:'다음 행동 미등록';
 const actor=r?.execution_kind==='MAIN_SESSION'?'메인 에이전트 직접 수행':r?.execution_kind==='INDEPENDENT_MODEL'?'독립 서브에이전트 수행':r?.execution_kind==='SYNTHETIC_PROCESS'?'합성 독립 실행 사례':'실행 주체 미확인';
 return `<h3>현재 상태와 다음 행동</h3><p>${badge(r?workStatus(r):statusLabel(t.raw_state))} ${badge(r?.execution_observation||'현재 실행 여부 미확인')}</p><p>${esc(actor)} · 마지막 활동 ${date(t.activity?.last_activity)}</p><p>다음 행동: ${esc(next)}</p><h3>작업 체크리스트</h3>${(t.criteria||[]).map(c=>`<p>${esc(c.description||c.id)} · ${esc(c.result||c.status||'미검증')}</p>`).join('')||'<p>체크리스트 기록 없음</p>'}<h3>최신 검증 결과와 현재 유효성</h3><p>${badge(({RECHECK_REQUIRED:'재검증 필요',PASS:'PASS',FAIL:'FAIL'})[v]||'미검증',v==='RECHECK_REQUIRED'?'warn':'')}</p><p>${esc(t.revalidation_summary||(t.reasons||[]).join(' / ')||'현재 유효성 근거 미확인')}</p>${latest?`<p>최근 기록: ${esc(latest.result)} · ${date(latest.reviewed_at)} · ${esc(latest.criterion)}</p>`:''}<h3>미해결 결함·차단·사용자 결정</h3><p>${esc(t.blocked||r?.reason||'연결된 차단 기록 없음')}</p>${(t.qa?.open_findings||[]).map(qaFindingCard).join('')}${(data.agent_flow?.decisions||[]).filter(d=>!d.task_id||d.task_id===t.id).map(d=>`<p class="decision-alert">사용자 결정 필요: ${esc(d.question)}</p>`).join('')}`;
}
function taskHistory(t){return detail('과거 검증·실행·보완 이력',`${qaDetail(t)}${(t.historical_reviews||[]).map(r=>`<p>당시 ${esc(r.result)} · ${esc(r.criterion)} · ${date(r.reviewed_at)} ${r.url?`<a href="${esc(r.url)}">검토 근거</a>`:'검증 근거 미확인'}</p>`).join('')}${json(t.activity?.events||[])}`,`history-${t.id}`)+detail('기술 상세와 원본 근거',`${delegationDetail(t)}${json(t)}`,`technical-${t.id}`);}
function provenanceBanner(s) {
  if(s.provenance?.kind!=='POSTHOC_CONNECTION')return '';
  return `<p class="badge warn">사후 구성 · ${esc(date(s.provenance.connected_at))} 연결 · 원본 상태 보존</p>${detail('사후 연결 범위와 원래 실행의 차이',`<p>${s.provenance.group_kind==='UNSTARTED_PLAN'?'원본의 미착수 후속 작업만 연결했습니다. 과거 실행·사용량·PASS를 이 계획의 실행으로 포함하지 않습니다.':'과거 여러 역할 실행을 검토 목적으로 연결했습니다. 당시 하나의 실행으로 등록되었다고 주장하지 않습니다. 미착수 전환 작업과 선행 입력 이력은 합산하지 않습니다.'}</p>${json(s.provenance)}`)}`;
}
function comparisonSection() {
  if(!data.comparisons?.length)return '';
  return `<section><h2>시안과 실제 플랫폼 화면 · 당시 캡처</h2><p>새 촬영이나 현재 목표 준수 증거가 아닙니다. 상태별 비교에서 빠진 부분은 별도로 표시합니다.</p>${data.comparisons.map(c=>detail(c.label,`<p>${esc(c.note)}</p>${c.images.length?`<div class="comparison-grid">${c.images.map(a=>`<figure><figcaption>${esc(a.label)} ${a.state==='CURRENT'?'':'· 파일 변경/누락'}</figcaption>${a.url?`<a href="${esc(a.url)}" target="_blank" rel="noopener"><img alt="${esc(c.label+' · '+a.label)}" src="${esc(a.url)}" loading="lazy"></a>`:'<p>캡처 미확인</p>'}</figure>`).join('')}</div>`:'<p class="warn">NOT_RUN · 세 플랫폼 상태별 비교 근거 없음</p>'}`)).join('')}</section>`;
}
function relatedHistory() {
  if(!data.related_history?.length)return '';
  return `<section><h2>선행 기획·디자인 입력 이력</h2><p>이 실행의 단계·역할 실행·사용량에 합산하지 않았습니다. 원본의 누락된 프로젝트 ID도 보충하지 않았습니다.</p>${detail('초기 입력 작업 5개 확인',data.related_history.map(t=>`<p><strong>${esc(t.title)}</strong> · ${esc(statusLabel(t.state))}</p><p>${esc(t.identity_note)}</p>`).join(''))}</section>`;
}

function artifactList() {
  const card=a=>`<article><h3>${esc(a.label)}</h3>${badge(a.kind||'문서')}${badge(a.approval)}${badge(a.state==='CURRENT'?'연결한 파일과 일치':a.state==='MISSING'?'파일 누락':'등록 후 변경·재검토 필요',a.state==='CURRENT'?'':'warn')}<p>${a.url?`<a href="${esc(a.url)}" target="_blank" rel="noopener">원문 보기</a>`:'조회 근거 없음'}</p>${a.url&&a.extension==='.html'?detail('미리보기 · '+a.label,`<p>격리된 디자인 시연입니다. 실제 제품·서버·DB와 연결되지 않습니다.</p><iframe title="${esc(a.label)}" sandbox="${a.interactive_preview?'allow-scripts':''}" src="${esc(a.url)}" loading="lazy"></iframe>`):''}</article>`;
  return `<div class="artifact-grid">${data.artifacts.filter(a=>a.featured).map(card).join('')}</div>${detail('기술·API·디자인·실행 안내 등 추가 문서',data.artifacts.filter(a=>!a.featured).map(card).join(''))}`;
}

function blockerContent(s, blocked) {
  if(s.blocker_summary) {
    const affected=blocked.filter(t=>t.compliance==='NON_COMPLIANT'||t.stage==='verification');
    return `<p>${esc(s.blocker_summary)}</p><p>영향받는 작업: ${affected.map(t=>esc(t.title)).join(' · ')||'전환 계획의 공통 선행 조건'}</p><p>다음: ${esc(s.outcome?.next||'작업별 다음 행동 확인')}</p><small>과거 검토 범위 설정 실패와 현재 기술·인수 미충족은 작업 상세에서 구분합니다.</small>`;
  }
  return blocked.length?blocked.map(t=>`<p><strong>${esc(t.title)}</strong></p><p>${esc(t.revalidation_summary||t.blocked||t.reasons.join(' / ')||'필수 검증 실패')}</p><p>다음: ${esc(t.next||'해제 조건 및 재검증 범위 연결 필요')}</p>`).join(''):'<p>연결된 차단 기록이 없습니다. 문제가 없다는 판정은 아닙니다.</p>';
}
