# kmp_agent

여러 제품 프로젝트에 설치해 재사용하는 공통 개발 하네스다. 요구사항·디자인의 반복 지시, 구현 누락 확인, 변경 전달에 드는 사람의 부담을 줄이는 것이 목표다. 전체 개발 흐름·자동 변경 대응의 목표, 적용 프로젝트와의 책임 경계, 현재 구현 상태는 [프로젝트 목표](docs/project-goal.md)를 따른다.

[작업 진입 지침](AGENTS.md)에서 현재 역할·작업에 필요한 문서만 선택한다. 실행 환경 설정은 [로컬 설정 안내](docs/harness-logging.md#local-setup)를 따른다.

제품 예제·앱별 시나리오·선택 실제 모델 시험은 [예제 분리 경계](docs/examples-separation.md)에 따라 현재 하네스 소스와 새 설치물에서 제외한다. 필요한 시험은 명시한 하네스 source/ref를 사용하는 별도 로컬 companion에서 실행한다. 과거 Git 이력·기존 릴리스 태그와 로컬 검증 원본은 보존하며 일반 full clone에서 역사 객체까지 제외한다고 보장하지 않는다. 공통 단위 테스트는 제품과 무관한 임시 합성 입력을 생성한다.

[배포 버전별 지원 현황](docs/releases/README.md): 설치한 태그/SHA의 제공 범위·실행 방식·검증 근거와 미배포 작업본을 구분한다.

[하네스 시행착오](docs/retrospective.md): 구축·운영에서 확인한 문제와 개선 결과의 요약.

[버전 고정 설치·init·update](docs/installation.md): 특정 태그/커밋 설치, 프로젝트별 설정·데이터 보존과 명시적 업데이트.
[연결·동작 점검](docs/harness-projects.md): 설치 버전의 훅·로그·재시작 판정과 개발용 원본 참조 점검.

[순차 개발 근거 수집](docs/sequential-evidence.md): 제품별 모듈·명령 초기 설정, 작업/시도·명령·대기·파일 변화·통합 근거와 수집 충족도. 현재 작업본 기능이며 병렬 실행·후보 판정은 포함하지 않는다.

[하네스 결함 개선 PR 정책](docs/harness-defect-pr.md): 적용 프로젝트의 문제 분류·최소 재현·격리 수정·Draft PR, 머지/배포 승인·버전별 재검증과 현재 미구현 범위.

[프로젝트 진행 상황 대시보드](docs/dashboard.md): 실행/전체 이력 분리, 명시 범위·승인 기준·상태별 검토·사용량을 읽기 전용으로 표시하는 미배포 작업본.

[개발 위임](docs/development-delegation.md) · [독립 QA](docs/qa.md) · [요구사항 추적](docs/requirement-lineage.md) · [토큰 기록](docs/token-usage.md) · [공통 PR 운영 규칙](docs/operations.md#pr-submission).

[회귀 시나리오 관리](docs/regression-scenarios.md): 제품별 기준·플랫폼·도구 catalog와 smoke/full/개별 실행. 현재 미배포 작업본이며 공식 완료는 보호 검증 절차를 따른다.
