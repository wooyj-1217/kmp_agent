const num=n=>Number(n).toLocaleString('ko-KR');
const usageLabels=['기획','디자인','개발','검증','리포트','공통','귀속 불명','라벨 충돌'];
let usageSelection=null;
function usageSection(){
 const u=data.usage,c=u.comparison,info=u.scope_info,tot=u.totals;
 const scopeLine=i=>`${i.period?.length?i.period.map(date).join(' ~ ')+' (브라우저 현지 시각)':'기간 미확인'} · 작업 ${num(i.tasks)}개 · 역할 실행 ${num(i.role_executions)}개 · 응답 ${num(i.responses)}개`;
 const knownCosts=u.rows.filter(r=>r.scenario_cost!==null),costTotal=knownCosts.reduce((s,r)=>s+r.scenario_cost,0);
 return `<section id="usage-section"><span class="eyebrow">사용량 · 범위가 먼저입니다</span><h2>선택 실행에 연결된 응답만</h2><p class="usage-total"><strong>${!u.rows.length?'연결된 사용량 기록 없음':mode==='tokens'?num(tot.tokens)+' 토큰':knownCosts.length?'$'+costTotal.toFixed(6)+' · 단가 기반 추정 비용':'비용 산정 불가'}</strong> <span>${u.rows.length?'로그에서 확인된 사용량 '+num(tot.tokens)+' 토큰':'사용량 0으로 판정하지 않습니다.'} · 응답 ${num(info.responses)}개${mode==='cost'?' · 실제 청구액 미확인':''}</span></p><p>${esc(scopeLine(info))}</p><p class="muted">${esc(u.coverage)}</p><div id="usage-controls"><button data-mode="tokens" aria-pressed="${mode==='tokens'}">토큰</button> <button data-mode="cost" aria-pressed="${mode==='cost'}">추정 비용</button> <label for="group">보기</label><select id="group"><option value="stage">단계 라벨별</option><option value="role">역할별 · 원본 실행 역할</option><option value="development_area">개발 전문 영역 · 원본 실행 영역</option><option value="response_stage">응답 활동 · 사후 분류</option><option value="rework">재작업 연결별 · 단계와 별도</option><option value="task">작업별</option><option value="hour">시간별 · UTC</option></select></div><p id="cost-note"></p><div class="legend"><span><i class="normal"></i>일반 입력</span><span><i class="cached"></i>캐시 입력</span><span><i class="output"></i>출력</span><small>단위: ${mode==='tokens'?'토큰':'USD · 단가 기반 비교 추정'}</small></div><div id="chart" aria-label="선택 실행 사용량 그래프"></div><div id="usage-selection" aria-live="polite"></div>
 ${detail('이전 2억 2,772만 토큰과 왜 다른가',c?`<div class="scope-comparison"><article><h3>현재 선택 · ${num(tot.tokens)} 토큰</h3><p>${esc(scopeLine(info))}</p><p>프로젝트: ${esc(data.project)}. 원장에 명시적으로 연결된 응답만. 작업 단계·역할과 응답 활동 사후 분류를 별도 보기로 구분합니다.</p></article><article><h3>보존 분석 · ${num(c.tokens)} 토큰</h3><p>${esc(c.period.map(date).join(' ~ '))}</p><p>작업 ${c.tasks}개 · 역할 실행 ${c.role_executions}개 · 요청 ${c.requests}건 · 응답 ${num(c.responses)}개</p><p>${esc(c.project_scope)}</p><p>그중 원래 실행 연결(기간 필터 전) ${num(c.linked_responses)}개 / ${num(c.linked_tokens)} 토큰, 그 밖의 사후 요청 문맥 ${num(c.posthoc_context_responses)}개 / ${num(c.posthoc_context_tokens)} 토큰.</p></article></div><p>${esc(c.note)}</p><p>혼합 제품/하네스 요청의 응답 ${c.mixed_excluded_responses}개는 광역 합계에서 제외. 이전 요청 30건의 하네스·환경 지침 8건도 범위 제외. 귀속 불명은 범위 제외와 다르며 사후 문맥 분석에 포함될 수 있습니다.</p><p>광역 분석의 작업 귀속 불명 ${c.unknown_task_responses}개, 여러 작업 문맥 ${c.multiple_task_context_responses}개는 각각 중복 배분하지 않았습니다. 전체 원본 사용량·수집 누락량은 UNKNOWN이므로 위 숫자로 전체 수집률을 계산하지 않습니다.</p>${detail('비교 원본·기간·집계 범위 상세',json({selected:info,archive:c.source,analysis_generated_at:c.generated_at,classification:'원장 연결과 사후 분류는 별개',whole_v1_usage:c.whole_product_usage}))}`:`<p>검증된 비교 원본이 연결되지 않았거나 변경되어 대조할 수 없습니다. ${esc(u.analysis_state)}</p>`)}
 ${detail('토큰 계산·분류·가격 근거',`<p>일반 입력 = 전체 입력 − 캐시 입력. 총 토큰 = 일반 입력 + 캐시 입력 + 출력. reasoning은 출력의 부분집합이므로 더하지 않습니다. thread/turn 누적 수치는 합산하지 않고 응답 ID로 중복 제거합니다.</p><p>집계 제외: 충돌·누락·부적합 응답 ${u.excluded}건. 단계는 명시 연결된 역할 실행의 시작 당시 작업 계약이며 역할 축·응답 활동 사후 분류와 구분합니다. 기록이 없는 라벨은 0이 아닌 ‘연결 기록 없음’입니다. 재작업은 단계와 겹칠 수 있어 별도 보기이며 합계에 더하지 않습니다.</p><p>가격 계산 = (일반 입력×일반 단가 + 캐시 입력×캐시 단가 + 출력×출력 단가) ÷ 1,000,000. 모델 불일치·단가 미확인은 산정 불가.</p>${c?`<p>보존된 2026-10-21 단가의 Standard 비교 시나리오만 적용. 현재 가격·당시 실제 서비스 등급·Codex 구독 청구액은 확인되지 않았습니다. 장문 가산·세금·할인·도구 비용을 포함하지 않습니다.</p>${json(c.pricing_reference)}`:'<p>적용 가능한 단가 근거 없음</p>'}${detail('합산 제외·충돌 근거',json({excluded:u.excluded,conflicts:u.conflicts}))}${detail('선택 응답 상세 · ID·분류 이유·집계 입력',json(u.rows))}`)}
 </section>`;
}
function usageGroups(){
 if(!data.usage.rows.length)return [];
 const groups=new Map();
 for(const r of data.usage.rows){const k=grouping==='task'?`${r.project_id||'프로젝트 미연결'} / ${r.task_id||'작업 미연결'}`:r[grouping]||'귀속 불명';if(!groups.has(k))groups.set(k,[]);groups.get(k).push(r);}
 if(grouping==='stage')return usageLabels.map(k=>[k,groups.get(k)||[]]);
 return [...groups];
}
function drawChart(){
 const groups=usageGroups(),rows=data.usage.rows;
 const val=r=>mode==='tokens'?r.tokens:r.scenario_cost??0;
 if(mode==='cost'&&rows.length&&rows.every(r=>r.scenario_cost===null)){$('#chart').innerHTML='<p>산정 불가 · 모델·단가·기준일 연결 없음. 실제 청구액 UNKNOWN.</p>';$('#usage-selection').innerHTML='';$('#cost-note').textContent='산정 불가를 0 비용으로 표시하지 않습니다.';return;}
 const total=rows.reduce((s,r)=>s+val(r),0),time=grouping==='hour';
 const series=time?groups.slice().sort(([a],[b])=>a.localeCompare(b)):groups;
 let cumulative=[];
 const sums=series.map(([,rs])=>{cumulative=cumulative.concat(rs);return (time?cumulative:rs).reduce((s,r)=>s+val(r),0);});
 $('#usage-section .legend').innerHTML=time?`<span><i class="normal"></i>누적 ${mode==='tokens'?'총 토큰 (일반 입력 + 캐시 입력 + 출력)':'단가 기반 추정 비용'}</span>`:`<span><i class="normal"></i>일반 입력</span><span><i class="cached"></i>캐시 입력</span><span><i class="output"></i>출력</span><small>단위: ${mode==='tokens'?'토큰':'USD'}</small>`;
 const max=Math.max(1,...sums),unit=mode==='cost'?1:max>=1e6?1e6:max>=1000?1000:1,unitName=mode==='cost'?'USD':unit===1e6?'백만 토큰':unit===1000?'천 토큰':'토큰';
 const width=Math.max(740,series.length*155+100),height=430,left=80,top=45,bottom=300,plotW=width-left-25,step=plotW/Math.max(1,series.length);
 const y=n=>bottom-(bottom-top)*n/max;
 let svg=`<svg role="group" aria-label="${time?'시간별 누적 사용량 선그래프':'누적 세로 막대그래프'}" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><text x="8" y="20">${unitName}</text>`;
 for(let i=0;i<=5;i++){const n=max*i/5,yy=y(n);svg+=`<line x1="${left}" y1="${yy}" x2="${width-25}" y2="${yy}" stroke="#d6dfe9"/><text x="${left-10}" y="${yy+5}" text-anchor="end">${(n/unit).toLocaleString('ko-KR',{maximumFractionDigits:2})}</text>`;}
 let points=[];const firstTime=time&&series.length?Date.parse(series[0][0]+':00:00Z'):0,lastTime=time&&series.length?Date.parse(series[series.length-1][0]+':00:00Z'):0;
 series.forEach(([label,rs],i)=>{
  const x=time&&lastTime>firstTime?left+step/2+(plotW-step)*(Date.parse(label+':00:00Z')-firstTime)/(lastTime-firstTime):left+step*(i+.5),v=sums[i],unknown=mode==='cost'&&rs.some(r=>r.scenario_cost===null),index=groups.findIndex(([k])=>k===label);
  const tooltip=!rs.length&&!time?`${label}: 연결 기록 없음 · 사용량 0 판정 아님`:`${label}: ${mode==='tokens'?num(v)+' 토큰':'$'+v.toFixed(6)} · ${total?(v/total*100).toFixed(1):'미산정'}% · ${time?series.slice(0,i+1).reduce((s,[,r])=>s+r.length,0):rs.length}응답${unknown?' · 산정 불가 포함':''}`;
  svg+=`<g tabindex="0" role="button" aria-label="${esc(label)} 사용량 근거 보기" data-usage-index="${index}"><title>${esc(tooltip)}</title><rect x="${x-step/2+2}" y="20" width="${step-4}" height="${height-40}" fill="transparent"/>`;
  if(time){points.push(`${x},${y(v)}`);svg+=`<circle cx="${x}" cy="${y(v)}" r="6" fill="#204e7c"/>`;}
  else if(rs.length){let used=0;const rates=data.usage.comparison?.pricing_reference.scenarios.standard_short_base;['normal_input','cached_input','output'].forEach((key,j)=>{const n=rs.reduce((s,r)=>s+(mode==='tokens'?r[key]:r.scenario_cost===null?0:r[key]*(rates?.[key]??0)/1e6),0);svg+=`<rect x="${x-29}" y="${y(used+n)}" width="58" height="${(bottom-top)*n/max}" fill="${['#204e7c','#71afd1','#c38323'][j]}"/>`;used+=n;});}
  svg+=`<text x="${x}" y="${rs.length?Math.max(28,y(v)-10):bottom-15}" text-anchor="middle">${rs.length?(unknown&&v===0?'산정 불가':mode==='tokens'?num(v):'$'+v.toFixed(4)):'연결 기록 없음'}</text>`;
  const display=time?label.slice(5,10)+' '+label.slice(11,13)+':00':label.length>40?label.slice(0,40)+'…':label;for(let j=0;j<display.length;j+=12)svg+=`<text x="${x}" y="${bottom+25+Math.floor(j/12)*19}" text-anchor="middle">${esc(display.slice(j,j+12))}</text>`;
  svg+='</g>';
 });
 if(time)svg+=`<polyline points="${points.join(' ')}" fill="none" stroke="#204e7c" stroke-width="3" pointer-events="none"/>`;
 svg+=`<text x="${width/2}" y="${height-8}" text-anchor="middle">${time?'시각 (UTC) · 선택 기간 내 누적':grouping==='role'?'역할':grouping==='task'?'작업':'분류 라벨'}</text></svg>`;
 $('#cost-note').textContent=(mode==='cost'?'단가 기반 추정 비용 · 보존된 2026-10-21 Standard API 비교 시나리오. 실제 청구액 미확인. ':'확인된 응답별 증분 토큰. ')+(time?'각 시각까지 누적한 값이며 누적 지점들을 다시 합산하지 않습니다.':'비중은 선택 범위의 확인된 소계 기준입니다. 막대 선택/마우스 올림으로 정확한 수치를 확인합니다.');
 $('#chart').innerHTML=rows.length?`<div class="chart-scroll">${svg}</div><p>라벨이 많으면 좌우로 스크롤하세요.</p>${detail('전체 라벨·수치 보기',`<div class="scroll"><table><tr><th>라벨</th><th>합계</th><th>응답 수</th></tr>${series.map(([label,rs],i)=>`<tr><td>${esc(label)}</td><td>${!rs.length?'연결 기록 없음':mode==='tokens'?num(sums[i]):rs.every(r=>r.scenario_cost===null)?'산정 불가':'$'+sums[i].toFixed(6)}</td><td>${time?series.slice(0,i+1).reduce((s,[,r])=>s+r.length,0):rs.length}</td></tr>`).join('')}</table></div>`)}`:'<p>연결 기록 없음 · 사용량 0 판정 아님</p>';
 $('#usage-selection').innerHTML='';
 const chosen=usageSelection?.scope===data.selected&&usageSelection?.grouping===grouping?groups.findIndex(([k])=>k===usageSelection.label):-1;if(chosen>=0)showUsage(chosen);
}
function showUsage(index){
 const group=usageGroups()[index];if(!group)return;let [label,rows]=group;if(grouping==='hour'){rows=usageGroups().filter(([k])=>k<=label).flatMap(([,rs])=>rs);}
 usageSelection={scope:data.selected,grouping,label};
 if(!rows.length){$('#usage-selection').innerHTML='<p>'+esc(label)+' · 연결 기록 없음 · 사용량 0 판정 아님</p>';return;}
 const sum=k=>rows.reduce((s,r)=>s+r[k],0);const known=rows.filter(r=>r.scenario_cost!==null),amount=known.reduce((s,r)=>s+r.scenario_cost,0);const denominator=mode==='tokens'?data.usage.totals.tokens:data.usage.rows.reduce((s,r)=>s+(r.scenario_cost??0),0),chosen=mode==='tokens'?sum('tokens'):amount;
 $('#usage-selection').innerHTML=`<h3>${esc(label)} · 응답 ${rows.length}개</h3><p>${mode==='cost'?(known.length?'$'+amount.toFixed(6)+' · 단가 기반 추정 비용':'비용 산정 불가'):'확인된 토큰'} · 선택 소계 내 비중 ${denominator?(chosen/denominator*100).toFixed(1)+'%':'미산정'}</p><p>일반 입력 ${num(sum('normal_input'))} + 캐시 입력 ${num(sum('cached_input'))} + 출력 ${num(sum('output'))} = <strong>${num(sum('tokens'))} 토큰</strong></p><p>관련 작업: ${[...new Set(rows.map(r=>r.task))].map(esc).join(' · ')}</p><p>작업 귀속: 원본의 명시적 연결. 작업 단계: ${[...new Set(rows.map(r=>r.classification))].map(esc).join(' · ')}. 재작업 분류는 별도이며 이 응답을 중복 합산하지 않습니다.</p>${detail('응답별 집계·분류 근거',`<div class="scroll"><table><thead><tr><th>작업 / 응답</th><th>라벨 · 분류 이유</th><th>일반 입력</th><th>캐시 입력</th><th>출력</th><th>합계</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.task)}${detail('응답 연결',json({response_id:r.response_id,session_id:r.session_id,agent_run_id:r.agent_run_id,attribution:r.attribution,source:r.classification_source,occurred_at:r.occurred_at}))}</td><td>${esc(r.stage)} · ${esc(r.classification)}<p>${esc(r.stage_basis||'단계 연결 미확인')} · 원본 ${esc(typeof r.raw_stage==='object'?JSON.stringify(r.raw_stage):r.raw_stage||'UNKNOWN')}</p><p>응답 활동(별도 사후 분류): ${esc(r.response_stage)}</p><p>${r.classification_reason.map(esc).join(' / ')||'근거 없음'}</p></td><td>${num(r.normal_input)}</td><td>${num(r.cached_input)}</td><td>${num(r.output)}</td><td>${num(r.tokens)}</td></tr>`).join('')}</tbody></table></div>`)}`;
}
document.addEventListener('click',e=>{const b=e.target.closest('[data-usage-index]');if(b)showUsage(Number(b.dataset.usageIndex));});

document.addEventListener('keydown',e=>{const b=e.target.closest('[data-usage-index]');if(b&&['Enter',' '].includes(e.key)){e.preventDefault();showUsage(Number(b.dataset.usageIndex));}});
