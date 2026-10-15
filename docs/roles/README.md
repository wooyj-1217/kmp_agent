# 역할 계약

역할 문서는 지침이다. 독립 역할 자동 호출·외부 도구 연결·전체 예산 집행은 **PLANNED**다.
[최소 작업 관리](../task-management.md)의 current_agent/local_check 실행 이력, YAML 상태·의존성·검토·인계·시도 상한은 구현돼 있다. 같은 세션 역할 전환은 독립 에이전트 실행이 아니다.
제품 모듈과 역할은 별개다. 제품별 지침을 입력으로 받고 [Ktor/KMP 참조](../product-architecture.md)는 해당 스택 선택 시 적용한다.

| 역할 | 계약 | 주 산출물 |
| --- | --- | --- |
| 오케스트레이터 | [orchestrator](orchestrator.md) | 작업·인계·완료 권고 |
| 기획 | [planning](planning.md) | 문제·범위·정책·시나리오·수용 기준 |
| 디자인 | [design](design.md) | 디자인 명세·필수 HTML/CSS 시안·별도 시각 검토 근거 |
| 개발 | [development](development.md) | 선택된 백엔드·Android·iOS·웹 담당 범위별 구현·계약·커밋·PR·자체 검증 |
| 검증 | [verification](verification.md) | PASS / FAIL / NOT_RUN과 증거 |
| 개선 | [improvement](improvement.md) | 재작업·하네스 개선 평가 |

기능별 [최소 템플릿](../templates/README.md)을 사용한다. 기획·디자인 도구와 요금제는 미결정이며 특정 서비스는 필수가 아니다.
현재 역할 문서와 해당 제품·기능의 입력만 선택해 읽는다. 다른 역할의 상세 기준은 인계·검토에 필요한 절만 참조한다. 과거 예제·시험·로그·스냅샷은 일반 제품 작업의 필수 입력이 아니다.

## 공통 인계 규칙

입출력은 feature_id·task_id·run_id·agent_run_id와 고유 수용 기준 ID를 연결한다.
입력에는 목표·범위·제약·의존 작업·명세와 산출물 버전을, 출력에는 산출물·버전·근거·검증·남은 가정·차단 이유·다음 역할을 포함한다.
역할은 자신의 완료 조건을 보고하고 오케스트레이터는 전체 완료를 권고한다. 상태 전환과 재시도 예산은 실행기가 집행한다.
정책 누락·모순은 기획, 디자인 문제는 디자인, 구현 오류는 개발로 반환한다.
종료·인계 시 수행 Codex는 [시행착오 기록 기준](../task-management.md#retrospective)에 따라 해당 저장소의 요약을 갱신한다. 새로운 근거가 없으면 항목을 만들지 않는다.
가정·질문·단계별 차단·변경·인계 버전·증거의 기준은 [운영 설계](../operations.md)다. 작업/PR·담당·브랜치·병렬 실행은 [작업 관리](../task-management.md)를 참조한다.
