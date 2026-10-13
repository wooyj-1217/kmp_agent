# 메모 디자인 인계 체크리스트 — 2차 문서 시험

- 작업: FEAT-002 / TASK-004; 제품 디자인 미확정
- 요구사항: [requirements.md](requirements.md)
- 고정 요구사항 SHA-256: 5820931c3e62e92c3a042262253eb7de1186bcef9d4a2d6ac1870570cac58bba
- 요구사항 스냅샷: [고정 입력](../../../.harness/artifacts/5820931c3e62e92c3a042262253eb7de1186bcef9d4a2d6ac1870570cac58bba.txt)
- 재사용 디자인 SHA-256: 9e98558f8741ca1a85ef3bdfc0e7cb114195c6148dff7484658815bedbfe7a5a
- 디자인 원본: [고정 입력](../../../.harness/artifacts/9e98558f8741ca1a85ef3bdfc0e7cb114195c6148dff7484658815bedbfe7a5a.txt)
- Git 커밋: UNKNOWN. 이번 하네스 문서 시험의 콘텐츠 스냅샷만 고정함.

| 구분 | 상태 | 범위 |
| --- | --- | --- |
| 명세 작성 | COMPLETE | 기존 화면·상태·행동의 문서 연결 정리 |
| 시안 제작 | NOT_PRODUCED | 미제작 |
| 시각 검토 | NOT_RUN | 시각 자료 없음 |

다음 항목은 고정 원본의 화면·컴포넌트·상태·행동·토큰·플랫폼·수용 기준 연결을 그대로 재사용한다. AC 축약은 EX-FEAT-001-AC 고유 ID를 뜻한다.

## 화면 목록·구조

| 화면 ID·이름 | 목적·진입 경로 | 영역·배치·이동 경로 | 수용 기준 ID |
| --- | --- | --- | --- |
| SCREEN-001 / 메모 작성 | 예제 진입점에서 열기 | 상단 제목, 본문 입력, 저장 버튼, 진행·결과 메시지 순서. 성공 시 같은 화면 유지라는 가설 | EX-FEAT-001-AC-001, EX-FEAT-001-AC-002, EX-FEAT-001-AC-003, EX-FEAT-001-AC-004 |

## 컴포넌트

| 컴포넌트 ID | 사용 화면 | 구조·내용·변형·접근성 | 수용 기준 ID |
| --- | --- | --- | --- |
| COMP-BODY | SCREEN-001 | 여러 줄 입력, 레이블 '메모 내용'; 최대 길이는 UNKNOWN | AC-001, AC-004 |
| COMP-SAVE | SCREEN-001 | '저장' 버튼; 처리 중 비활성화 | AC-002, AC-004 |
| COMP-FEEDBACK | SCREEN-001 | 진행·완료·오류 텍스트와 재시도 버튼; 색상만으로 구분하지 않음 | AC-002, AC-003 |

## 상태별 UI

| 상태 ID·화면·컴포넌트 | 상태·발생 조건 | 표시·가능 행동·복구 | 수용 기준 ID |
| --- | --- | --- | --- |
| STATE-EMPTY / SCREEN-001 / COMP-BODY, COMP-SAVE | 처음 진입·빈 입력 | 입력 영역 표시; 빈 값 저장 버튼 활성·오류 규칙은 UNKNOWN(Q-001) | AC-001, AC-004 |
| STATE-EDITING / SCREEN-001 / COMP-BODY | 본문 입력 | 입력 문자 표시; 길이 제한은 UNKNOWN(Q-002) | AC-001 |
| STATE-SAVING / SCREEN-001 / COMP-SAVE, COMP-FEEDBACK | 비어 있지 않은 본문 저장 요청 | '저장 중' 표시·추가 저장 차단; 처리 중 본문 편집 허용 여부 UNKNOWN — 기획 정책 제안 POL-005 / Q-005 참조 | AC-002, AC-003 |
| STATE-SAVED / SCREEN-001 / COMP-FEEDBACK | 성공 응답 | 같은 화면에 '저장 완료' 표시; 본문 유지 가설, 실제 저장 보장은 UNKNOWN(Q-003) | AC-002 |
| STATE-ERROR / SCREEN-001 / COMP-BODY, COMP-FEEDBACK | 저장 실패 | 입력 유지·'저장하지 못했습니다'·재시도 표시 | AC-003 |

별도 목록·데이터 로딩의 빈 상태는 N/A — 이 예제는 작성 화면만 다룬다. 최초 빈 본문은 STATE-EMPTY다.

## 인터랙션

| 행동 ID·대상·사용자 행동 | 전제 조건 | 이전→이후 상태·피드백·이동 화면 ID | 수용 기준 ID |
| --- | --- | --- | --- |
| ACT-001 / COMP-BODY / 문자 입력 | 작성 화면 | EMPTY → EDITING, 같은 SCREEN-001에 문자 표시 | AC-001 |
| ACT-002 / COMP-SAVE / 저장 | 비어 있지 않은 본문이라는 가설 | EDITING → SAVING → 성공 시 SAVED 또는 실패 시 ERROR; SCREEN-001 유지 | AC-002, AC-003 |
| ACT-003 / COMP-FEEDBACK / 재시도 | ERROR | ERROR → SAVING; 입력 유지, ACT-002와 같은 응답 처리 | AC-003 |
| ACT-004 / 화면 / 뒤로 가기 | 미저장 입력 | 이동 대상·폐기·확인 동작 UNKNOWN(Q-004); 임의 확정 금지 | N/A — 정책 결정 후 기준 추가 필요 |
| ACT-005 / COMP-SAVE / 빈 값 저장 | EMPTY | 상태 변화·오류·허용 여부 UNKNOWN(Q-001) | AC-004 |

## 디자인 토큰

| 토큰 이름 | 값·단위 | 용도·적용 범위 |
| --- | --- | --- |
| color.text / color.error / color.action | UNKNOWN | 본문·피드백·저장 버튼 |
| typography.body / spacing.content / size.touchTarget | UNKNOWN | 입력·배치·터치 영역; 시각·접근성 검토 전 미확정 |

## 키보드·스크롤·접근성·플랫폼 차이

| 항목 | Android | iOS | 공통 동작·근거·수용 기준 ID |
| --- | --- | --- | --- |
| 키보드·포커스 | 구체 IME 동작 UNKNOWN | 구체 키보드 동작 UNKNOWN | 입력 시 포커스·키보드 표시 가설 / AC-001 |
| 스크롤 | 본문 내 스크롤 가설 | 동일 가설 | 긴 본문에서 커서 위치가 보이도록 함; 최대 길이 미정 / AC-001 |
| 접근성 | 읽기 순서·알림 API UNKNOWN | 동일 UNKNOWN | 제목→본문→저장→결과 순서, 레이블·오류 텍스트 제공 가설 / AC-001~003 |
| 플랫폼 차이 | 시스템 뒤로 가기 처리 UNKNOWN | 뒤로 이동 제스처 처리 UNKNOWN | Q-004 결정 필요; 안전 영역·글자 확대 상세 UNKNOWN |

## 시각 자료 참조

| 자료 ID | 경로·버전 또는 없음 | 대응 화면·기준 ID | 검토 결과·검토자·일자 |
| --- | --- | --- | --- |
| N/A — 자료 미제작 | 없음 / 버전 N/A — 파일 없음 | SCREEN-001 / AC-001~004 | 미완료 / 검토자·일자 N/A — 미검토 |

## 수용 기준 연결·인계

| 수용 기준 ID | 화면·컴포넌트·상태·인터랙션 | 구현 TASK·코드 참조 | 검증 증거 참조 |
| --- | --- | --- | --- |
| EX-FEAT-001-AC-001 | SCREEN-001 / COMP-BODY / STATE-EMPTY, STATE-EDITING / ACT-001 | 미구현; TASK N/A — 예제 | NOT_RUN — 구현 없음 |
| EX-FEAT-001-AC-002 | SCREEN-001 / COMP-SAVE, COMP-FEEDBACK / STATE-SAVING, STATE-SAVED / ACT-002 | 미구현; TASK N/A — 예제 | NOT_RUN — 구현 없음 |
| EX-FEAT-001-AC-003 | SCREEN-001 / COMP-FEEDBACK / STATE-ERROR, STATE-SAVING / ACT-002, ACT-003 | 미구현; TASK N/A — 예제 | NOT_RUN — 구현 없음 |
| EX-FEAT-001-AC-004 | SCREEN-001 / COMP-BODY, COMP-SAVE / STATE-EMPTY / ACT-005; 기대 동작 UNKNOWN | 미구현; TASK N/A — 예제 | NOT_RUN — 정책 UNKNOWN |

## 미결정·인계 범위

Q-001~Q-005와 DQ-001~DQ-004는 고정 원본의 UNKNOWN·단계별 차단 범위를 유지한다. 저장 중 편집 비활성화는 기획 제안이며 채택하지 않는다. 새 정책·토큰·시각 자료를 생성하지 않는다.
이 문서의 명세 COMPLETE는 문서 연결 정리만 뜻한다. 제품 구현·저장 연동·최종 기능 검증·시각 검토 완료가 아니다. 변경 이력은 Git으로 관리하며 작업 상태는 YAML을 따른다.
