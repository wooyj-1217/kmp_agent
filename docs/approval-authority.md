# 승인·검토 권한 경계

기존 작업 상태·task.reviews·필수 질문·보호 정책을 재사용하며 별도 승인 원장을 만들지 않는다. 운영 본인 인증이나 보호 발행자를 배포했다는 뜻은 아니다.

| 유형 | 근거·용도 | 대체할 수 없는 것 |
| --- | --- | --- |
| `ROLE_REVIEW` | 역할 기준 검토와 제한된 구현·QA DONE | 인간 승인, 관리자 QA 권한 부여, 공식 인증 |
| `HUMAN_APPROVAL` | 현재 질문·대상·산출물에 연결된 native 사용자 입력 | 독립 QA 실행 결과, 보호 검증 |
| `QA_AUTHORIZATION` | 후보 밖 관리자 보호 정책이 정확한 QA basis 고정 | 로컬 QA PASS, 제품 방향의 인간 승인 |
| `OFFICIAL_CERTIFICATION` | 현재 제출 코드·계약과 일치하는 보호 실행·서명 증거 | 미승인 제품 정책 확정 |

## native 인간 승인

`decisions.open_question()`의 새 `decision_contract.version=1`은 질문·선택지·대상 task 범위와 실제 입력 bytes를 고정한다. 출력 산출물은 `approval_artifacts`에 명시한 파일만 고정하며 일반 질문에 새 출력 생성을 금지하지 않는다. typed 승인은 `approval_purpose`, `approval_subject`, `approval_artifacts`를 지정한다. 본문에 추가하는 `Approval scope` suffix를 포함해 같은 질문 항목을 native structured prompt로 제시해야 한다.

`answer_question()`은 고정 root native 세션 원본·질문 이후 경계·인접 사용자 메시지와 입력·structured 선택을 확인한다. `approvals.human_approval()`은 소비 시에도 `decisions.resolved_answer()`로 명시적인 유효 대체 체인을 해석하고 `validate_answer()`로 원본·현재 질문·대상 입력·산출물을 재검사한다. purpose/subject/artifacts/task가 일치하며 선택 ID가 `approve`일 때만 `HUMAN_APPROVAL`을 반환한다. 답변 당시 통과 이력만으로 재사용하지 않는다. 자유문, 다른 질문, 오래된 입력, 로컬 승인 라벨, 역할 검토와 QA PASS는 이 근거가 아니다.

typed 승인 질문은 등록 시 정확한 선택지 ID `approve`를 포함해야 한다. 라벨이 승인처럼 보여도 `APPROVE-T1`·`yes`를 대신 사용할 수 없으며 잘못된 질문은 checkpoint·사용자 표시 전에 거절한다. UI에 전달할 질문은 등록 결과의 `Approval scope` suffix까지 포함한 전체 문자열과 같은 순서의 선택지 라벨을 사용한다.

### 네이티브 질문과 UI 표시 응답

응답은 native `questionItemId`의 도구·호출 ID·질문 인덱스로 질문 이후의 유일한 실제 prompt 호출에 연결한다. 호출 원문의 **전체 질문**과 선택지·고정 승인 계약을 대조한 뒤 선택 라벨을 해석한다. UI가 돌려준 질문은 표시용이다. 전체 문자열, 줄바꿈의 공백 정규화, 이 두 문자열의 유효 UTF-8 경계 512바이트 절단만 지원하며 임의의 짧은 접두어를 허용하지 않는다. 표시용 접두어가 같아도 원래 호출의 질문·승인 범위가 다르면 거절한다. 호출 ID·선택지·항목이 잘못되거나 중복·모호하면 승인하지 않는다.

서로 다른 시점에 열린 질문의 batch 응답은 각 항목의 원래 호출과 그 질문의 개설 경계로 따로 검증한다. 같은 call/item을 가리키는 별도 사용자 응답이 여러 개면 승인 locator 하나를 골라 소비할 수 없다. 등록·복구뿐 아니라 소비 시점의 현재 native 원문 끝까지 재검사하며, 나중에 충돌 응답이 추가돼도 기존 승인은 유효하지 않다. 인접한 event/response_item 한 쌍은 한 사용자 사건으로 취급한다.

이 보완은 미배포 변경이며 기존 v0.4.6 설치본에는 소급 적용되지 않는다. 합성 protocol 시험과 실제 Codex UI의 질문→선택→typed 소비를 별도로 검증한다. 실제 UI 시험은 임시 시험 계약에만 적용하며 제품의 기존 승인이나 제품 전체 인수를 대신하지 않는다.

### 이미 받은 응답의 명시적 복구

전송 형식 때문에 연결하지 못한 원문 응답은 `task --operation recover-question`으로 다시 검증할 수 있다. 새 질문·선택지를 만들거나 원장을 직접 편집하지 않는다. 공식 명령이 검증한 복구 결과와 감사 이력만 원장에 기록한다. 질문이 속한 정확한 `--run-id`와 다음 JSON을 제품의 `docs/guard-inputs/` 아래 준비한다. 예시의 식별자·ordinal·해시는 실제 기존 원본에서 확인한 값으로 바꿔야 하며 새로 지어내거나 현재 파일 해시로 과거 값을 덮어쓰지 않는다.

```json
{
  "question_id": "TECH-APPROVAL",
  "reason": "기존 네이티브 응답의 표시 형식 오류를 재검증",
  "expected_contract_sha256": "<original decision_contract digest>",
  "question_item_id": "[\"request_user_input_async\",\"<native-call-id>\",0]",
  "record_ordinal": 123,
  "payload_sha256": "<original event payload digest>",
  "user_input_record_ordinal": 122,
  "user_input_payload_sha256": "<original response_item payload digest>"
}
```

```sh
rtk proxy python3 .kmp-agent/agent.py task --run-id RUN --operation recover-question --data docs/guard-inputs/approval-recovery.json
```

digest는 `harness.decisions.digest`의 canonical JSON SHA-256이다. event/response_item ordinal은 고정 native 세션 JSONL의 1부터 시작하는 인접 사용자 입력 레코드 위치다. 복구는 질문의 checkpoint·전체 계약·현재 대상 bytes·원본 세션 경계·정확한 호출/응답을 재검증한다. 계약·대상 파일·코드 기준이 바뀌면 거절하며 새 범위의 기존 재승인 규칙을 따른다. 이미 ANSWERED이면 같은 유효 원본만 재검증하고 다른 답변으로 대체하지 않는다.

성공하면 기존 질문의 `recovery_history`와 `required_question_answer_recovered` 이벤트에 이유·원문 locator/hash·호출 근거·당시 계약 digest·원래 선택 ID·전후 상태·시각·소비 가능 여부를 기록한다. 같은 근거의 반복 복구는 다시 검증하지만 이력을 중복 생성하지 않는다. 실패하면 잠정 답변·성공 이력을 저장하지 않는다. 소비자는 이력만 믿지 않고 기존 `validate_answer()`를 다시 수행한다.

실패도 원래 대상 작업에 `required_question_recovery_rejected` 이벤트로 요청 이유·거절 원인·질문 ID·제출한 계약 hash·native locator/hash·item을 남긴다. 인증은 복사한 상태에서 수행하므로 거절 시 원래 질문·답변·복구 이력과 성공 outbox를 유지하고 거절 감사만 기록한다. 존재하지 않는 질문은 무관한 작업에 귀속하지 않는다. 거절 이벤트는 승인 근거가 아니다.

구버전에 잘못 등록된 `APPROVE-T1` 같은 선택은 원래 ID 그대로 복구할 수 있지만 `approval_consumable: false`다. 이를 `approve`로 바꾸거나 라벨의 의미를 추측해 소비하지 않는다. 유효 canonical 질문의 전송 실패 복구와 잘못된 질문 설정의 권한 이전은 별개이며 후자의 자동 이전 경로는 제공하지 않는다. 실제 제품 원장 복구·재개는 수정 버전의 명시 설치와 해당 원문·현재 범위 재검증 뒤 별도로 수행한다.

## 변경 후 재승인과 명시적 대체

`open_question(..., supersedes_question_id=...)`은 같은 root/run/purpose/직접 대상 task ID 집합과 이전 `decision_contract` digest를 고정해 새 질문을 만든다. typed 여부와 관계없이 대체 질문에는 native structured prompt와 `approve` 선택이 필요하다. 새 질문이 OPEN·무효·거절이면 기존 대기는 유지한다. `decisions.resolved_answer()`만 합법적인 대체 체인을 따라 새 receipt를 반환하며, 서로 모호한 대체 분기는 거부한다. 소비자는 고정된 옛 질문 ID에서 이 체인을 따라도 현재 purpose/subject/artifacts/task를 정확히 다시 비교한다. 과거 질문·답변을 덮어쓰거나 옛 근거 자체를 유효하게 복원하지 않는다.

일반 untyped 질문은 입력 bytes를 고정하며 출력은 명시한 artifact만 포함한다. typed 질문의 대상에 `development_tracking`이 있으면 `capture()`의 `code_state_sha256`도 정확히 고정한다. 내용·파일 모드·범위·HEAD 변경은 재승인이 필요하며 prompt의 `task_basis_sha256`가 해당 대상을 묶는다. 과거 일반 질문의 native 출처를 typed purpose나 `HUMAN_APPROVAL`로 승격하지 않는다.

## 소비하는 게이트

- 단계 계약 `stage_workflow`의 `human_approval_question_id`는 선택 설정이다. 설정하면 `stage_readiness.assess()`가 `stage:<stage>` purpose, 대상 task/stage, 현재 입력·출력을 검사하고 불일치 시 `HUMAN_APPROVAL_REQUIRED`다. 미설정 기존 단계에 인간 승인을 자동 강제하지 않는다.
- 요구사항 계보의 `structurally_ready`는 구조 비교이고 `authorization_ready`가 권한 준비를 구분한다. PRODUCT의 `require_review()`는 source kind·승인 주장 유무와 관계없이 올바른 typed 인간 권한 근거가 없으면 실행을 차단한다. PRODUCT 작업에 HARNESS_TRIAL 계약을 사용하는 것도 거부하며, HARNESS_TRIAL의 무승인 주장만 `NOT_REQUIRED`일 수 있다. [요구사항 계보](requirement-lineage.md)를 따른다.
- 구현 `purpose='execution'`과 QA `purpose='qa_observation'` receipt는 유지하며 인간 승인·공식 인증으로 승격하지 않는다. 관리자 QA 권한 부여와 보호 발행은 [보호 검증](protected-verification.md)의 별도 경로다.

## 신뢰 경계

`identity_assurance: LOCAL_NATIVE_INPUT_ONLY`는 로컬 원본 대응이다. 실제 사람의 본인 인증은 UNKNOWN이다. 같은 OS 계정이 native 원본과 원장을 함께 다시 쓰는 공격을 막지 못한다. 보호 비밀키에 접근하는 공격자의 서명 위조도 로컬 검사만으로 막지 못한다. 독립 원본 서비스·권한·키·신뢰된 판정기의 운영 격리는 이번에 배포하지 않는다. 합성 protocol fixture와 실제 인간 인증을 구분한다.
