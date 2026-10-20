# 메모·즐겨찾기 디자인 규칙

## 기준·재사용
P-004 APPROVED, requirements SHA-256 e2441a3416533e7e4e29fe99f39d708ac6d4670d11854870923e8e9a8d585fe1. CR-002/003, TASK-STAR-RETURN 및 design-return-decision.md를 적용한다. 마지막 승인 D-003은 P-004 기준이다. 이번 제출은 새 검토 요청이며 D 번호는 실행기가 결정한다.
동결 입력의 토큰·CSS·JS·화면·갤러리와 checkpoint를 읽어 재사용했다. tokens.css, favorites-cr003.css, app-cr003.css, web-cr003.css, favorites-cr003.js 및 과거 비교 HTML은 변경하지 않는다. 기존 D-003 원본과 checkpoint는 불변 snapshot으로 보존한다. 합성 후보 app-favorites-synthetic-defect.html은 checkpoint 내용을 그대로 보존하며 현재 index에서는 연결하지 않는다.

## 실제 자원·실행 순서
index.html → tokens.css, app-favorites.html, web-favorites.html, components.html.
앱 → tokens.css + favorites-cr003.css + app-cr003.css + favorites-cr003.js + favorites-return.js.
웹 → tokens.css + favorites-cr003.css + web-cr003.css + favorites-cr003.js + favorites-return.js.
갤러리 → tokens.css + favorites-cr003.css. 정적 상태 예제다.
합성 후보 → 기존 세 CSS와 favorites-cr003.js, HTML 내부 토글 숨김 스타일. 과거 후보로만 보관한다.
두 활성 HTML의 defer 스크립트 순서는 기존 JS 다음 추가 JS다. 추가 JS는 기존 reset/emptyList onclick 이후 실행되는 click listener에서 listStatus.textContent만 비운다. 기존 저장·정렬·데이터·포커스 처리는 그대로 유지한다. 동적 자원·CSS url·외부 CDN·폰트·API·storage는 추가하지 않는다. 파일을 로컬 브라우저에서 열며 빌드는 필요 없다.

## 실제 토큰
공유 tokens.css의 CSS 변수를 화면과 갤러리에서 함께 사용한다. --bg #f4f5f7 배경, --surface #fff 표면, --ink #172033 본문, --muted #526074 보조, --accent #244fd3 강조·포커스, --error #a12424 오류. --body 16px 본문, --title-a 28px 제목, --title-b 22px 기존 분할 제목. --s1 8px·--s2 16px·--s3 24px 간격, --control 44px 최소 버튼 높이, --radius 12px 모서리. 시스템 폰트 사용. 테두리 #c6ceda는 기존 panel 값이다. 900px 분기·앱 최대480px·웹 최대1100px·목록280~340px·snapshot 최대320px는 기존 배치 상수다.

## 컴포넌트·상태
COMP-ROW: ACT-MEMO-OPEN 제목 버튼과 독립 COMP-FAV. 현재 대상 aria-current=true. 즐겨찾기 우선→order→ID 정렬. m-01/m-02/m-03의 order=1/2/2, 초기 false.
COMP-FAV: native button, ☆/★와 즐겨찾기 텍스트, aria-pressed와 메모 제목 포함 aria-label. ACT-FAV-TOGGLE·data-memo-id를 유지한다. 목록/편집 및 모든 본문 상태에서 활성. 목록 재정렬 후 같은 ID 목록 토글, 편집 조작 후 편집 토글에 포커스한다.
COMP-001: label/textarea, ACT-001, 원문 유지. COMP-002: ACT-002 저장·ACT-003 disabled 대기·ACT-006 재시도. COMP-003: 본문 상태 live 안내와 결과 포커스. COMP-004: SAVING/SAVED 요청 원문을 textContent로 표시하는 스크롤 가능한 pre.
목록 LIST-DEFAULT/MIXED/EMPTY, 편집 NO-SELECTION 및 EMPTY/EDITING/SAVING/SAVED/ERROR × FAV-OFF/ON을 유지한다. 샘플 초기화는 3개 false·미선택·이전 선택 안내 없음, 빈 목록은 행·현재 선택·이전 선택 안내 없음이다. 상태 선택과 긴 본문은 별도 aside의 샘플 제어이며 제품 정책이 아니다.

## 타깃·입력
app 390×844: 단일 목록↔편집, 터치용44px 버튼. web-mobile 390×844 및 900px 미만: 단일 열. web-desktop 1280×900 및 900px 이상: 목록+편집 분할, 패널 독립 스크롤.
모바일 열기는 제목 포커스·상단 이동, 복귀는 해당 열기 버튼·목록 위치 복원. 데스크톱 목록 접근은 선택 해제 없이 해당 열기 버튼 포커스. 웹 Tab/Shift+Tab·Enter/Space는 native 조작을 사용한다. 크기 전환은 현재 ID/값 유지·제목 포커스. 본문 변경 또는 SAVING 중 열기/복귀 disabled는 UNKNOWN 이탈 분기를 피하는 INFERRED 시험 가드다. 즐겨찾기는 계속 활성이다.
URL/history/storage는 사용하지 않는다. 직접 진입·새로고침은 초기 샘플. 브라우저 뒤로/앞으로는 문서 탐색이며 미저장 복구 보장은 없다. 실제 네이티브 입력·시스템 뒤로가기·접근성은 NOT_RUN, 실제 지원 범위는 UNKNOWN이다.

## 방향·적용 지침·검토
기존 합성 A 방향을 재사용하며 실제 사용자 제품 승인으로 표현하지 않는다. 이번은 반환 결함 수정으로 새 방향 선택은 N/A다. 기존 r1의 draft-ec287c5907490cd30e3dc80edf1f23036a790c0a0691ea064e69bf79aef812eb는 역사적 식별자다. 그 목록은 operations a4b4f3862a9633a4d667959ddfd38adb5e54392d0bbbe5b30a63fe1c3cdc1390, role-execution ca4318003af8ae05477090002bc01c8c771cb17e1747f9eca24739ec993e89be, roles/design bbbc12fa5bf3d7b3fc439ab426fd5fc7e526925a6fb0c024608170e88a3e8f29, templates/design 93240bf8e279b33da9bd9c755d60fdee41de34760a75c5822b85f635b94bbc47였다. 이번 제공 template 해시는 55893f384d094e6bb47c2f91a2ae571561dc83a8cd5d8d0431c6bfed757778e9로 다르다. 역사적 묶음 식별자를 이번 지침 해시로 주장하지 않는다. 이번 수정은 TASK-STAR-RETURN / A-targets r2 / 제공 정의와 재개 결정 94ba4fcff42c24e3c9de1ab5a9b162a303a24299071b5774e91f2b007344adeb로 추적한다. 새 비교 시안은 만들지 않았다. 입력 Git b802d18b068d4a213946a0c7f3b5dee77b6c6621은 새 출력 커밋이 아니다.
공식 검토 원본은 task.reviews/design_status.checks다. 구조·인터랙션·시각 재검증은 모두 NOT_RUN이다. UI에 하네스 검증 상태를 표시하지 않는다. 상위 검토자가 새 snapshot의 타깃별 DOM·계산 스타일·실제 조작·캡처를 보고 issue별 해결 여부를 판단한다.
