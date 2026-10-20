# 제품 기능 산출물 템플릿

공통 하네스 설계·계획은 루트 [design.md](../../design.md)·[plan.md](../../plan.md)에 둔다. 제품별 목표·사용자·MVP·정책·스택·아키텍처·디자인 규칙은 제품 문서에 두고 기능 문서에서 참조한다.
기능별 폴더에는 requirements.md·design.md·prototype/index.html과 필요한 로컬 자원을 둔다. 상세 형식·동작·완료 조건의 기준은 [디자인 역할](../roles/design.md)이다. 템플릿 배포 위치가 실제 제품 폴더를 생성했다는 뜻은 아니다.

- [requirements.md](requirements.md): 기획 산출물의 작성 필드.
- [design.md](design.md): 명세·시안·실제 시각 검토의 기록 필드.
- [project-settings.json](project-settings.json): 제품별 결정 상태와 단계별 입력의 단일 참조. [단계 계약](../project-settings.md)을 적용한다.
- [development-plan.md](development-plan.md): 개발 입력 해석·구현 위치·API/정책/실행·통합 검증 인계.

<...>는 작성할 값이다. 해당 없음은 N/A와 이유를 기록한다.
REQ ID와 기능 내 고유 FEAT-001-AC-001 형식의 수용 기준 ID를 기획→디자인→구현→검증에 유지한다. 삭제한 ID는 재사용하지 않는다. 미구현·미검증 참조를 증거처럼 채우지 않는다.
분류·가정·질문·차단·변경·버전은 [운영 설계](../operations.md), 작업/PR 기록은 [작업 관리](../task-management.md)를 기준으로 사용한다.
YAML이 실행 상태의 원본이고 템플릿의 준비도는 산출물별 상태다. 문서에 중복 변경 이력 표를 두지 않고 Git 이력을 사용한다.
기존 task-handoff 계열의 문서 인계 시험은 완료 상태를 유지하지만 필수 시안·시각 검토·제품 품질 검증 완료로 취급하지 않는다. role-execution 예제의 실제 파일·브라우저 근거도 적용 프로젝트의 제품 선정·품질 검증과 구분한다. 공식 작업본·P/D/CR·기준본 보관은 [역할 실행](../role-execution.md)이 기준이다.
실행 모델·요금제·외부 서비스 선택은 미결정이며 산출물 형식과 구분한다.
