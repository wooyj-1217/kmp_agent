# kmp_agent 작업 지침

목표는 [여러 제품에 재사용하는 공통 개발 하네스로 사람의 반복 지시·누락 확인·변경 전달 부담을 줄이는 것](docs/project-goal.md)이다. 아래에서 현재 작업에 필요한 문서·절만 읽고, 모든 링크를 사전 로드하지 않는다.

| 작업 | 기본 읽기 경로 |
| --- | --- |
| 역할 수행 | [역할 목록](docs/roles/README.md) → 현재 역할 문서 + 해당 제품 지침·기능 입력 |
| 공통 판단·완료·버전 | [운영 설계](docs/operations.md)의 관련 절 |
| 작업 배정·상태·PR·인계 | [작업 관리](docs/task-management.md)의 관련 절 |
| 기획·디자인 문서 작성 | 현재 역할 → [해당 템플릿](docs/templates/README.md) |
| 적용 프로젝트의 하네스 결함·개선 PR | [개선 PR 정책](docs/harness-defect-pr.md) → 해당 역할·기존 작업/실행 기록; 이번 요청의 실행 범위 우선 |
| 하네스 설계·계획 변경 | [design.md](design.md) · [plan.md](plan.md)의 관련 절 |
| 로컬 실행·로그 기록 | [로컬 설정 안내](docs/harness-logging.md#local-setup) → [기존 로깅 절차](docs/harness-logging.md#사용-절차) |
| 순차 개발 근거·명령·대기·인계 | [공통 수집 규칙](docs/sequential-evidence.md); 제품 init 설정을 재사용하고 미관측 값은 UNKNOWN |
| 하네스 버전·설치·업데이트 | [설치·init·update](docs/installation.md); 대상 버전은 명시적으로 선택하고 개발 원본에서 자동 전파하지 않음 |
| 중단 후 재개 | [중단·재개](docs/interruption-recovery.md)와 기존 작업의 완료 근거 |

제품 목표·범위·원본·인수 조건·테스트 명령과 감시 대상·변경 확정 조건은 적용 프로젝트가 정한다. 제품 산출물·코드·로그·검증 증거는 해당 프로젝트에 보관하며 하네스 원본으로 자동 전송하지 않는다. 자동 변경 대응의 목표와 현재 구현 상태를 구분한다.
제품 아키텍처는 해당 제품 지침을 읽고, Ktor/KMP를 채택한 경우에만 [참조 구조](docs/product-architecture.md)를 적용한다.
과거 docs/examples/·실험 보고서·로그·스냅샷은 재현·조사·재개에 필요한 경우에만 읽는다. 일반 제품 작업의 필수 입력이 아니다.
종료·인계에는 [회고 판단·기록 기준](docs/task-management.md#retrospective)을 적용한다. 적용 프로젝트 연결·개선 공유는 [작업 관리](docs/task-management.md#demo-feedback), 공통 결함의 격리 수정·Draft PR과 머지/배포 승인 경계는 [개선 PR 정책](docs/harness-defect-pr.md)을 따른다. 정책 허용과 자동 실행 구현을 구분하며 현재 사용자 요청의 작업 범위를 우선한다.
사용자 후속·수정 요청은 [개입 연결 절차](docs/harness-logging.md#request-classification)에 따라 작업·역할 실행과 실제 원본 메시지 ID, 분류·판단 근거를 기록한다. 원문 수집 대기는 pending으로 구분하고 자유문 이벤트로 대신하지 않는다.
원문 수집은 [생명주기 수집 경로](docs/harness-logging.md#생명주기-수집과-보장-범위)를 사용한다. CLI 시작·종료 수집과 Codex 훅의 신뢰·활성화 상태를 구분하고, 분류 실패로 원문을 누락시키지 않는다.

지침은 실행 시스템이 아니다. 최소 구현과 PLANNED의 현황은 [설계의 구현 상태](design.md#구현-상태)를 참조한다.
작업 범위는 현재 사용자 요청을 따른다.
