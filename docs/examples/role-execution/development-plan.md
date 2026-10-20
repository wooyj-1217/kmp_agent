# 메모·즐겨찾기 개발 입력 해석·구현 계획

- TASK-STAR-DEV / agent_run_id f9325fd6-714e-4ad2-b004-99a3c902aa98.
- 범위: CR-002/CR-003 합성 예제의 입력 해석·계획만. 실제 제품 선정·앱 구현·웹 기술 채택·빌드·플랫폼 검증은 수행하지 않았다.
- 적용 기준: APPROVED P-004 → APPROVED D-004, CR-003 및 그 안에 보존된 CR-002 정책.
- 기획 원본: requirements.md SHA-256 e2441a3416533e7e4e29fe99f39d708ac6d4670d11854870923e8e9a8d585fe1.
- 디자인 원본: design.md SHA-256 2380c2050715eb83ed56caadbbce19ccd543ebc7e2d10557f8bcc7d15a527206.
- 공식 검토: evidence/star/d004-structure.json(f307d520f208a144a88a07f4b32aee5b486bc0442c977842e53c5e91c58a44df), d004-interaction.json(3eed53bbb412c7aa3d6c0fbd2947964d32aeca4ac145900262b455e3aaf36bcc), d004-visual.json(7e9d44b4aa1eb5301af38dbfc473ddbc537e93e81f59846b443e45eeb093db49). 모두 P-004/D-004/CR-003 및 세 타깃 PASS를 기록한다. 이는 제공된 검토 결과의 열람이며 이번 개발 프로세스가 브라우저를 실행했다는 뜻이 아니다.
- 원본 문서의 제출 당시 NOT_RUN·D 번호 UNKNOWN은 역사적 작성 상태다. 현재 인계 버전은 패킷의 승인 레지스트리와 위 공식 검토로 고정한다. 불변 문서를 수정하지 않는다.
- 입력 Git b802d18b068d4a213946a0c7f3b5dee77b6c6621은 신규 제품 코드 커밋이 아니다. 합성 예제의 콘텐츠 snapshot 예외만 적용한다.

## 입력 확인·해석

input_receipt에 열거한 모든 동결 입력을 읽었다. 요구사항·두 CR 요청·아키텍처·활성 및 과거 HTML·토큰·공통/타깃 CSS·두 JS·컴포넌트·디자인 규칙·공식 검토 세 보고서를 포함한다. 과거 비교안과 합성 결함 후보는 보존 자료이며 현재 제품 동작의 기준으로 사용하지 않는다.

현재 활성 진입은 index.html의 app-favorites.html/web-favorites.html이다. 두 화면은 tokens.css와 favorites-cr003.css, favorites-cr003.js 및 favorites-return.js를 공유하며 표현은 app-cr003.css/web-cr003.css로 나눈다. 추가 JS는 초기화/빈 목록의 이전 live 안내만 비운다. 합성 결함 후보의 토글 숨김 CSS는 이식하지 않는다.

즐겨찾기는 메모 ID별 기본 false이며 목록/편집에서 즉시 반전한다. true 우선, 원래 생성 순서, ID 오름차순으로 정렬한다. 해제는 false 그룹의 원래 위치로 복귀한다. 같은 페이지 내 목록/편집은 같은 상태를 사용한다. 서로 다른 앱/웹 HTML 사이 동기화·새로고침 영속성·실제 API는 요구하지 않는다. 본문 다섯 상태와 즐겨찾기 양 상태는 독립이다.

실제 앱 .kt/.kts 모듈은 제공 제약상 없다. 아래 경로·클래스는 모두 새로 만들 위치의 계획이며 존재하는 코드가 아니다. KMP/Clean Architecture는 이 계획 연습에만 적용한다. 웹 기술·KMP 웹 타깃·UI 공유 여부·라이브러리·DI 버전은 UNKNOWN이다.

## 요구사항별 구현 위치·검증

아래 테스트는 모두 계획이며 현재 NOT_RUN이다. AC-001~004와 F01~F08/T01~T03은 각각 EX-FEAT-001-AC-001~004 및 EX-FEAT-001-AC-F01~F08/T01~T03을 뜻한다.

| REQ·AC | 의미·정책 해석 | 계획 위치·계층·책임 | 공통·플랫폼 경계 | 검증 계획 |
| --- | --- | --- | --- | --- |
| REQ-001 / ROLE-P1-AC-006 | 합성 예제, 제품 승인 아님 | development-plan.md 및 향후 제품 준비 문서 | 하네스 기록과 제품 모듈 분리 | 범위·snapshot·제품 완료 주장 여부를 문서 검토 |
| REQ-002 / AC-001,002 | 원문 입력, 요청 본문 복사, 중복 저장 차단, 정확한 성공 안내 | domain-client의 SaveDraft 계약·가상 요청 규칙, presentation-client의 MemoEditorState·EditorScreen 계획 | 상태 의미 공유, 입력·결과 포커스는 UI/플랫폼 책임 | 원문/개행 보존, EDITING→SAVING→SAVED, 중복 요청 0회 추가, 성공 첫 문구와 기존 후속 안내 일치 |
| REQ-003 / AC-003 | 실패 요청 본문 보존·재시도 | domain-client 가상 결과 계약, presentation-client 오류 상태, data-client 가상 응답 구현 계획 | 실패가 즐겨찾기를 덮어쓰지 않음 | 실패→ERROR→재시도→SAVING→결과 및 본문 불변 검사 |
| REQ-004 / AC-004 | 빈/공백 저장·길이·실제 저장·이탈·동시 편집 UNKNOWN | 제품 정책 결정 후 domain-client 규칙 계획 | 현재 샘플 이동 가드는 INFERRED이며 제품 정책으로 확정하지 않음 | 해당 제품 분기는 결정 전 차단. UNKNOWN을 PASS/N/A로 삭제하지 않음 |
| REQ-005 / ROLE-P1-AC-005 | 세 타깃별 상태·긴 콘텐츠·입력·시각 증거 | presentation-client 계획 UI와 향후 웹 UI의 별도 검증 계획 | 앱 HTML 증거와 Android/iOS 실기기 증거 분리 | 각 크기 목록 상태·본문5×즐겨찾기2, 긴 본문/오류, 확대·스크롤·포커스·잘림 검증 |
| REQ-006 / ROLE-P1-AC-006 | 기존 합성 A와 불변 P/D 보존 | 개발 인계 명세·검증 manifest 계획 | 제품 코드 커밋과 입력 커밋 분리 | 정확 P→D→출력 커밋→AC 연결, 과거 artifacts 보존 확인 |
| REQ-FAV-001 / F01 | 기본 false·해당 ID만 즉시 반전 | domain/commonMain의 Memo·ToggleFavorite 순수 규칙, domain-client의 세션 계약 계획 | 업무 규칙은 공통, UI 이벤트는 플랫폼 | 모든 ID 초기 false, 1회 반전·2회 복귀·다른 ID 불변 |
| REQ-FAV-002 / F02 | 아이콘·텍스트·접근성 상태 일치, 열기와 분리 | presentation-client/commonMain의 FavoriteControl·MemoRow 계획 | Compose semantics와 웹 aria-pressed는 각 UI 어댑터 책임 | 클릭/Enter/Space 1회당 반전1회, 열기 미발생, 이름·상태·포커스 확인 |
| REQ-FAV-003 / F03 | true→생성순서→ID, 해제 복귀 | domain/commonMain의 FavoriteOrdering 계획 | 공통 순수 비교 규칙, UI는 결과 표시 | 02선택:02,01,03→03선택:02,03,01→02해제:03,01,02→모두해제:01,02,03; 동률 ID·모두 선택 검사 |
| REQ-FAV-004 / F04 | 동일 ID 값 유지·페이지 메모리 수명 | domain-client의 MemoSessionRepository 계약, data-client의 InMemoryMemoSessionRepository, presentation-client 선택 ID 상태 계획 | 목록/편집이 같은 인스턴스 사용. 별도 문서·재시작 동기화 없음 | 미수정/비대기 왕복·패널 전환·재진입 시 값 유지, 열기가 값을 변경하지 않음 |
| REQ-FAV-005 / F05 | 샘플3개·빈 목록·초기화 | data-client 시험 seed, presentation-client 빈 상태·선택/안내 초기화 계획 | 시험 조작은 제품 UI와 분리 | 빈 목록 행/버튼0·오래된 편집 제거·안내 없음, 초기화3개 false·미선택 |
| REQ-FAV-006 / F06 | 공유 토큰·컴포넌트·명시적 진입/DOM 계약 | presentation-client의 디자인 토큰 대응 계획; 향후 웹 구현 위치 UNKNOWN | CSS를 네이티브 코드로 간주하지 않음. 웹 DOM 식별자와 앱 semantics 구분 | 색상·16px·8/16/24px·44px·12px 대응 검토, 웹 진입·자원·DOM·금지 문구 확인 |
| REQ-FAV-007 / F08 | 정확한 승인 입력을 읽고 계획만 제출 | 본 문서·input_receipt | 계획 제출과 의미 검토·제품 구현 완료 분리 | 전체 입력 path/SHA·P/D·AC·REQ별 책임/검증 계획을 상위 검토자가 확인 |
| REQ-002,003,FAV-004 / F07 | 저장 전환이 즐겨찾기를 초기화/롤백하지 않음 | domain-client 상태 전이와 presentation-client 상태 결합 계획 | 본문 요청 snapshot과 favorite 별도 필드 | 본문5상태×양 값에서 토글·성공·실패·재시도 후 최신 값 유지 |
| REQ-TGT-001 / T01 | 앱·웹 모바일 단일 화면, 웹 데스크톱 분할 | presentation-client 앱 목록/편집 계획; 웹 기술 결정 후 전용 presentation 계획 | 웹을 Compose/KMP로 자동 채택하지 않음 | app390×844, web390×844, web1280×900 배치별 검증 |
| REQ-TGT-002 / T02 | 타깃별 입력·포커스·내비게이션·스크롤 | UI의 선택 ID/복귀 위치 상태 및 플랫폼 어댑터 계획 | Android/iOS 시스템 뒤로가기·키보드·접근성은 플랫폼 담당; 웹 Tab/Enter/Space·패널 스크롤은 웹 담당 | 동일 ID 토글 포커스 복구, 모바일 복귀 위치, 데스크톱 목록 접근/편집 유지, 899/900 전환 검사 |
| REQ-TGT-003 / T03 | 타깃별 증거·지원 UNKNOWN·네이티브 경계 | 향후 검증 manifest·타깃별 보고서 계획 | 일부 타깃 PASS로 전체 완료하지 않음 | 출력 커밋·P/D·AC·환경·재현·기대/실제·캡처 연결, 누락/FAIL/NOT_RUN 차단 |

## 의존성·소유권

공유 담당은 domain의 순수 Memo/정렬/반전과 domain-client의 클라이언트 계약을 소유할 계획이다. data-client는 세션 메모리 구현, presentation-client는 UI 상태·화면·컴포넌트를 소유한다. Android 담당은 androidApp 진입·DI·시스템 통합, iOS 담당은 iosApp 진입·DI·시스템 통합을 소유할 계획이다. 실제 채택 플랫폼과 담당자 신원·작업/PR은 UNKNOWN이다. 공유 변경 시 선택된 양 플랫폼 및 웹 공유 여부를 확인하고 영향 AC를 재검증한다.

presentation-client와 data-client는 domain-client에 의존하고 domain-client는 domain에 의존한다. Domain은 DTO/UI/HTTP/DB를 참조하지 않는다. API DTO를 Domain 계약에 노출하지 않는다. model은 향후 API DTO/오류 코드 위치이며 이번에는 API가 없어 새 DTO를 설계하지 않는다. 향후 DTO 변환은 data-client 또는 서버 입출력/데이터 경계에 둔다. DI는 androidApp/iosApp 등 진입점에서 연결하며 presentation이 data 구현체를 직접 조립하지 않는다. DI 도구·버전은 미정이다.

서버 domain-server/data-server/presentation-server/server는 참조 구조의 계획 모듈이다. 이번 페이지 메모리·가상 응답 예제에서 서버/API 구현은 N/A다. 실제 저장 채택 시 별도 계약·담당·버전·재검증 범위를 먼저 정의한다. 서버 domain과 클라이언트 domain은 서로 참조하지 않는다.

## 검토·반환·제한

제공된 공식 D-004 보고서는 세 타깃 PASS와 ISSUE-002/003/004 해결 근거를 기록한다. ISSUE-004는 합성 결함이며 자연 결함으로 집계하지 않는다. 이번 에이전트는 이슈를 해결 처리하거나 캡처를 직접 관측했다고 주장하지 않는다. 기존 D-003 저장/실패/재시도 근거 재사용은 보고서가 명시한 동일 JS bytes와 제한 안에서만 해석한다. 보고서의 광범위 REQ coverage가 UNKNOWN 제품 정책이나 개발 F08의 완료를 증명하지 않는다.

필수 입력의 현재 해석을 막는 누락·충돌은 발견하지 않았다. 과거 문서의 검토 전 상태는 공식 후속 검토와 구분 가능하므로 반환하지 않는다. 향후 정책 누락·충돌은 planning에, 규격/토큰/상태/포커스 충돌은 design에 관측·기대·영향 AC·재검증 기준을 붙여 반환한다. 구현 오류는 development가 수정한다.

Q-001~006, 실제 OS/브라우저/접근성 지원, 웹 기술/공유 범위, 저장/API/라이브러리/DI 버전, 제품 커밋·외부 PR은 UNKNOWN이다. 이번 계획을 차단하지 않으나 해당 제품 구현 단계 전에 담당 기획·디자인·개발이 결정해야 한다. 원본 사용자 메시지 ID도 UNKNOWN이며 파일 해시로 대체하지 않는다.

## 다음 작업·인계

1. 상위 검토자가 TASK-STAR-DEV-C1/C2와 F08에 대해 receipt 및 이 계획의 의미를 검토한다. READY·프로세스 실행·읽기 확인·INTERPRETATION_REVIEWED를 구분한다. 본 제출은 검토 요청이며 스스로 INTERPRETATION_REVIEWED/DONE을 선언하지 않는다.
2. 실제 제품 진행이 요청되면 기획이 제품·지원 플랫폼·UNKNOWN 정책을 결정하고 개발이 웹 기술·공유 범위·소유 모듈·환경·계약/DI 버전을 준비한다. 현재 workflow.next_tasks는 빈 배열이며 새 등록 작업이나 PR이 존재한다고 주장하지 않는다.
3. 별도 승인된 후속에서만 모듈 생성·구현·빌드·플랫폼/서버 연동을 수행하고 새 제품 코드 커밋을 고정한다. 검증 역할에 같은 P/D·AC·코드 커밋과 자체 검증 증거를 인계한다.

현재 실제 앱 구현, KMP/웹 빌드, Android/iOS 실행, 네이티브 접근성/뒤로가기, 서버 연동·제품 검증은 모두 NOT_RUN이다. 별도 브라우저 재검증도 NOT_RUN이다. 회고상 입력 해석에서 확인한 점은 공식 검토와 제출 시점 문서 상태를 분리해야 한다는 것이다. 구현 품질·제품 효과는 관측하지 않았다.
