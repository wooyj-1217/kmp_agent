# 기획·디자인 실행과 개발 입력 해석

## 기존 구현과 이번 보완

상태·의존성·시도 상한·agent_run_id·검토·스냅샷·인계·명시적 사용량 귀속은 [Tasks](task-management.md)를 그대로 사용한다. 별도 작업 DB는 없다. `roles.py`는 역할별 고정 입력 패킷과 순차 프로세스 진입점, 대기/재개, 실제 파일 제출을 연결한다. `deliverables.py`는 같은 YAML 안에서 기준본과 P/D/CR 번호를 관리한다.

의미 판단은 실행 에이전트와 검토자의 책임이다. 파일 존재 검사·해시는 요구의 타당성, 실제 사용자 승인, 시각 품질을 증명하지 않는다. 외부 서비스 어댑터·상시 감시·병렬 배정은 없다.

## 실행 계약

아래 기능 폴더·기준본·코드·실행 로그·검증 증거는 적용 프로젝트에 보관한다. 하네스 원본의 docs/examples/는 사용법 설명·제한된 시험 자료이며 제품 기록을 자동 수집하는 장소가 아니다. 하네스 배포 버전과 프로젝트 피처의 P/D/API/CR·Git 기준을 구분한다.

| 역할 | 입력 | 실제 출력·소유 범위 | 도구·완료 판단 |
| --- | --- | --- | --- |
| planning | 제품 목표·사용자·범위·기존 정책/자료/결정·명시적 CR, 기존 requirements 및 기준본 | 기능 폴더 requirements.md. 문제·사용자·목표·MVP·REQ/POL/AC·흐름·화면별 기능/행동/예외·근거 분류·미결정 영향. 필요한 표/흐름 도식 | 패킷 원본 읽기·로컬 읽기 도구·문서 생성·질문. 기존 기획 완료 기준을 검토자가 기준별 증거로 확인해야 DONE |
| design | 승인 P 버전의 불변 원본, 제품 디자인 제약·기존 토큰/스타일/컴포넌트·결정·레퍼런스 | design.md와 prototype/만 수정. tokens.css, components.html, system.md, index.html 및 실제 대표/전체 화면 시안 | 로컬 HTML/CSS/최소 JS 생성, 브라우저 DOM·클릭/키보드·캡처 검토. 기존 명세/시안/시각 검토 기준에 더해 구조·동작·시각 결과 각각 필수 PASS |
| development (input_interpretation_only) | 정확히 승인된 P/D·전체 자원·수용 기준·공식 검토 기록·선택 기술 지침 | development-plan.md만 작성. REQ별 구현 위치·공통/플랫폼 책임·검증/반환·후속 계획 | 새 독립 프로세스가 모든 input의 path/SHA·P/D·AC·해석을 input_receipt로 확인. 의미 검토 후 INTERPRETATION_REVIEWED. 실제 앱 구현·빌드는 NOT_RUN |

세부 명세는 [기획](roles/planning.md), [디자인](roles/design.md), 해당 [템플릿](templates/README.md)이 기준이다. 문서와 시안의 충돌·누락·차단 문제가 있으면 인계하지 않는다. 다른 역할의 확정 정책은 변경하지 않고 CR 제안으로 기획에 반환한다. 위임된 가역적인 시각 선택은 근거와 함께 기록한다.

필수 입력은 전달된 원본·기존 결정에서 먼저 찾는다. 추정은 INFERRED, 미확인은 UNKNOWN으로 유지한다. 질문에는 추천·대안·영향을 제시하며 범위·핵심 정책·대표 시안 선택에 집중한다. 원문 없이 다음 역할이 작업할 수 있게 중요한 결정·출처를 산출물에 포함한다. 실행 로그와 사용량은 명세에 복제하지 않는다.

## 파일·버전·공식 원본

기능 폴더의 현재 작업본 경로는 `requirements.md`, `design.md`, `prototype/`로 고정한다. 최종 제출 전 현재 파일은 초안이다. 공식 인계 기준은 tasks.yaml의 `deliverables[기능 폴더].versions`에 보관된 불변 artifacts이며, `status=APPROVED`인 버전 중 인계 기록에 명시한 정확한 버전만 전달한다. 원본 path·원문 SHA·마스킹된 snapshot SHA·가용 Git 커밋을 재사용한다. Git 없는 예제 시험은 콘텐츠 스냅샷 예외를 명시하며 제품 승인으로 표현하지 않는다.

- P-001, D-001은 기능 폴더별·역할별 독립 증가한다. CR-001은 같은 레지스트리의 변경 요청 번호다. 번호를 재사용하지 않는다.
- 최초 검토 요청과 검토 후 수정본 제출 시 문서와 제출한 모든 토큰·컴포넌트·시안/자원을 함께 snapshot으로 보관한다. 승인·인계 시 그 동일한 기준본에 milestone과 인계 기록을 연결한다. 파일 저장마다 번호를 올리지 않는다. 동일 파일 집합·내용·기준 P를 재제출하면 같은 번호를 사용한다.
- 상태는 레지스트리의 IN_REVIEW / APPROVED / SUPERSEDED / BLOCKED로 관리한다. 이전 승인본은 새 작업본 제출 중 유지하며 새 기준 승인 후 대체된다. 보관된 artifacts는 수정하지 않는다. 현재 파일을 편집해도 이전 인계 bytes는 변하지 않는다.
- 각 D에는 기준 P가 필수이고 그 P artifacts가 실제 task inputs에 포함돼야 한다. 인계에는 P 또는 D와 기준 P, CR, 검토·고정 파일 집합을 연결한다. 개발은 인계된 D→P 체인을 사용한다.
- 비교안은 D-001/A, D-001/B, D-001/C라는 기록상 조합으로 구분한다. 실제 파일명은 기존 [시안 파일명·draft 해시 규칙](roles/design.md#시안-버전-추적)을 따른다. 버전 폴더를 중복 생성하지 않는다. 비교안 파일과 간접 자원도 모두 제출해 보존한다.
- CR에는 요청 내용·이유·근거, before 버전, 영향 REQ/SCREEN/검증/TASK 목록을 기록한다. 변경 역할은 새 TASK에 이전 기준본·CR·명시적 새 입력을 연결한다. after 버전과 검증 결과는 제출/검토 때 연결한다. 비영향 파일·기준 ID·완료 작업은 유지한다. 현재 상시 변경 감시·자동 의미 영향 분석·구현 수정/재검증 실행은 없다. [개발 추적](development-tracking.md)은 명령·조회 시 해시/유효성을 검사한다. 사용자 매번 별도 요청 없는 전체 변경 대응은 목표이며 감시 대상·확정 조건의 실행 설정도 PLANNED다.

## 생성·검증 규격

기존 디자인 자원을 먼저 조사하고 재사용 여부·경로를 system.md에 기록한다. tokens.css는 실제 CSS 변수이며 화면과 components.html이 같은 파일을 참조해야 한다. system.md에는 실제 쓰는 토큰·컴포넌트·변형·상태·사용 규칙만 둔다. 컴포넌트 갤러리에는 정상/비활성/처리 중/오류 등의 실제 시각 예제를 만든다. 각 화면은 REQ/AC와 SCREEN/STATE/ACT 대응을 명세·DOM에 유지한다. CDN·외부 폰트·실제 API를 필수로 만들지 않는다.

대표 시안 비교·선택과 화면 확장은 기존 디자인 절차를 따른다. 시험용 선택은 **합성 시험 결정**으로 명시하며 실제 사용자 선택으로 승격하지 않는다. 실제 미선택은 waiting으로 저장한다. 범위에 필요한 화면×상태×크기·긴 본문/오류 문구를 사전에 열거한다. 실제 렌더링 DOM/계산된 스타일에서 토큰 적용·컴포넌트 일치·overflow를 확인하고, 실제 클릭·입력·키보드로 동작을 확인하며, 캡처를 보고 잘림·겹침·가독성·위계·일관성을 검토한다. 수정 조합만 재검증한다.

검토는 `Tasks.review(..., design_checks={structure: ..., interaction: ..., visual: ...})`로 별도 접수한다. 각 실행 결과는 result, evidence(로컬 보고서), environment, coverage(SCREEN/STATE/ACT/크기·콘텐츠)를 갖는다. 보고서는 테스트한 산출물 snapshot, 실제 캡처 경로/해시, 재현 절차·기대/실제·관찰·남은 결함을 연결한다. 근거 접수는 자동 시각 판정기가 아니며 검토자가 정확성과 충분성을 책임진다. 필수 검증 NOT_RUN/FAIL은 BLOCKED다. 새 제출본의 이전 PASS를 자동 재사용하지 않는다.

## 진입점과 프로토콜

기존 `tasks.py register`로 planning/design 작업과 의미 있는 필수 criteria, 입력, 의존성, max_attempts를 등록한다. 디자인은 `visual_required=true`를 사용한다. `roles.py setup --data`에 task_id, folder, 선택적 planning_version/change_id를 전달한다. planning 검토 DONE → 기존 handoff → design 실행 순서다.

```sh
rtk proxy python3 harness/roles.py --run-id RUN setup --data setup.json
rtk proxy python3 harness/roles.py --run-id RUN planning --task-id TASK-P
rtk proxy python3 harness/roles.py --run-id RUN design --task-id TASK-D
```

기본 어댑터는 설치된 `codex exec --sandbox read-only --ignore-user-config --json`을 별도 cwd·새 대화로 호출한다. [공식 비대화형 실행 문서](https://developers.openai.com/codex/noninteractive/)와 로컬 CLI 도움말을 확인했다. 실행 컨텍스트 분리는 보안 컨테이너 격리가 아니다. 기본 어댑터는 원본을 직접 편집하지 않고 JSON의 files를 반환하며 실행기가 소유 범위만 현재 경로에 반영한다. 브라우저 검증은 별도 검토자가 수행한다. 로컬 셸/브라우저 도구 가용성은 환경마다 다르며 도구 없는 검증은 NOT_RUN이다.

설치 프로젝트에서는 선택한 버전의 `.kmp-agent/agent.py planning|design --task-id ... --run-id ...`도 같은 진입점에 연결된다. 개발 원본 변경을 기존 설치에 자동 전파하지 않으며 새 기능 사용에는 해당 구현을 포함한 버전을 명시적으로 선택해야 한다.

`--worker '["실행파일","인자"]'`는 명시적으로 신뢰한 로컬 프로세스 어댑터다. stdin은 고정된 역할 지침·입력·출처·수용 기준·결정·checkpoint JSON, stdout은 status(submitted/waiting/failed), files(path/content), summary, questions(question/recommended/alternative), completed 배열의 JSON이다. 테스트 fixture worker는 실제 모델이 아니며 결과에 별도 표시한다. 임의 worker 자체의 파일 접근은 OS 권한을 따르며 프로토콜이 sandbox를 제공하지 않는다.

`prepare`는 호출하지 않고 입력 패킷만 만든다. `accept`는 명시적 task_id/agent_run_id/response를 받아 같은 제출 규칙을 적용한다. 필수 실제 파일 누락과 다른 역할 파일 수정은 거부한다. 모델의 완료 진술은 IN_REVIEW까지만 이동시킨다.

패킷에는 관측한 선행/후속 작업과 공식 기준본 메타데이터도 포함한다. 전달되지 않은 PR/결정은 UNKNOWN이며 미등록으로 단정하지 않는다. 실행 시작의 현재 작업본도 snapshot으로 보존하며 실행 중 사용자 편집이 생기면 결과 덮어쓰기를 거부하고 명시적 재기준화를 요구한다. 경로는 기능 폴더 상대 또는 그 정확한 저장소 경로를 허용하되 소유 범위는 동일하게 검사한다. `reuse`는 현재 파일을 다시 읽는 것이 아니라 해당 실행의 동결 input 원문만 재사용한다.

디자인 제출 전 `design_assets.py`는 실제 자원 존재, HTML/CSS의 지원하는 로컬 자원 참조와 제출 집합 포함, CSS 변수 정의·소비, 컴포넌트/진입점의 공유 tokens.css 연결을 검사한다. 이는 소스 검사이며 임의 JavaScript의 모든 동적 의존·시각적 동일성·브라우저 동작을 자동 증명하지 않는다. 브라우저 DOM/스타일·실제 조작·캡처 검토를 별도로 수행한다.

waiting 응답은 완성 단계·초안 파일·질문을 기존 snapshot checkpoint에 남기고 BLOCKED로 둔다. `tasks.py resume`에 task_id, 같은 agent_run_id, decision 파일을 전달한 뒤 역할 진입점을 다시 호출한다. 새 프로세스는 기존 checkpoint·명시적 결정으로 복원하며 완료 단계는 반복하지 않는다. DONE 작업은 실행 진입점이 건너뛴다. checkpoint가 남은 작업을 ready로 새로 시작하지 못한다.

실패/timeout은 원인·프로세스 결과와 기존 실행 ID를 남기고 BLOCKED로 종료한다. 재시도는 기존 ready/begin과 max_attempts를 적용해 새 실행 ID를 발급한다. 자동 무한 재시도는 없다. 프로세스 강제 종료 시 활성 실행은 재개/실패 처리 전에 관측해야 하며 자동 복구 데몬은 없다. Codex 어댑터는 종료 시 관측한 thread.started의 정확한 native session을 기존 sync로 수집하고 native response_id가 있는 증분 사용량만 bind_usage로 귀속한다. 숨은 추론은 수집하지 않는다. 원본 응답 ID 없는 CLI 집계·fixture는 UNKNOWN이다. 임의 어댑터와 현재 세션의 자동 귀속은 지원하지 않는다.

`restore`에 folder/version을 전달하면 문서·토큰·컴포넌트·시안의 보관 snapshot 집합을 `.harness/baselines/<기능 폴더>/<P 또는 D>/`에 재구성한다. 현재 작업본을 덮어쓰지 않으며 복원본이 변경됐으면 덮어쓰기를 거부한다. 보관본에 연결한 검토 결과와 캡처는 기존 reviews 및 artifact snapshot에서 찾는다.

완료 보고는 산출물·검증 결과·미결정·다음 인계 대상을 짧게 제시한다. 실제 파일 생성·검토·승인·제품 완료는 서로 다르다.

## 검토 반환·수정·재검증

`tasks.py issue`에 task_id/kind(design,requirements,policy)/screen/ui_state/observed/expected/severity/recheck/evidence와 선택적 synthetic/impacts를 전달한다. ISSUE 번호는 기존 YAML의 issues 안에서 관리한다. 실제 자연 결함, 후속 요청으로 생긴 범위 차이, 명시적 합성 결함을 관측 근거에 구분한다. 없는 결함을 자연 결함으로 기록하지 않는다.

디자인은 design, 요구·정책은 planning 소유다. `route-issue`는 해당 역할의 TODO/BLOCKED 작업으로만 반환하며 거절된 출력 snapshot·관측 근거를 다음 실행 input에 연결한다. 같은 경로의 이전 input은 과거 executions에 보존하고 다음 실행에는 지정한 최신 원문을 전달한다. `rebase`는 비활성 TODO/BLOCKED에만 새 요청·P/D/CR/타깃을 연결하고 before/after를 기록한다. 기존 max_attempts를 그대로 소비한다. 활성 질문 대기는 checkpoint/resume를 사용한다.

수정 에이전트의 제출·해결 주장은 issue를 닫지 않는다. 검토자가 새 출력 hash를 대상으로 재렌더링·조작·캡처한 보고서를 만들고, 활성 review ID와 issue별 관측·재검증 기준을 `resolve-issue`로 확인한다. 디자인 문제 해소에는 실제 캡처가 필수다. policy/requirements 문제는 새 명세 내용 검토와 영향 디자인 재검토를 분리한다. OPEN MAJOR/BLOCKER가 남으면 디자인 DONE과 개발 인계를 거부한다. 자동 스케줄러·자동 시각 판정기는 아니다.

## 검증 공식 원본·갱신

제품 시안과 현재 갤러리에는 하네스 검증 상태를 표시하지 않는다. 공식 결과는 기존 task.reviews/design_status.checks의 불변 보고서·대상 출력 hash·캡처다. 새 P/D 제출 시 같은 registry의 validation_status overlay로 영향을 받는 과거 기준 검증을 RECHECK_REQUIRED로 표시한다. 이전 artifacts/reviews 자체는 수정하지 않는다. CR 영향 목록을 함께 기록하며 자동 의미 영향 분석을 주장하지 않는다. 새 기준은 NOT_RUN부터 시작하고 검토 통과 후 CURRENT가 된다. 영향 없는 실제 bytes·동작은 동등성 근거와 이전 검토에 연결할 수 있지만 새로 실행했다고 표현하지 않는다.

## 앱·웹 타깃

기획은 REQ별 app/web 적용, 공통 의미와 플랫폼 차이, 웹 모바일/데스크톱 범위를 명시한다. 실제 제품의 OS/브라우저·기술 지원 범위 UNKNOWN은 시험 디자인 범위와 구분한다. setup/rebase의 design_targets와 제출 target_artifacts에 타깃별 실제 HTML·screen·REQ를 연결한다. 공통 토큰·컴포넌트 의미/상태는 공유하되 앱 터치·내비게이션·스크롤과 웹 키보드/포커스·반응형 분할 배치를 구분한다. 같은 D snapshot에 모든 타깃 자원을 보관한다.

구조·동작·시각 보고서의 target_results에는 각 타깃 결과·REQ/화면/상태/행동 coverage를 기록하고 시각 보고서는 타깃별 캡처도 필요하다. app만 검토한 보고서로 전체 PASS를 접수할 수 없다. 앱 HTML 브라우저 시뮬레이션과 실제 네이티브 입력·키보드·뒤로가기·접근성은 다른 검증이며 후자는 실행 전 NOT_RUN이다. 디자인에 web을 포함해도 KMP 웹 빌드 타깃·제품 구현 결정을 추가하지 않는다.

## 실제 개발 입력 확인

실제 구현 작업의 배정에는 [프로젝트 설정·단계 계약](project-settings.md)을 추가한다. 설정과 문서도 기존 입력 snapshot/receipt에 포함하고 stage_contract를 역할 컨텍스트에 전달한다. 기존 입력 해석 예제의 승인본은 소급 변경하지 않는다. configure-stage는 명시적 작업 설정이며 제품 기술 선택이나 실제 API/DB 실행을 대신하지 않는다.

실제 순차 시험과 타깃별 근거는 [연결 시험 보고](examples/role-execution/connection-report.md)를 참조한다. 검토자는 상위 Codex이며 디자인 에이전트의 직접 시각 판정으로 기록하지 않는다. 검토 대기 checkpoint에 문제를 반환할 때 기존 활성 작업 ID·입력 스냅샷·시도 상한을 유지하고, 재개 컨텍스트에 새 반환 사항을 전달한다. 종료된 실패를 다시 활성화하거나 시도 상한을 늘리지 않는다.

development 진입점은 `roles.py` 및 선택 설치의 cli에 연결한다. handoff는 D의 자원뿐 아니라 기준 P의 실제 snapshot과 공식 검토 보고서를 전달한다. 승인 P/D가 맞지 않거나 자원이 누락되거나 차단 issue/재검증 필요 상태면 실행을 거부한다. READY는 등록 상태이고 실행 이력이 아니다. 실제 프로세스의 input_receipt를 전체 원본 path/SHA·정확한 P/D·AC·해석과 대조해 CONFIRMED_BY_AGENT를 남긴다. 상위 검토자가 구현 위치·책임·계획을 읽고 통과시켜야 INTERPRETATION_REVIEWED다. 해시 확인은 의미 해석의 자동 증명이 아니다.

입력 누락/충돌은 waiting의 returns(kind/screen/ui_state/observed/expected/severity/recheck)로 소유 역할에 issue를 반환하고 현재 response를 관측 근거로 snapshot한다. 질문이 필요하면 기존 선택·대기 절차를 따른다. 이 개발 모드는 KMP/Clean Architecture 계획만 허용하며 .kt/.kts 작성·앱 빌드·제품 기능 완료를 처리하지 않는다.
