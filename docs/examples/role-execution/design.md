# EX-FEAT-001 메모·즐겨찾기 디자인 명세

## 기준·범위·진행
FEAT-ROLE-001 / TASK-STAR-RETURN / agent_run_id b9386521-5b5a-4efa-89e4-2fff02121853. 승인 P-004: requirements.md SHA-256 e2441a3416533e7e4e29fe99f39d708ac6d4670d11854870923e8e9a8d585fe1. 最後 승인 디자인은 D-003/P-004이며 before design SHA-256 b613db77fae9653221c70ab717c5f5d7662823e2d07f795bdd5b00d167d21557. 연결 CR-002/003. 새 D 번호·개발 인계 D·외부 PR은 UNKNOWN이다.
재개 결정 design-return-decision.md SHA-256 94ba4fcff42c24e3c9de1ab5a9b162a303a24299071b5774e91f2b007344adeb를 적용한다. 이전 checkpoint·합성 후보·승인 원본은 보존한다. 시도 상한 변경이나 원본 직접 편집은 하지 않는다.
합성 HTML 예제만 수행한다. 실제 제품 확정·네이티브 실행·앱 구현·KMP 웹 빌드·API·실제 저장은 제외한다. 실제 OS/브라우저 지원과 Q-001~006 제품 정책은 UNKNOWN이다. 입력 Git b802d18b068d4a213946a0c7f3b5dee77b6c6621은 새 출력 커밋이 아니다. 예제 콘텐츠 snapshot 예외를 유지한다.

| 구분 | 상태 | 근거 |
|---|---|---|
| 명세 작성 | WRITTEN | P-004 유지·반환 수정 범위와 재검증 연결, 검토 전 |
| 시안 제작 | PRODUCED_UNVERIFIED | files/reuse 전체 자원 제출, 실행기 반영 필요 |
| 시각 검토 | NOT_RUN | 실제 브라우저·캡처 관측 없음 |

구조·인터랙션·시각 재검증은 각각 NOT_RUN이다. C1/C2 PASS·DONE·이슈 해결·개발 인계를 선언하지 않는다.

## 방향·진입·자원
외부 레퍼런스 없음. 제공 P-004·D-003·CR 요청·재개 결정을 근거로 기존 합성 A를 유지한다. 실제 사용자 선택으로 승격하지 않는다. 반환 수정은 방향 변경이 아니므로 새 비교/질문은 N/A다. 활성 시안 A-targets r2, index.html → app-favorites.html / web-favorites.html / components.html. 로컬 브라우저에서 열며 별도 빌드·서버·외부 서비스가 필요 없다.
두 활성 HTML은 tokens.css·favorites-cr003.css·기존 app/web 표현 CSS·기존 favorites-cr003.js를 유지하고 favorites-return.js만 뒤에 defer로 추가한다. 현재 갤러리는 title만 수정한다. index는 동결 정상 입력을 reuse하여 합성 후보 링크를 정상 앱 링크로 복원한다. 의존 상세·토큰·컴포넌트 원본은 prototype/system.md에 명시한다. 과거 합성 앱 후보는 checkpoint bytes 그대로 files에 보존하며 활성 타깃에서 제외한다. 기존 JS/CSS 및 과거 비교 파일은 reuse하여 의존 bytes를 유지한다. 새 출력 hash는 실행기가 고정한다.

## 화면·상태·행동 계약
AC-001~004는 EX-FEAT-001-AC-001~004, F01~F08/T01~T03은 EX-FEAT-001-AC-F01~F08/T01~T03의 축약이다.

| SCREEN | 구조·컴포넌트·목적 | 연결 AC |
|---|---|---|
| SCREEN-LIST | 제목→정렬된 행→live 안내. COMP-ROW의 제목 열기와 COMP-FAV를 분리. data-memo-id 유지 | F01~F06,T01,T02 |
| SCREEN-EDITOR | 복귀→제목/COMP-FAV→COMP-001 본문 또는 COMP-004 요청 원문→범위/COMP-003 안내→COMP-002 저장/대기/재시도. 기존 SCREEN-001 책임 계승 | AC-001~003,F01,F04,F07,T01,T02 |
| COMPONENT-GALLERY | 앱/웹 행·즐겨찾기 양 상태·본문·저장 활성/비활성/재시도·안내·요청 본문·빈 상태의 정적 예제. lang=ko, title=메모 컴포넌트 | F06 |

| STATE | 표시·복구 |
|---|---|
| LIST-DEFAULT | 3개 false, m-01,m-02,m-03 |
| LIST-MIXED | 하나 이상 true, 모두 선택 포함. true 우선→생성 order→ID |
| LIST-EMPTY | 메모 없음, 행별 열기/토글 없음, 과거 선택 안내 없음 |
| NO-SELECTION | 데스크톱 선택 안내. 빈 목록이면 메모 없음 |
| EMPTY | 기존 메모 빈 본문 표시만. 빈 저장 정책은 UNKNOWN |
| EDITING | 원문 입력, 비공백 본문만 가상 저장 |
| SAVING | 요청 원문·disabled 저장·가상 응답 대기 |
| SAVED | 메모가 저장됐어요 같은 화면에 요청한 본문을 표시합니다. 실제 저장·영속성은 보장하지 않습니다. |
| ERROR | 요청 원문 복원·긴 오류·재시도 |
| FAV-OFF/FAV-ON | 다섯 본문 상태와 독립, ☆/★·텍스트·aria-pressed 일치 |

목록 로딩/API 오류는 페이지 메모리 샘플이므로 N/A다. 본문 처리/오류/비활성은 SAVING/ERROR/disabled로 제공한다.

| ACT | 전제·전환·피드백 |
|---|---|
| ACT-MEMO-OPEN | 본문 미수정·대기 없음에서 동일 ID 편집, 즐겨찾기 불변 |
| ACT-LIST-RETURN | 같은 조건에서 모바일 목록 복귀 또는 데스크톱 목록 포커스 |
| ACT-FAV-TOGGLE | 목록/편집 모든 본문 상태에서 해당 ID만 반전·안정 정렬·접근성/포커스 갱신 |
| ACT-001 | 입력 원문 유지, EMPTY/EDITING |
| ACT-002/003 | 비공백 본문 요청 복사→SAVING, 중복 요청 차단 |
| ACT-004/005 | SAVING→SAVED 또는 ERROR, 요청 원문·즐겨찾기 보존 |
| ACT-006 | ERROR 비공백 본문→새 가상 요청·SAVING |

샘플 초기화는 3개 false·미선택·listStatus 빈 문자열, 빈 목록은 메모/선택 제거·listStatus 빈 문자열이다. 기존 onclick 뒤 추가 listener가 안내만 지운다. 저장·정렬·메모 데이터 규칙은 변경하지 않는다. 상태 선택은 표시용, 긴 본문은 문장/연속문자/개행12회이며 별도 aside에서 조작한다.

## 크기·입력·접근성
공통 tokens.css의 색상·16px 본문·8/16/24px 간격·44px 조작·12px 모서리를 그대로 사용한다. 값·CSS 변수·사용처는 system.md에 기록한다.

| 타깃 | 배치 | 입력·포커스·스크롤 |
|---|---|---|
| app | 390×844, 최대480px 단일 목록↔편집 | 터치용44px 버튼, 열기→제목/상단, 복귀→동일 열기 버튼/목록 위치. 페이지 스크롤 |
| web-mobile | 390×844, 900px 미만 단일 열 | Tab/Shift+Tab·Enter/Space, 열기/복귀 포커스·목록 위치 복원, 페이지/본문 스크롤 |
| web-desktop | 1280×900, 900px 이상 목록280~340px+편집, 간격24px | 목록→편집→샘플 DOM 순서, 선택→편집 제목, 목록 접근→동일 열기 버튼, 패널 독립 스크롤 |

토글은 native button·접근 가능한 이름·aria-pressed·data-action-id/data-memo-id를 유지한다. 재정렬 후 같은 ID의 같은 종류 토글에 포커스한다. 결과는 live 안내에 포커스, snapshot은 키보드 스크롤 가능하다. 좁은 폭 줄바꿈·200% 확대·긴 오류·899/900px 전환은 재검토 대상이다.
본문 변경/SAVING에서 열기·복귀 disabled는 UNKNOWN 이탈 정책을 피하는 기존 INFERRED 시험 가드이며 즐겨찾기는 활성이다. 직접 진입/새로고침은 초기 샘플. history/storage 없음. 브라우저 뒤로/앞으로는 문서 탐색, 미저장 복구 보장 없음. 네이티브 시스템 동작은 NOT_RUN이다.

## 요구·수용 기준 연결
| REQ | SCREEN/STATE/ACT·AC·검증 경로 |
|---|---|
| REQ-001,006 | 합성 범위·snapshot 보존·정확 P→D·ROLE-P1-AC-006 |
| REQ-002 | 편집 EMPTY~SAVED·ACT-001~004·AC-001/002, 정확 성공/비영속성 안내·중복 차단 |
| REQ-003 | ERROR·ACT-005/006·AC-003, 실패 원문·재시도 |
| REQ-004 | AC-004·Q-001~006 UNKNOWN, 관련 제품 분기 차단 유지 |
| REQ-005 | ROLE-P1-AC-005, 세 타깃 상태/긴 콘텐츠/입력/시각 |
| REQ-FAV-001,002 | 두 화면 ACT-FAV-TOGGLE·F01/F02, 반전·표시·열기 독립·키보드 |
| REQ-FAV-003 | LIST-DEFAULT/MIXED·F03, 02선택→02,01,03;03선택→02,03,01;02해제→03,01,02;모두해제→01,02,03 |
| REQ-FAV-004 | 동일 ID 왕복/패널 전환·F04, 페이지 내 값 유지 |
| REQ-FAV-005 | LIST-EMPTY/NO-SELECTION·F05, 빈 목록/초기화·이전 안내 제거 |
| REQ-FAV-006 | index·공유 토큰·갤러리·DOM·F06, 세 타깃 자원 연결 |
| REQ-FAV-007 | F08, 승인 P/D·전체 자원·공식 검토 이후 개발 입력 해석 |
| REQ-002,003,FAV-004 | 다섯 본문 상태×양 즐겨찾기·F07, 저장 전환이 값 초기화하지 않음 |
| REQ-TGT-001,002,003 | T01~T03, 세 target_artifacts·타깃별 구성/입력/증거·네이티브 경계 |

## 반환 수정·공식 재검증
| 이슈 | 출처·수정 | 필수 재검증·현재 판정 |
|---|---|---|
| ISSUE-002 | 자연 MINOR. lang=ko 갤러리의 일본어 title을 메모 컴포넌트로 수정 | 세 타깃 크기에서 실제 document.title/documentElement.lang·갤러리 렌더링/캡처. NOT_RUN |
| ISSUE-003 | 자연 MINOR. 공유 추가 JS로 reset/emptyList 후 listStatus만 비움 | 세 타깃에서 m-02 즐겨찾기 선택→빈 목록, 별도 초기화 후 다시 선택→초기화. 이전 안내 없음·행0/3·초기false·포커스 확인, 실제 DOM/캡처. NOT_RUN |
| ISSUE-004 | 합성 MAJOR. 정상 앱을 index/target entry로 복원. 토글 숨김 후보는 과거 자료로 보존 | app390×844 목록3개·편집1개 토글 노출, 클릭/키보드 반전·정렬·미수정 왕복 값 유지·캡처. NOT_RUN |

새 앱/웹 HTML이 추가 JS를 사용하므로 웹을 변경 없음으로 표현하지 않는다. 각 타깃 초기화/빈 목록 경로를 재실행한다. 갤러리 세 크기와 앱 토글을 실제 재렌더링해야 한다. 비영향 저장/정렬 함수·CSS는 동결 원문 bytes 재사용 근거와 D-003 공식 검토에 연결할 수 있으나 새 PASS 자동 상속은 금지한다.
검토자는 새 출력 hash·P-004·새 D·CR·ISSUE·REQ/AC·SCREEN/STATE/ACT·환경/크기·재현/기대/실제·관찰·캡처 경로/해시를 구조/인터랙션/시각 보고서에 각각 기록하고 target_results를 포함한다. 공식 원본은 task.reviews/design_status.checks다. 본 제출은 원문 검토 보고서나 이슈 상태를 수정하지 않는다. 검토자가 resolve-issue로 실제 재검증 근거를 연결해야 한다.
회귀 검토 범위는 세 타깃 목록 초기/혼합/해제/빈 목록/초기화, 편집 다섯 상태×양 즐겨찾기, 영향 조작과 키보드/포커스다. 긴 본문·긴 오류·성공 안내·잘림/겹침/스크롤·버튼 접근 및 기존 비영향 검토의 동등성도 검토자가 판단한다. 모든 새 실행 결과는 현재 NOT_RUN이다.

## 인계·회고
다음 담당은 실행 관리자·상위 브라우저 검토자다. files/reuse·기준 P-004·before D-003·재개 결정·checkpoint와 이슈를 같은 제출에 연결한다. 필수 FAIL/NOT_RUN 또는 OPEN MAJOR가 남으면 DONE·개발 인계를 차단한다. 일부 타깃 PASS로 전체 완료하지 않는다. 실제 제품 구현/빌드·네이티브 검증은 범위 밖 NOT_RUN이다.
새 핵심 정책 질문은 없다. 변경을 제목·샘플 안내·진입 복원으로 한정했고 기존 데이터/저장/정렬 로직과 과거 후보를 보존했다. 수정 효과·최종 품질은 아직 관측하지 않았으며 공식 재검토 후에만 회고 결과를 확정한다.
