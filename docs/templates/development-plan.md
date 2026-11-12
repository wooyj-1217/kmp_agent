# <기능> 개발 입력 해석·구현 계획

- 범위: 입력 해석·계획만. 앱 코드·빌드·실제 플랫폼 검증은 NOT_RUN.
- 정확한 기획 P / 디자인 D / CR와 공식 검토 기록: <버전·원본 path/SHA·검토 참조>
- 입력 확인: <requirements/design/tokens/components/prototype/AC/아키텍처 원문 목록과 이해한 내용>
- 적용 지침: [개발 역할](../roles/development.md), [제품 아키텍처](../product-architecture.md)의 KMP 필수 기준과 제품별 세부 기술 지침. 실제 존재하는 코드와 계획 모듈을 구분한다.

## 프로젝트 결정·진행 단계

- 프로젝트 설정 원본·기준 snapshot: <project-settings.json 참조>. [단계 계약](../project-settings.md)의 상태·필수 입력을 사용하고 값을 복제하지 않는다.
- 단계: <ui / client_integration / server_implementation / integration_verification / 입력 해석만>. 임시 계약·목 데이터, 진행 가능한 작업·차단된 작업, 필요한 결정·담당을 연결한다.
- Kotlin Multiplatform 필수 적용과 실제 공유 모듈·소스셋·타깃별 빌드/검증 명령을 확인한다. KMP 미사용 계획은 구현 전에 계약 충돌로 반환한다.
- 실제 구현 타깃·UI 기술·지원 범위, 타깃별 공유/플랫폼 책임·소유 모듈, 서버 없음/기존/신규와 서버·DB 결정을 확인한다. 미정을 확정으로 승격하지 않는다.
- [승인된 개발 제약](../development-constraints.md) 원본 requirement ID·정책 digest·동결 참조: <참조 또는 비 PRODUCT에서 미지정 사유>. DB 엔진/위치/역할, UI 공유·소유 경로, 전체 타깃 진입 파일·명령·소스 규칙은 원본을 참조한다. 변경 제안은 승인과 재검토 전까지 구현하지 않는다.

## 요구사항별 구현 위치·검증
| REQ·수용 기준 | 의미·상태·정책 해석 | 계획 모듈·계층·파일/책임 | 공통·플랫폼 경계 | 검증 계획 |
| --- | --- | --- | --- | --- |
| <ID> | <내용> | <현재 존재/새로 만들 위치 구분> | <내용> | <테스트·기대 결과·환경·현재 NOT_RUN> |

## 의존성과 입력 충돌·반환
Domain 순수성, DTO 변환 경계, DI 진입점, 공통/서버/클라이언트·Android/iOS 책임을 기술 지침과 대조한다. 웹 기술과 실제 저장·라이브러리/DI 버전을 임의 확정하지 않는다. 필수 정보 충돌은 issue에 관측·기대·영향·담당 planning/design을 연결한다. 범위 밖 UNKNOWN은 후속 단계와 담당을 기록한다.

## API·정책·실행·통합 검증 인계

- API 계약 원본·버전·요청/응답/오류·인증·real/temporary/mock·목 데이터 위치와 한계: <참조 또는 해당 없음과 이유>
- 정책 ID별 클라이언트/서버 책임·최종 검증/저장 주체·오류/재시도: <기존 요구사항/API 표 참조>
- 실행 안내 원본: <타깃/서버 명령·작업 디렉터리·순서·환경변수 이름/자리표시자·DB 준비/마이그레이션/실패 복구/격리된 시험 데이터 초기화>. 비밀값은 기록하지 않는다.
- 타깃별 환경·수용 기준·전체 연결(저장→재조회·재시작 유지·실패 경로)·공식 검증 기록: <참조>. 실제/목·native/browser를 구분하고 미실행은 NOT_RUN.
- 승인된 타깃 명령과 제출 work 실행의 native 시작/종료·argv·출력 digest 증거: <공식 기록 참조>. 구조·명령 일치 검사와 독립 QA·제품 e2e 인수 결과를 구분한다.

## 다음 작업
KMP 앱 구현·빌드·플랫폼/서버 연동·제품 결정이 필요한 작업을 별도 후속으로 남긴다. 입력 등록 READY, 프로세스 실행, 에이전트의 읽기 확인, 해석 검토 완료는 다른 상태다. 실행 로그/사용량은 기존 기록을 참조한다.

## 실제 구현 연결 계약

단계 워크플로의 `development_plan` 산출물에는 아래 필드를 담은 **`development-execution` fenced JSON 블록을 정확히 하나** 넣는다. AI가 기획·디자인·프로젝트 설정의 승인 입력에서 작성하고 개발 계획 자체의 독립 검토를 받는다. 원본이 없는 필드는 임의 기본값으로 채우지 않고 waiting/반환한다. 기존 input_interpretation_only 실행은 이 계약을 요구하지 않는다.

| 필드 | 내용 |
| --- | --- |
| schema_version | `1` |
| task_id, title, goal | 새 구현 부모 작업 ID·제목·승인된 목표. 계획/기존 작업 ID 재사용 금지 |
| criteria | 구현 인수 기준 배열: id·description·required(boolean). 적어도 하나 필수 |
| baselines | planning·design·policy 경로, API 필요 시 api 경로. 현재 승인 P/D 출력과 계획의 동결 입력 |
| code_paths | 승인된 수정 소스 경로 배열. 루트 전체·verification/ 제외 |
| api_required, service_version | 명시적 boolean과 실제 서비스/계약 버전. 비해당도 구체적 이유/버전 표기 |
| stage | PRODUCT는 `{ "settings": "승인 설정 경로", "stage": "ui 또는 client_integration 또는 server_implementation" }`. 비 PRODUCT에서 미적용은 null |
| children | task_id·area·title·goal·requirement_ids·acceptance_ids·allowed_paths·dependencies·verification_commands·out_of_scope. 필요한 영역만, 부모 code_paths 안의 소유 범위 |
| architecture | evidence(검토 입력 경로)·modules(영역별 실제 소스 경로)·필요한 ui_owners |
| shared_owners | 공유 빌드/계약 파일별 담당 task ID. 소유자 없음을 추측하지 않음 |
| verification | 승인 검토 입력에 이미 포함된 검증 정의 JSON의 정규 상대 경로. PRODUCT 필수. `schema_version`, `plan_version`, 기준·플랫폼별 checks는 [보호된 검증](../protected-verification.md) 참조 |
| integration_commands | 영역별 검사와 구분한 실제 통합 명령 argv 배열. 모든 명령은 `rtk proxy`로 시작 |
| max_parallel, timeout | 선택적인 운영 한도. 생략 시 기존 위임 기본값 2·600초이며 프로젝트 공유 admission 한도는 그대로 적용 |

`area`는 현재 위임기의 kmp/web/server/android/ios 중 실제 선택 영역이다. 이 목록은 제품 플랫폼 채택 지시가 아니다. 본문의 구현/검증 설명과 JSON이 다르면 승인 전에 바로잡는다. JSON 형식 검사는 승인·명령 안전성·제품 인수 검증을 대신하지 않는다. 검토 후 메인은 같은 계획 task ID의 development 진입점을 호출해 실제 구현으로 이어간다. 실행 계약이나 검토가 없으면 입력 해석 완료를 코드 구현 완료로 승격하지 않는다.

승인된 검증 정의의 필수 테스트·assertion·기준 이미지·검증 명령·제외/CI 설정을 구현 편의로 변경하면 기존 승인과 결과를 재사용하지 않는다. 영향받는 기준을 표시하고 기존 계획/기준 승인 담당에게 반환해 정의·보호 정책을 갱신한 뒤 제출 커밋에서 재실행한다. 새 테스트 파일 추가는 허용하지만 CI/제외 설정 추가는 재승인 대상이다. 구현·QA의 관찰 보고와 공식 PASS 발행을 구분한다.
