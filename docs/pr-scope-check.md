# PR 범위 검사 사용법

정책은 [공통 PR 준비·제출](operations.md#pr-submission)에만 정의한다. 이 도구는 명시적으로 실행하는 보조 검사다. Git 훅·자동 스케줄러·PR 게시 게이트가 아니며 의미상 완전성이나 사용자 승인 여부를 보장하지 않는다.

## 원본 목록 고정

```sh
python3 -B tools/check_pr_scope.py snapshot --root "$SOURCE_ROOT" --base "$SOURCE_BASE" --id "$SOURCE_ID"
```

JSON 출력에는 기준 커밋·HEAD·변경 경로·SHA-256이 있다. 기준부터 현재 작업 트리까지 추적 변경·삭제와 nonignored 미추적 파일을 수집한다. 실제 root 경로는 저장하지 않는다. 원본 내용을 복사하지는 않으므로 별도 백업을 먼저 한다. ignored 필수 파일은 직접 조사하고 `--include-ignored <파일>`을 반복 지정한다. 디렉터리·submodule은 파일 단위 조사 없이 지원한다고 간주하지 않는다. symlink는 대상 파일을 따라 읽지 않고 링크 문자열만 지문화하며, 부모 경로가 symlink인 명시 파일은 거부한다.

## 범위표 형식

민감한 경로명까지 포함될 수 있으므로 공개 전 검토한다. `sources`에는 위 snapshot 객체를 복수로 넣는다. 아래는 구조 설명이며 실제 해시·출처로 작성해야 한다.

```json
{
  "sources": [],
  "decisions": [
    {"source": "source-id", "path": "feature.txt", "action": "include", "reason": "요청 구현", "in_scope": true},
    {"source": "source-id", "path": "private-fixture.txt", "action": "transform", "target": "tests/public-fixture.txt", "target_sha256": "실제 제출 내용의 SHA-256", "reason": "민감 자료를 합성 자료로 대체; 차이와 한계 기록", "in_scope": true},
    {"source": "source-id", "path": "local-output.txt", "action": "exclude", "reason": "요청 구현과 무관한 일회성 결과", "in_scope": false}
  ],
  "additional": [{"path": "docs/review.md", "reason": "이번 제출 검증 보고서"}],
  "required": ["tests/public-fixture.txt"],
  "documents": ["docs/review.md"]
}
```

- 원본 항목마다 결정이 하나 있어야 한다. `include`는 파일명·개수가 아닌 원본/제출 바이트 해시를 비교한다. `transform`은 이유와 실제 제출 해시가 일치해야 한다. 원본 삭제는 제출 ref에서도 삭제되어야 한다.
- 요청 범위의 `exclude`, `unresolved`, 결정 누락은 실패다. `in_scope: false`는 작성자의 판단이므로 거짓 분류를 도구가 검출하는 것은 아니다. 공통 규칙에 따라 요청 기능을 제외·연기할 수 없다.
- 제출 과정에서 새로 추가한 파일은 `additional`에 이유와 함께 적는다. PR diff의 분류되지 않은 변경도 실패한다.
- 검증 입력·fixture·자원은 `required`에 적는다. checkout에만 존재하는 미추적 자료는 제출된 것으로 세지 않는다. 숨은 런타임 의존은 자동 추론하지 않으므로 clean checkout 실행은 따로 필요하다.

## 깨끗한 제출 checkout 대조

```sh
python3 -B tools/check_pr_scope.py check --root "$CLEAN_CHECKOUT" --base "$PR_BASE" --scope "$SCOPE_JSON" --source "$SOURCE_ID=$SOURCE_ROOT" --body "$PR_BODY"
```

원본이 여러 곳이면 `--source ID=ROOT`를 반복한다. root는 실제 제출 HEAD가 있는 깨끗한 Git checkout이어야 한다. `--source`로 원본을 다시 수집해 snapshot 이후 변경도 검출한다. 원본 접근이 없으면 `NOT_RUN live source recapture`를 기록한다. 구조 검사 PASS를 원본 대조까지 완료한 것으로 표현하지 않는다.

제출 HEAD의 Git 객체에서 대상 파일·해시·필수 자료를 확인한다. PR 최종 diff가 모두 분류되었는지도 검사한다. `documents`에 선택한 Markdown과 선택적인 `--body`의 inline Markdown 상대 파일 링크를 제출 트리 기준으로 검사한다. 참조형 Markdown 링크는 `NOT_RUN`으로 기록한다. 전체 과거 기록의 로컬 링크까지 새 결함으로 취급하지 않도록 검토 대상 문서를 명시한다. 파일 존재와 제목 앵커 유효성은 다르다. 외부 URL·제목 앵커는 `NOT_RUN`이며, 실제 PR 브랜치의 웹 링크 접근은 따로 확인한다.

결과 JSON의 `result`는 이 구조 검사의 PASS/FAIL이다. 실패 시 종료 코드가 0이 아니다. `not_run`을 반드시 함께 읽는다. 도구 입력 오류도 완료로 처리하지 않는다. 자동으로 코드를 수정하거나 자료를 삭제·업로드하지 않는다.

## 검증

```sh
python3 -B -m unittest harness.test_pr_scope -v
```

격리된 임시 Git 저장소로 누락·내용 불일치·미추적 필수 파일·제외 자료 의존·잘못된 링크·이관 변환·삭제·미해결을 확인한다. 실제 모델·원격 설치·배포 검증이 아니다. 일반 회귀 실행 `python3 -B -m harness.run_tests -v`도 이 테스트 모듈을 자동 수집한다.
