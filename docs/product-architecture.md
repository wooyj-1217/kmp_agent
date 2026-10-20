# Ktor/KMP 제품 구조 참조

모듈 이름과 의존성은 확정된 설계 결정이며 구현 상태는 모두 **PLANNED**다.
아래는 기존에 합의한 Ktor 백엔드와 KMP·Compose Multiplatform Android/iOS 제품 구조다. 해당 스택을 채택하는 제품에 적용하며 공통 하네스의 필수 스택이 아니다.
이 참조의 기존 Android/iOS 모듈 표만으로 웹 구조를 결정하지 않는다. 웹 기술·진입 모듈·KMP 로직/UI 공유 여부는 제품별 개발 준비에서 UNKNOWN을 해소해 정의한다.
제품 목표·스택·인수 조건·테스트 명령은 적용 프로젝트가 정한다. 이 참조를 특정 데모 제품의 목표·구현 계획이나 공통 하네스의 필수 스택으로 채택하지 않는다.
제품 모듈은 에이전트 역할이나 실행 하네스 모듈과 구분한다.
이 문서는 기술별 제품 아키텍처 참조다. 실제 제품은 목표·사용자·MVP·정책·채택 스택·아키텍처·디자인 규칙을 제품별 문서에 정의하고 참조 적용 여부를 명시한다.

| 영역 | 모듈 | 책임 |
| --- | --- | --- |
| 공통 | `model` | API DTO·오류 코드 |
| 공통 | `domain` | 업무 모델·순수 규칙 |
| 서버 | `domain-server` | 서버 전용 업무 계약·규칙 |
| 서버 | `data-server` | 서버 데이터 접근 구현 |
| 서버 | `presentation-server` | Ktor HTTP 입출력·업무 호출 |
| 서버 | `server` | 서버 진입점·DI |
| 클라이언트 | `domain-client` | 클라이언트 전용 업무 계약·규칙 |
| 클라이언트 | `data-client` | API·저장소 접근 구현 |
| 클라이언트 | `presentation-client` | Compose Multiplatform UI·상태 |
| 클라이언트 | `androidApp` | Android 진입점·DI |
| 클라이언트 | `iosApp` | iOS 진입점·DI |

## 의존성 규칙

- `presentation-server`와 `data-server`는 `domain-server`를 참조한다.
- `presentation-client`와 `data-client`는 `domain-client`를 참조한다.
- 전용 domain은 공통 `domain`을 참조하며 서로 참조하지 않는다.
- 모든 Domain 계층은 API DTO·UI·HTTP·DB 구현에 의존하지 않는다. `model`의 API DTO를 Domain 계약에 노출하지 않는다.
- DTO·업무 모델 변환은 Domain 밖의 API·데이터 경계에 둔다.
- 진입점에서 DI로 구현체를 연결한다. presentation이 data 구현체를 직접 조립하지 않는다.

라이브러리·DI 도구·버전은 [미결정 사항](open-decisions.md)에 둔다.
KMP 채택 시 공유 모듈별 담당·소유 파일·플랫폼 영향을 제품 지침에 지정한다. API 요청·응답·오류 계약의 내용은 제품 문서에서 관리하고 버전·변경 영향·관련 작업/PR 연결은 [개발 역할](roles/development.md)과 [작업 관리](task-management.md)를 따른다. 공통 개발 지침에 이 모듈 규칙을 복제하지 않는다.
