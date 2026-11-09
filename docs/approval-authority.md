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

## 변경 후 재승인과 명시적 대체

`open_question(..., supersedes_question_id=...)`은 같은 root/run/purpose/직접 대상 task ID 집합과 이전 `decision_contract` digest를 고정해 새 질문을 만든다. typed 여부와 관계없이 대체 질문에는 native structured prompt와 `approve` 선택이 필요하다. 새 질문이 OPEN·무효·거절이면 기존 대기는 유지한다. `decisions.resolved_answer()`만 합법적인 대체 체인을 따라 새 receipt를 반환하며, 서로 모호한 대체 분기는 거부한다. 소비자는 고정된 옛 질문 ID에서 이 체인을 따라도 현재 purpose/subject/artifacts/task를 정확히 다시 비교한다. 과거 질문·답변을 덮어쓰거나 옛 근거 자체를 유효하게 복원하지 않는다.

일반 untyped 질문은 입력 bytes를 고정하며 출력은 명시한 artifact만 포함한다. typed 질문의 대상에 `development_tracking`이 있으면 `capture()`의 `code_state_sha256`도 정확히 고정한다. 내용·파일 모드·범위·HEAD 변경은 재승인이 필요하며 prompt의 `task_basis_sha256`가 해당 대상을 묶는다. 과거 일반 질문의 native 출처를 typed purpose나 `HUMAN_APPROVAL`로 승격하지 않는다.

## 소비하는 게이트

- 단계 계약 `stage_workflow`의 `human_approval_question_id`는 선택 설정이다. 설정하면 `stage_readiness.assess()`가 `stage:<stage>` purpose, 대상 task/stage, 현재 입력·출력을 검사하고 불일치 시 `HUMAN_APPROVAL_REQUIRED`다. 미설정 기존 단계에 인간 승인을 자동 강제하지 않는다.
- 요구사항 계보의 `structurally_ready`는 구조 비교이고 `authorization_ready`가 권한 준비를 구분한다. PRODUCT의 `require_review()`는 source kind·승인 주장 유무와 관계없이 올바른 typed 인간 권한 근거가 없으면 실행을 차단한다. PRODUCT 작업에 HARNESS_TRIAL 계약을 사용하는 것도 거부하며, HARNESS_TRIAL의 무승인 주장만 `NOT_REQUIRED`일 수 있다. [요구사항 계보](requirement-lineage.md)를 따른다.
- 구현 `purpose='execution'`과 QA `purpose='qa_observation'` receipt는 유지하며 인간 승인·공식 인증으로 승격하지 않는다. 관리자 QA 권한 부여와 보호 발행은 [보호 검증](protected-verification.md)의 별도 경로다.

## 신뢰 경계

`identity_assurance: LOCAL_NATIVE_INPUT_ONLY`는 로컬 원본 대응이다. 실제 사람의 본인 인증은 UNKNOWN이다. 같은 OS 계정이 native 원본과 원장을 함께 다시 쓰는 공격을 막지 못한다. 보호 비밀키에 접근하는 공격자의 서명 위조도 로컬 검사만으로 막지 못한다. 독립 원본 서비스·권한·키·신뢰된 판정기의 운영 격리는 이번에 배포하지 않는다. 합성 protocol fixture와 실제 인간 인증을 구분한다.
