> 이 파일은 2026-10-20 최초 조사 시점의 기록이다. 현재 VERSION 0.2.0 후보의 지원·재실행 근거는 [0.2.0 후보](v0.2.0.md)와 [준비서](candidate-preparation.md)를 우선한다. 아래 과거 관측은 소급 수정하지 않는다.

# 현재 미배포 작업본 지원 현황

- 점검 시작: **2026-10-20 02:50:52 UTC**. 기준 HEAD **`b802d18b068d4a213946a0c7f3b5dee77b6c6621`**, VERSION `0.1.0`. **미커밋 수정·미추적 모듈/문서 포함**이며 v0.1.0 배포판이 아니다. 다음 배포 번호는 지정하지 않았다.
- 이번에는 **테스트·설치·역할 호출을 재실행하지 않고 기존 기록을 확인**했다. 새로 수행한 것은 Git 태그/원격 참조·파일/해시·문서 점검이다. 과거 예제 실행 이후 코드가 보완된 경우 그 예제를 현재 작업본 전체의 재검증으로 표현하지 않는다.
- 조사한 소스·테스트 해시와 근거 범위는 [점검 자료](support-audit.json)에 연결한다. 이 자료는 점검 식별용이며 배포 버전이나 개발 상태 원장이 아니다. 진행 상태는 기존 TASK/run이 원본이다.
- 코드는 현재 작업 경로 링크다. 배포될 때는 해당 태그 내용으로 다시 확정하며 [v0.1.0 기록](v0.1.0.md)은 그대로 보존한다.

| 흐름 | 구현 상태 | 제공 범위와 실행 방식 | 검증 범위 | 사용 전제·차단 요소·제약 | 코드·테스트·실행 근거 |
| --- | --- | --- | --- | --- | --- |
| 1. 원격 버전 설치·초기화·업데이트 | 구현 | 수동 버전 고정 install/init/update/status/recover. 명령 내부 설정 보존·원자적 갱신·복구. 최신 자동 업데이트·다음 역할 실행 없음 | 단위 테스트, 로컬 통합 시험(임시 Git 원본/태그/bare 원격/대상). 실제 원격 설치·설치본 세션은 미실행 | POSIX·Python 3.10+·Git·rtk·원격 접근 권한. 이 작업본은 아직 배포 ref가 없으므로 원격 설치 시 이 추가 기능이 포함되지 않음. 개발 모드로만 별도 선택 가능 | [bootstrap](../../bootstrap.py), [시험](../../harness/test_installation.py), [기존 설치 기록](../../.harness/logs/installation-trial.json) |
| 2. 기획 생성·검토 | 구현 | 수동 작업/입력 설정 후 planning 호출·검토·인계. 명령 내부 독립 Codex 호출·고정 컨텍스트·파일 제출·P 보관. 다음 역할은 수동 호출 | 단위 테스트, 로컬 통합 시험(합성 worker), 공통 예제 실행(실제 Codex P-001~P-004). 실제 적용 프로젝트 실행은 미실행 | Codex 실행 환경·권한·제품 입력·검토자 필요. 자동 질문 결정/승인·역할 연쇄 없음 | [roles](../../harness/roles.py), [시험](../../harness/test_roles.py), [연결 시험](../examples/role-execution/connection-report.md), [기획 검토](../examples/role-execution/evidence/star-planning-review.json) |
| 3. 디자인·시안 생성·검토 | 구현 | 수동 design 호출·선택·브라우저 검토. 명령 내부 시안 제출·자원/토큰 참조 검사·D 보관·타깃별 검증 근거 접수·인계 게이트. 검토자는 상위 Codex이며 브라우저/시각 판단은 별도 수행 | 단위 테스트, 로컬 통합 시험, 공통 예제 실행(실제 앱 HTML 390·웹 390/1280·공통 컴포넌트·렌더링 이미지 검토). 실제 적용 프로젝트 실행은 미실행 | 필요한 타깃·검증 환경을 지정해야 함. 자동 브라우저/시각 판정·자동 역할 연쇄 없음. 앱 HTML은 네이티브 검증 아님 | [roles](../../harness/roles.py), [자원 검사](../../harness/design_assets.py), [역할/연결 시험](../../harness/test_connections.py), [시각 근거](../examples/role-execution/evidence/star/d004-visual.json) |
| 4. 개발 태스크 생성·실행 | 부분 구현 | 수동 작업 등록·단계 설정·현재 Codex의 구현·제출·검토. 명령 내부 고정 P/D/API·대상 Git/코드 상태 자동 연결과 누락 차단. 독립 development 명령은 **입력 해석/계획**만 실행하며 코드 구현 worker가 아님 | 단위 테스트, 로컬 통합 시험(임시 Git 코드 작성·실행·검증·인계), 공통 예제 실행(실제 독립 개발 입력 해석). 하네스 자체 코드 작업의 추적 실행도 확인. 실제 적용 프로젝트 개발 실행은 미실행 | 코드 작업은 대상 Git 루트·HEAD·해당 단계 필수 입력과 검증 근거 필요. 자동 작업 분해/배정·제품 빌드 실행·독립 구현 worker 없음 | [추적 코드](../../harness/development_tracking.py), [착수 게이트 시험](../../harness/test_development_gates.py), [추적 시험](../../harness/test_development_tracking.py), [개발 입력 해석 근거](../examples/role-execution/evidence/star/development-interpretation.json), 로컬 tasks의 TASK-DEV-TRACKING-GATES |
| 5. 실패→담당 반환→수정→재검증 | 부분 구현 | 수동 issue 기록/라우팅·checkpoint/재개·담당 실행·재검토. 명령 내부 담당 소유권·상한·미해결 차단 문제·해당 출력 검증 확인. 무지시 자동 분류/호출/재검증 없음 | 단위 테스트, 로컬 통합 시험, 공통 예제 실행(기획 범위 반환·실제 디자인 MINOR 수정·별도 합성 차단 결함 반환·재렌더링). 실제 제품 구현 결함 전체 루프는 미실행 | issue.kind는 design/requirements/policy. 일반 구현/하네스 결함 자동 분류·라우팅은 없음. checkpoint는 실행 재개이며 코드/index 복구 아님 | [findings](../../harness/findings.py), [연결 시험](../../harness/test_connections.py), [관측·수정/재검토 기록](../examples/role-execution/connection-report.md), [차단 인계 근거](../examples/role-execution/evidence/star/blocked-handoff.json) |
| 6. 변경 자동 감지→개발·재검증 자동 실행 | 부분 구현 | 작업 명령/show/refresh-validation 실행 시 해시·입력 변경을 자동 확인하고 RECHECK_REQUIRED·인계 차단. 명시적 CR/기준 전환·재실행은 수동. 요청한 전체 자동 연쇄는 없음 | 단위 테스트, 로컬 통합 시험(변경 무효화·잘못된 PASS/기준 충돌 차단), 공통 예제 실행(명시적 CR 재실행만). 상시 감지·자동 수정/재검증은 미실행 | 감시·변경 확정·의미상 영향 분석·개발/검증 자동 호출 미구현. 파일 원복만으로 과거 PASS를 현재 유효로 돌리지 않음 | [refresh](../../harness/development_tracking.py), [변경/CR 시험](../../harness/test_development_tracking.py), [명시적 변경 예제](../examples/role-execution/connection-report.md) |
| 7. 피처 버전별 산출물·실행·로그·사용량 | 부분 구현 | 기존 feature/task/run/agent_run과 P/D/CR·API/정책 hash·대상 Git/코드 상태·불변 기준본·검증 유효성 연결. 명령 내부 보관/검사와 Codex 어댑터의 native 응답 사용량 귀속, 명시적 bind_usage. 역할 간 실행 자체는 자동 아님 | 단위 테스트, 로컬 통합 시험, 공통 예제 실행(P/D 보관·입력 receipt·응답 귀속). 실제 적용 프로젝트 실행은 **과거 직접 참조 모드의 훅 원문 수집만** 확인 | 전체 사용량/비용 UNKNOWN·미귀속 가능. 제품 릴리스 자동 생성·전용 전체 버전 집계 없음. 과거 훅 PASS는 현 작업본/태그 설치본 전체 검증 아님 | [deliverables](../../harness/deliverables.py), [logging](../../harness/logging.py), [추적 시험](../../harness/test_development_tracking.py), [버전/사용량 기록](../../.harness/logs/role-trial-report.json), [과거 수집 진단](../../.harness/logs/demo-hook-application.json)의 결과만 참조 |
| 8. 개발 태스크 병렬 실행 | 문서만 있음 | 병렬 허용·의존성·소유 코드·PR 관계의 지침만 있음 | 미실행 | 개발 스케줄러·격리 worktree·파일 소유권 집행·충돌 처리 없음. 상태 잠금이 병렬 개발 보장은 아님 | [작업 계약](../task-management.md#pr-contract), [현재 구현](../../harness/tasks.py) |
| 9. 하네스 결함→수정 Draft PR | 문서만 있음 | 공통 결함 조사·격리 수정·검증·Draft PR까지의 수동 수행/권한 정책. 머지·정식 배포는 사용자 승인. 정책을 수행하는 자동 연쇄 없음 | 미실행(정책 검토만; 실제 전체 PR 흐름 아님) | 자동 분류·안전한 최소 재현·격리 수정·원격 PR 생성/역연결·승인 집행·배포 후 재개 미구현. 원격 권한·출처 확인 필요 | [결함 PR 정책](../harness-defect-pr.md), [구현 상태](../../design.md#구현-상태) |

## 근거의 범위와 현재 사용 판단

공통 예제는 특정 과거 작업본에서 실행한 범위다. 최신 개발 추적 보완 뒤 독립 기획→디자인→제품 구현→통합 검증을 전체 재실행한 근거는 없다. 기존 시험 결과는 [단계 계약 기록](../examples/role-execution/evidence/project-stages-tests.json), [개발 추적 회귀 기록](../../.harness/logs/development-tracking-tests.json), 로컬 tasks/검토 artifact에서 확인했다. 문서·시험 파일만 있는 주장과 실제 실행 기록을 구분했다.

실제 적용의 과거 수집 확인은 신뢰된 새 CLI 세션의 원문 수집·중복 방지 범위다. 제품 원문·경로·개발 상태를 복제하지 않았으며, 해당 환경의 과거 결과를 현재 버전 설치/제품 개발의 성공으로 확대하지 않는다. 원본이 없는 배포 환경에서는 근거 파일 부재를 표시하고 프로젝트가 자체 재검증한다.

지금 시도할 수 있는 범위는 **개발 모드의 선택된 작업본에서 수동 명령·상위 검토로 기획→디자인/브라우저 검토→반환 수정→개발 입력 계획**, 그리고 별도 수동 코드 구현·검증·근거 제출/인계다. 후자는 실제 적용 프로젝트의 제품 흐름으로는 아직 미검증이다. 단계 설정은 API 미정의 UI와 실제 연동/서버/통합 작업을 분리하며 임시 계약을 실제 연동 완료로 인정하지 않는다.

하네스 측 필수 후속은 배포 대상 코드/지침의 버전 확정과 원격 설치본의 새 세션 검증이다. 무지시 자동 실행을 지원한다고 선언하려면 해당 구현 worker·역할 오케스트레이션·감시/재검증 연결이 추가로 필요하다. 병렬·자동 PR은 별도 미구현 범위이며 첫 수동 사용의 선행 요건은 아니다. 개별 제품 스택/목표/준비 상태는 이 기록에서 평가하지 않는다.
