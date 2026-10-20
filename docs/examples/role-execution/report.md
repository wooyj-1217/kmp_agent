# 기획·디자인 독립 실행·변경 시험 결과

2026-10-19. HARNESS_BUILD 메모 예제이며 실제 제품·MVP·정책·사용자 디자인 승인이 아니다. 실행 run_id는 `3714570e-4ad2-40bb-9719-13fca11c8ed9`, 구축 작업은 TASK-ROLE-BUILD다.

## 기존 구현과 보완

| 기존 기반 | 이번 최소 보완 |
| --- | --- |
| Tasks YAML·의존성·시도 상한·agent_run_id | 별도 planning/design 프로세스·동결 입력 패킷, 명시적 순차 진입점 |
| 불변 artifact snapshot·검토·인계 | 기존 YAML 안에 P/D/CR·승인/대체·개발 인계 체인, 기준본 복원 |
| 중단/재개 근거 조회 | 활성 역할 checkpoint·BLOCKED·결정 snapshot·같은 실행 ID 재개, DONE 건너뛰기 |
| 시각 검토 NOT_RUN 저장·완료 거부 | 구조·동작·시각의 별도 근거 접수, 정확한 제출 hash·캡처 snapshot 연결·필수 검증 차단 |
| 원본 sync·bind_usage | 별도 Codex 프로세스 native session/response의 종료 수집·정확한 사용량 귀속 |

입출력·책임·도구·실제 파일 규격·번호·보관·갱신의 기준은 [실행 계약](../../role-execution.md)이다. 기존 규칙을 별도 상태 DB로 복제하지 않았다.

## 실제 실행 결과

이 예제의 기획·디자인 생성은 실제 `codex exec` 별도 프로세스다. `role_example_worker.py`는 자동 테스트의 결정적 fixture이며 이 예제의 모델 생성으로 대신하지 않았다. 역할별 이전 대화는 전달하지 않고 필요한 원본·선택·기준본만 전달했다. 검토는 수행 Codex가 별도로 실행했으며 독립 검토 모델 자동 호출을 주장하지 않는다.

| 단계 | 작업 | 결과·정확한 인계 |
| --- | --- | --- |
| 최초 기획 생성·내용 검토 | TASK-ROLE-P1 | DONE / P-001 → 디자인 입력 snapshot |
| 대표 A/B·실제 토큰·컴포넌트 | TASK-ROLE-D1 | 실제 파일 생성 후 선택 대기 checkpoint |
| 합성 A 선택·재개·전체 화면 | TASK-ROLE-D1 | 같은 활성 실행 ID로 재개, 완료 비교/토큰 유지 |
| 실제 브라우저 검토·인계 | TASK-ROLE-D1 → TASK-ROLE-DEV1 | DONE / D-001 → P-001. 개발 작업은 인계 수신 READY, 구현 NOT_RUN |
| 명시적 변경·기획 재실행 | CR-001 / TASK-ROLE-P2 | DONE / P-002. 기존 REQ/POL/AC·미결정 유지 |
| 영향 디자인 재실행·재검토 | TASK-ROLE-D2 | DONE / D-002 → P-002 / CR-001 |
| 새 개발 인계 | TASK-ROLE-DEV2 | 정확한 D-002/P-002/CR-001 수신 READY. 실제 개발 NOT_RUN |

P-001/D-001은 SUPERSEDED, P-002/D-002는 APPROVED다. 번호·상태·before/after·실행·검토·인계의 원본은 `.harness/tasks/tasks.yaml`이다. Markdown은 이 시험의 결과 요약이며 상태 원본을 대체하지 않는다.

## 실제 산출물

- [requirements.md](requirements.md): 목표·사용자 가설·MVP/제외, REQ/POL/AC, 흐름·화면별 기능/행동/예외 표, 근거 분류·미결정/차단·CR 영향.
- [design.md](design.md): 기준 P·화면/상태/행동/컴포넌트·토큰·선택·인계 규격. 생성 시 검증 NOT_RUN 선언은 보존하며 실제 검토 결과는 기존 검토 기록에 연결한다.
- [prototype/index.html](prototype/index.html): 현재 시안·기존 A/B·이전 최종 화면·현재/이전 컴포넌트의 실행 진입점.
- [tokens.css](prototype/tokens.css), [components-cr001.html](prototype/components-cr001.html), [system.md](prototype/system.md): 실제 공유 변수·상태 예제·최소 사용 규칙. 사용하지 않는 제품 라이브러리는 만들지 않았다.
- [합성 선택](synthetic-selection.md), [명시적 CR](change-request.md), evidence/의 실제 JPG 28개 및 구조/동작/시각 JSON 보고서.

## 검증·보존

첫 디자인은 SCREEN-001의 5상태×두 크기(390×844/1280×900) 10조합, 긴 본문 1680자×4상태×두 크기 8조합을 관측·캡처했다. 컴포넌트 갤러리와 함께 19개 최종 캡처를 실제 열어 잘림·겹침·가독성·위계·일관성·스크롤·버튼 접근을 검토했다. 실제 입력·Enter 저장·실패 본문 유지·Space 재시도·성공·Tab 포커스·disabled·요청 횟수를 두 크기에서 확인했다. 긴 본문도 실제 실패·재시도로 1680자가 보존됨을 확인했다.

CR 이후에는 새 성공 문구·기존 후속 안내·상단 번역·새 갤러리의 영향 조합만 두 크기에서 실제 재실행하고 6개 캡처를 검토했다. 주석 metadata를 제외하면 이전 화면에서 지정된 문구·상단 번역만 치환한 결과가 새 HTML 전체와 정확히 같음을 확인했다. 비영향 동작을 새로 실행했다고 주장하지 않으며 이전 검토와 동등성 근거를 연결했다.

| 근거 | 첫 기준 | CR 이후 |
| --- | --- | --- |
| 기획 내용 | [planning-r1](evidence/planning-r1.md) | [planning-r2](evidence/planning-r2.md) |
| 구조·실제 토큰·의존 파일 | [structure-r1](evidence/structure-r1.json) | [structure-r2](evidence/structure-r2.json) |
| 실제 동작 | [interaction-r1](evidence/interaction-r1.json) | [interaction-r2](evidence/interaction-r2.json) |
| 실제 캡처 시각 검토 | [visual-r1](evidence/visual-r1.json) | [visual-r2](evidence/visual-r2.json) |

D-002는 토큰·기존 두 갤러리·대표 A/B·이전 최종 화면 등 기존 파일 6개를 바이트 그대로 보존했다. 새 화면/갤러리 2개를 추가하고 현재 design/system/index 참조 3개를 갱신했다. 이전 제출본의 모든 파일은 불변 snapshot으로 남으며 P-001·D-001·D-002 복원을 확인했다. 검토한 캡처도 기존 artifact snapshot에 연결했다. 다른 내용으로 바꾼 뒤 옛 내용을 복원하는 경우에는 새 번호를 사용하며, 직전과 동일한 내용을 다시 제출하는 경우에는 번호를 늘리지 않는 회귀 시험을 통과했다.

자동 테스트는 전체 80개 PASS 후 최종 컨텍스트·작업본 편집 보호를 포함한 관련 11개를 다시 실행해 모두 PASS했다. 검증 명령은 `rtk proxy python3 -m unittest discover -s harness -p 'test_*.py'`와 `-p test_roles.py`다. 미실행/오래된 검토의 완료 거부, 입력 P 불일치, 다른 역할 수정, 누락 자원·외부 의존·정의 없는 CSS 변수, 실패 상한·timeout, 선택 대기/재개, 버전 중복/역행 방지, 실행 중 사용자 편집 보존을 검사했다. `git diff --check`도 PASS다.

## 한계·남은 작업

- 실제 제품 선정·사용자 조사·제품 정책 승인·실제 저장·제품 개발/통합 검증은 NOT_RUN/UNKNOWN이다. 합성 A 선택은 실제 사용자 승인으로 취급하지 않는다.
- 브라우저 관측·캡처 판단은 수행 Codex가 실행했다. 자동 브라우저 실행기·자동 시각 품질 판정기는 없다. 200% 확대는 추가 검토 제안으로 NOT_RUN이며 이 시험의 필수 AC에 포함하지 않았다. 생성 명세 표의 일부 혼용 표기는 비차단 문서 다듬기 항목으로 남긴다.
- 버전 registry·불변 snapshot·정확한 사용량 기록은 기존 `.harness/`의 로컬 Git 제외 자료다. 현재 산출물·선별 검토 근거는 저장소에 남지만 로컬 전체 실행 이력이 다른 clone에 자동 복제되지는 않는다. 실행 전부터 더럽혀진 HEAD를 산출물 승인 커밋이라고 표현하지 않는다.
- 설치된 다른 프로젝트에서의 실제 모델 실행·원격 배포는 NOT_RUN이다. 선택 버전의 설치 진입점은 연결했으며 개발 원본 변경을 자동 전파하지 않는다.
- 비용·현재 대화/검토의 전체 사용량은 UNKNOWN이다. 관측 native 응답의 알려진 소계만 기존 report로 조회한다. 마지막 실제 산출물 추가 요청은 원본 메시지/턴 ID를 확인해 pending 선언했으며 원문 수집·연결은 기존 종료 훅 대기다. 원문을 자유문 이벤트로 대신하지 않았다.
- 외부 서비스 연결·상시 감시·병렬 실행·자동 변경 감지는 이번 범위에서 제외했다. 변경은 명시적 CR로 재실행했다.

실행 권한 제한과 결과 경로 표기 차이는 실패·재시도 기록에 남겼다. 결과를 재생성하지 않고 복구한 사건은 [RETRO-H009](../../retrospective.md#retro-h009--독립-역할-결과-경로-계약의-표기-차이)에 연결한다. 다음 대상은 개발 인계 수신 작업 TASK-ROLE-DEV2이며 이 예제로 실제 제품 개발을 시작하지 않는다.
