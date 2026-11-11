# 미배포 변경

기준 배포는 [v0.4.1](v0.4.1.md)이다. 아래 변경은 해당 배포에 포함되지 않았으며 다음 버전 번호·태그·배포 일정은 미확정이다. VERSION과 기존 배포 기록은 변경하지 않는다.

## 예제 분리와 UI 적용 여부

- 제품 예제·앱 시나리오·Ktor fixture·메모 시험 도구와 전용 시험은 [별도 로컬 companion](../examples-separation.md)으로 분리한다. 현재 소스·새 설치물에서 제외하고 기존 파일은 원래 로컬 경로에 보존한다. 과거 Git 이력·기존 태그는 유지하며 일반 full clone의 역사 객체 제외를 보장하지 않는다.
- companion은 명시한 하네스 source/ref로 별도 실행한다. 실제 실행 허가 원문과 합성 fixture의 계보·독립 QA 원칙을 유지하고, 개별 실제 모델 검증 기록과 원문은 로컬에만 보존한다. 새 원격 생성·공개는 포함하지 않는다.
- [UI 비해당 계약](../ui-applicability.md)은 명시적 선언을 현재 요구사항 계보와 연결하고 입력으로 동결한다. CLI 등의 인터페이스 설계·독립 검토는 유지하며 mockup·시각 검증은 NOT_APPLICABLE로 기록한다. 기존 visual_required=False만으로 개발 인계를 허용하지 않는다.

## 개발 추적과 사용량 회귀

- [개발 추적](../development-tracking.md)은 불변 Git 객체만 캐시하고 현재 Git 열거는 한 refresh 안에서만 공유한다. 단계 종료 시 단일 scope도 Git·파일 내용·모드·symlink를 재확인하며 캐시 경로도 deadline을 검사한다. 상태 조회는 명령 전후 refresh를 마친 최종 저장 상태를 반환한다.
- 공통 사용량 회귀는 고정된 비공개 폴더에 의존하던 skip 시험을 명시적 합성 legacy 필수 시험으로 대체한다. 첫 복구·합계 보존·동일 제목 QA 구분·수정 분류·멱등성·입력 원본 불변을 검증하며 실제 모델 실행으로 표시하지 않는다.
- 실제 corpus 검증은 [별도 로컬 companion](../examples-separation.md)의 명시적 경로·해시 manifest로 선택 실행하며 공통 설치 입력에 포함하지 않는다. 원래 private legacy corpus 미제공은 NOT_RUN으로 구분하고, 다른 실제 corpus의 합계 보존이나 선택 회귀 결과를 그 시험 또는 전체 검증의 PASS로 확대하지 않는다.

## KMP 개발 기준

- 적용 제품의 클라이언트 개발에서 Kotlin Multiplatform을 필수로 사용한다. 비 KMP 클라이언트 요구는 구현 전 계약 충돌로 반환하도록 공통 지침·역할 입력·개발자 위임 프롬프트를 맞춘다.
- 타깃 플랫폼·로직/UI 공유 범위·Compose UI 공유·서버 기술은 제품별로 확정한다. 이 변경은 산출물의 KMP 사용을 자동 판별하는 새 게이트를 추가하지 않는다.
- [제품 아키텍처](../product-architecture.md), [개발 역할](../roles/development.md)을 따른다.

## DB 기본값과 기존 제품 보존

- 서버 기본값은 PostgreSQL + Exposed SQL DSL(JDBC) + Flyway, 로컬 기본값은 SQLite + SQLDelight다.
- 신규 제품 첫 개발 전에 기본값 사용/다른 지정을 한 번 확인한다. 개발 중인 제품은 기존 스펙을 따르며 기본값 교체나 반복 질문을 하지 않는다.
- DB 필요 여부·저장 역할을 임의 가정하지 않으며 미응답을 제품별 채택 승인으로 처리하지 않는다. 자동 설정 주입·새 설정 스키마는 추가하지 않는다.
- [DB 기본 스택 확인](../project-settings.md#db-기본-스택-확인)을 따른다.
