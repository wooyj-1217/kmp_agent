# 메모 작성 — 디자인 인계 시험 산출물

- 예제 기능: EX-FEAT-001; 실제 제품 미확정
- 하네스 작업: FEAT-001 / TASK-002; 입력 작업 TASK-001
- 요구사항: [requirements.md](requirements.md)
- 고정 입력 SHA-256: `e7c1b8f859e7e27c8d444d8deb60d038c7ea9d84440588e0fdc15efad21aea28`
- Git 커밋: UNKNOWN. 이번 문서 인계 시험의 콘텐츠 스냅샷이며 제품 실행 인계의 Git 버전 고정을 대신하지 않음.

| 구분 | 상태 | 적용 범위 |
| --- | --- | --- |
| 명세 작성 | COMPLETE | 문서 연결 시험의 화면·상태·행동 매핑 작성만 완료 |
| 시안 제작 | NOT_PRODUCED | 시각 자료 미제작 |
| 시각 검토 | NOT_RUN | 시각 자료 없음; 문서 검토와 구분 |

## 화면 구조

| 화면 ID | 구조 | 수용 기준 |
| --- | --- | --- |
| SCREEN-001 | 제목→여러 줄 본문→저장→결과 피드백 | EX-FEAT-001-AC-001~004 |

## 컴포넌트

| ID | 역할·레이블 | 수용 기준 |
| --- | --- | --- |
| COMP-BODY | 본문 입력, '메모 내용' | AC-001, AC-004 |
| COMP-SAVE | '저장', 처리 중 중복 요청 차단 | AC-002, AC-004 |
| COMP-FEEDBACK | 진행·완료·오류 메시지, 재시도 | AC-002, AC-003 |

AC 축약은 requirements.md의 EX-FEAT-001-AC 고유 ID를 뜻한다.

## 상태별 UI

| 상태 ID | 표시·행동 | 정책 연결 |
| --- | --- | --- |
| STATE-EMPTY | 빈 입력 표시; 저장 허용·오류 동작 UNKNOWN | Q-001 / AC-004 |
| STATE-EDITING | 입력 문자열 표시; 길이 제한 UNKNOWN | Q-002 / AC-001 |
| STATE-SAVING | 저장 중 표시·중복 요청 차단; 본문 편집 허용 UNKNOWN | POL-001 / Q-005 / AC-002 |
| STATE-SAVED | 동일 화면에 저장 완료 표시라는 가설 | Q-003 / AC-002 |
| STATE-ERROR | 본문 유지·오류·재시도 | POL-002 / AC-003 |

## 인터랙션

| 행동 ID | 전제·행동 | 상태 전환·화면 이동 |
| --- | --- | --- |
| ACT-001 | 문자 입력 | STATE-EMPTY → STATE-EDITING / SCREEN-001 |
| ACT-002 | 비어 있지 않은 본문 저장 요청 | STATE-EDITING → STATE-SAVING → STATE-SAVED 또는 STATE-ERROR / SCREEN-001 |
| ACT-003 | 오류 후 재시도 | STATE-ERROR → STATE-SAVING / SCREEN-001 |
| ACT-004 | 미저장 상태 이탈 | UNKNOWN / Q-004; 기획 결정 후 기준 보완 |
| ACT-005 | 빈 값 저장 요청 | STATE-EMPTY에서 이후 상태 UNKNOWN / Q-001 |

## 디자인 토큰

색상·타이포·간격·터치 영역 값은 UNKNOWN. 현재는 ID 연결만 검토하며 정확한 스타일 구현·검증은 후속 디자인 작업이다.

## 키보드·스크롤·접근성·플랫폼 차이

본문 입력의 포커스, 긴 본문의 스크롤, 레이블·결과 텍스트 제공을 제안한다. Android/iOS 키보드·뒤로 이동·안전 영역·접근성 API의 정확한 동작은 UNKNOWN이며 확정하지 않는다.

## 시각 자료

- 위치·버전: N/A — 미제작
- 시각 검토: NOT_RUN — 검토 자료 없음

## 수용 기준 연결

| 수용 기준 ID | 화면·컴포넌트·상태·행동 | 구현·제품 검증 |
| --- | --- | --- |
| EX-FEAT-001-AC-001 | SCREEN-001 / COMP-BODY / STATE-EMPTY, STATE-EDITING / ACT-001 | 미구현 / NOT_RUN |
| EX-FEAT-001-AC-002 | SCREEN-001 / COMP-SAVE, COMP-FEEDBACK / STATE-SAVING, STATE-SAVED / ACT-002 | 미구현 / NOT_RUN |
| EX-FEAT-001-AC-003 | SCREEN-001 / COMP-BODY, COMP-FEEDBACK / STATE-ERROR, STATE-SAVING / ACT-002, ACT-003 | 미구현 / NOT_RUN |
| EX-FEAT-001-AC-004 | SCREEN-001 / COMP-BODY, COMP-SAVE / STATE-EMPTY / ACT-005; 기대 결과 UNKNOWN | 미구현 / NOT_RUN |

## 미결정·변경 영향

Q-001~Q-005의 차단 범위·후속 담당은 requirements.md의 미결정 표를 원본으로 사용한다. 저장 중 편집 제한은 POL-005 기획 제안이며 미채택이다.
현재 TASK-002의 완료 범위는 문서 연결·상태 분리다. 제품 구현 준비나 시각 검토 완료를 선언하지 않는다.
정책 결정 시 해당 화면·상태·행동·수용 기준을 재검토한다. Git 변경 이력을 사용하며 실행 입력 스냅샷은 덮어쓰지 않는다.
