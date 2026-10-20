# 기획·디자인·개발 입력 연결 시험

메모는 하네스 시험 예제이며 실제 제품 기능·지원 플랫폼 확정이 아니다. 실행 `18f82cb5-cda2-4d59-bb11-43a024bcad8f`의 기존 tasks.yaml, 역할 실행·사용량, P/D/CR, 불변 snapshot 체계를 재사용했다. 과거 [P-002/D-002 보고](report.md)는 유지한다.

## 실제 실행한 흐름

1. CR-002 즐겨찾기 요청을 독립 기획 프로세스가 P-003으로 작성했다. 이후 앱·웹 추가 요청 CR-003을 ISSUE-001로 기획에 반환해 같은 작업의 두 번째 실행에서 P-004를 생성했다. 이는 사용자 범위 추가이며 자연 결함으로 세지 않았다.
2. 독립 디자인 프로세스가 P-004 기반 D-003을 생성했다. 공통 `tokens.css`, 상태 의미·컴포넌트를 재사용하고 앱·웹 CSS를 분리했다. 요구사항의 타깃 적용, 공통/차이, 화면·상태 대응과 미정 범위는 [requirements.md](requirements.md), [design.md](design.md), [system.md](prototype/system.md)가 원본이다.
3. 상위 Codex가 실제 Chrome에서 앱 390×844, 웹 390×844·1280×900을 조작·캡처하고 렌더링 이미지를 직접 검토했다. D-003의 동작 시험에는 정렬, Enter/Space, 목록↔편집, 저장→실패→재시도→성공, 저장 중 즐겨찾기, 1,680자 본문·스크롤을 포함했다. 자동 캡처만으로 시각 PASS를 만들지 않았다.
4. 실제 MINOR 문제 ISSUE-002(한국어 갤러리의 일본어 탭 제목), ISSUE-003(빈 목록·초기화 뒤 남은 live 상태 안내)을 기록했다. 자연 차단 결함은 발견하지 못했으므로, **별도 합성 후보**에서 앱 즐겨찾기 버튼을 숨겨 ISSUE-004 MAJOR 반환 경로를 시험했다. 승인된 D-003과 과거 기준본은 유지했다.
5. 합성 생성기 첫 시도는 동적 버튼을 정적 HTML에서만 찾는 시험 코드 오류로 실패했다. 기록·시도 상한 2회를 유지했다. 두 번째 실행 `b9386521-5b5a-4efa-89e4-2fff02121853`의 draft/checkpoint에 실제 브라우저 관측을 반환하고 재개했다. 독립 디자인 프로세스가 D-004를 제출했다. 검토자가 다시 렌더링하고 문제를 해결 처리했다. 디자인 에이전트가 직접 브라우저를 보았다고 주장하지 않는다.
6. ISSUE-004가 열려 있을 때 DONE/승인된 D-003에서도 개발 인계를 거절하는 것을 [차단 시험](evidence/star/blocked-handoff.json)으로 확인했다. probe 작업 TASK-STAR-GATE에는 개발 프로세스를 호출하지 않았다. 실제 개발 입력은 문제 해결 후 TASK-STAR-DEV에 별도로 전달했다.

## 최종 산출물과 검증 원본

현재 인계 체인은 **CR-003 → P-004 → D-004**다. 문서·토큰·컴포넌트·앱/웹 시안은 같은 D-004 불변 기준본에 함께 보관된다. `requirements.md`, `design.md`, `prototype/`는 현재 작업 경로이고 승인 상태·이력·정확한 hash·snapshot은 기존 작업 기록이 원본이다.

| 타깃 | 실행 시안 | 실제 확인 범위 | 캡처 예 |
| --- | --- | --- | --- |
| 앱 HTML | [app-favorites.html](prototype/app-favorites.html) | 390×844, 단일 화면 이동·즐겨찾기·키보드·상태 | [앱 오류+선택](evidence/star/d004-app-ERROR-FAV-ON.jpg) |
| 반응형 웹 모바일 | [web-favorites.html](prototype/web-favorites.html) | 390×844, 목록/편집 전환·포커스·상태 | [웹 모바일](evidence/star/d004-web-mobile-ERROR-FAV-ON.jpg) |
| 반응형 웹 데스크톱 | 동일 웹 파일 | 1280×900, 목록+편집 분할 배치·독립 스크롤·포커스·상태 | [웹 데스크톱](evidence/star/d004-web-desktop-ERROR-FAV-ON.jpg) |
| 공통·타깃 표현 | [components.html](prototype/components.html) | 한국어 제목·앱 터치 행/웹 선택 행·상태 예 | [컴포넌트](evidence/star/d004-gallery.jpg) |

D-004 공식 검증은 [구조](evidence/star/d004-structure.json), [동작](evidence/star/d004-interaction.json), [시각](evidence/star/d004-visual.json)으로 분리했다. 대상 출력의 정확한 hash, REQ→타깃→화면·상태·검증·캡처와 해결한 issue를 연결한다. 제품 시안에 하네스 검증 상태 문구를 넣지 않는다.

D-004에서는 세 타깃의 버튼 가시성·키보드 토글·정렬·화면 이동·초기화/빈 목록 안내, 본문 5상태×즐겨찾기 OFF/ON을 재실행했다. 모바일 웹은 실제 innerWidth 390을 확인한 [별도 재검증](evidence/star/d004-mobile-recheck.json)이 기준이다. 변경되지 않은 공유 JS의 저장·실패·재시도·긴 본문 동작은 D-003 검증을 명시적으로 참조한다. 이를 D-004에서 모두 새로 실행했다고 집계하지 않는다. 검토 이미지에서 잘림·겹침·가독성·위계·일관성을 확인했다.

이전 검증의 현재 유효성은 기존 deliverables의 `validation_status`에서 RECHECK_REQUIRED로 관리한다. 과거 PASS 보고서와 기준본을 소급 수정하지 않는다. 현재 인계는 새 D-004 검증을 사용한다. 자동 변경 감지가 아니라 명시적 CR과 버전 제출로 재실행한 결과다.

## 실제 개발 입력 해석

별도 독립 Codex 프로세스 TASK-STAR-DEV (`f9325fd6-714e-4ad2-b004-99a3c902aa98`)에 P-004/D-004, 토큰·공통 컴포넌트·앱/웹 시안·수용 기준·검증 원본 등 고정 입력 26개를 전달했다. 입력 등록 READY → 실제 프로세스 실행 → CONFIRMED_BY_AGENT → 상위 의미 검토 INTERPRETATION_REVIEWED / DONE까지 실행했다. 원본 문서와 과거 비교·합성 후보의 위계도 구분했다.

[개발 계획](development-plan.md)에 모든 REQ/AC별 제안 모듈·공통/플랫폼 책임·검증 계획과 반환 조건이 있다. 상위 Codex가 문서 전체를 읽고 input_receipt의 26개 path/SHA가 동결 입력과 정확히 일치함을 확인했다. Domain의 DTO/UI/HTTP/DB 의존 금지, data 경계 변환, Android/iOS 진입점 DI, 조건부 서버 범위, 웹 기술 미정과 후속 구현 차단 정책을 확인했다. [입력 해석 검토 근거](evidence/star/development-interpretation.json)가 공식 원본이다. 이는 입력 등록만 한 결과와 다르며 실제 KMP 구현·빌드는 여전히 NOT_RUN이다.

## 하네스 검증

검토 반환·소유 역할 라우팅·재시도/재개·차단 인계·정확한 개발 receipt·일부 타깃 검증 거부·과거 검증 유효성 overlay를 [회귀 시험](../../../harness/test_connections.py)으로 확인했다. 단위 시험의 캡처·worker는 합성이며 위 실제 Codex/Chrome 실행 근거와 구분한다. 전체 87개(149.819초), 연결·역할 집중 17개(35.003초) PASS. `git diff --check` PASS. [시험 기록](evidence/star/harness-tests.json)에 명령·범위·결과를 남겼다.

## 미실행·미결정

- 앱은 HTML/CSS 시뮬레이션이다. 실제 Android/iOS 네이티브 동작, 시스템 뒤로가기·키보드·터치·스크린리더, KMP 앱 구현·빌드·기기 시험은 NOT_RUN.
- 웹은 대표 두 너비의 Chrome 검토다. 전체 브라우저·OS 호환성과 중간 모든 너비 검증은 NOT_RUN. 디자인 대상과 KMP 실제 구현 타깃은 별개이며 웹 빌드 타깃을 추가하지 않았다.
- 저장/API/영속성, 빈 값·길이·미저장 이탈 등의 기존 미정 정책은 임의 확정하지 않았다. 예제 조작·차단은 문서화한 시험 범위다.
- 외부 서비스, 상시 감시, 자동 역할 배정, 병렬 역할 실행은 미실행이다. 다음 인계는 제품·지원 범위와 미정 정책 결정 후 실제 KMP 구현 작업이다.
