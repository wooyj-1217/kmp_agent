# kmp_agent 작업 지침

목표는 [공통 하네스를 구축하고 첫 제품으로 검증](docs/project-goal.md)하는 것이다. 아래에서 현재 작업에 필요한 문서·절만 읽고, 모든 링크를 사전 로드하지 않는다.

| 작업 | 기본 읽기 경로 |
| --- | --- |
| 역할 수행 | [역할 목록](docs/roles/README.md) → 현재 역할 문서 + 해당 제품 지침·기능 입력 |
| 공통 판단·완료·버전 | [운영 설계](docs/operations.md)의 관련 절 |
| 작업 배정·상태·PR·인계 | [작업 관리](docs/task-management.md)의 관련 절 |
| 기획·디자인 문서 작성 | 현재 역할 → [해당 템플릿](docs/templates/README.md) |
| 하네스 설계·계획 변경 | [design.md](design.md) · [plan.md](plan.md)의 관련 절 |
| 로컬 실행·로그 기록 | [로컬 설정 안내](docs/harness-logging.md#local-setup) → [기존 로깅 절차](docs/harness-logging.md#사용-절차) |
| 중단 후 재개 | [중단·재개](docs/interruption-recovery.md)와 기존 작업의 완료 근거 |

제품 아키텍처는 해당 제품 지침을 읽고, Ktor/KMP를 채택한 경우에만 [참조 구조](docs/product-architecture.md)를 적용한다.
과거 docs/examples/·실험 보고서·로그·스냅샷은 재현·조사·재개에 필요한 경우에만 읽는다. 일반 제품 작업의 필수 입력이 아니다.
종료·인계에는 [회고 판단·기록 기준](docs/task-management.md#retrospective)을 적용한다. 데모 연결·환류는 [작업 관리](docs/task-management.md#demo-feedback)를 따른다.

지침은 실행 시스템이 아니다. 최소 구현과 PLANNED의 현황은 [설계의 구현 상태](design.md#구현-상태)를 참조한다.
작업 범위는 현재 사용자 요청을 따른다. 이번 정리는 기존 문서·참조만 수정하며 코드·제품·새 자동화·로깅을 추가하지 않는다.
