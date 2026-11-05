# 로컬 검증과 PR 보고

수정 검증은 로컬에서 수행한다. 새 보고서·로그·캡처·검증 JSON·패치·증거 묶음은 해당 프로젝트의 `verification/` 아래 작업별 경로에 생성한다. `docs/`에는 재사용 지침과 검증 요약을 둔다. 기존 원본은 원래 로컬 경로에 보존하고 제품·공통 Git 커밋, PR 첨부, 원격 저장소 또는 원격 보관소에 업로드하지 않는다. PR에는 수정 코드·문서와 실제 검증 명령·결과 요약만 포함한다. 기존 증거는 삭제·이동하지 않는다.

- 작업 기록에는 검증 대상 커밋 또는 미커밋 상태, 수행 검사·결과·미실행 범위, 필요한 로컬 근거 경로를 요약한다. 로컬 경로는 원격 열람이나 백업을 보장하지 않는다.
- 에이전트 일반 실행은 과거 증거 전체를 필수 입력으로 요구하지 않는다. 현재 작업의 필수 검증은 수행하며, 과거 원본을 확인하지 못했다면 과거 PASS를 현재 결과로 승계하지 않는다.
- PR 작성 전 staged 파일·diff·본문·첨부에 원본 증거·비밀값·개인정보·제품 원문이 없는지 확인한다. 기존의 추적 중인 테스트 fixture나 일반 소스 파일을 이번 결정으로 임의 삭제하지 않는다.
- PR 준비·리뷰·수정 대응 중 증거는 유지한다. 버전업 때 목록·중복·참조 상태를 점검할 수 있지만 자동 삭제·이동하지 않는다. 향후 실제 삭제·이동은 별도 명시 지시에 따른다.
- 중요한 최종·실패·수정·재검증 원본과 미해결·미반영 작업의 근거를 보존한다. 과거 로컬 파일이 사라지면 그 한계를 기록하고 현재 필요한 검증을 다시 수행한다.

원격 백업·증거 묶음·자동 정리 도구는 이 절차에 포함하지 않는다. 자세한 역할 구분은 [산출물·메모리 관리](artifact-policy.md)를 따른다.

## 새 자료 생성 경로

수동 검증은 프로젝트 루트에서 아래 명령으로 전용 폴더를 만들고, 반환된 경로 아래에 보고서·명령 로그·캡처를 저장한다. 생략한 name은 새 UUID이며 같은 name은 기존 폴더를 재사용한다. 도구는 기존 파일을 덮어쓰거나 검증 명령을 실행하지 않는다.

```sh
rtk proxy python3 -B -m harness.verification_artifacts --root . --name pr-review
```

설치 프로젝트에서는 선택한 하네스 checkout의 모듈을 사용한다. 예: `rtk proxy env PYTHONPATH=.kmp-agent/releases/선택한체크아웃 python3 -B -m harness.verification_artifacts --root . --name pr-review`. 실제 checkout 경로는 설치 manifest를 확인하고 버전을 추측하지 않는다.

- 수동 자료: `verification/manual/<name 또는 UUID>/`.
- 새 자동 QA 실행: `verification/qa/<task_id>/<agent_run_id>/` 아래 report.json·명령 로그·격리 workspace·runtime 및 증거 사본.
- 예외 실패 보고서: `verification/qa/failures/<UUID>/report.json`.
- 프로젝트 init/apply는 `/verification/`을 Git 제외 대상으로 추가한다. 생성 도구도 `verification/.gitignore`에 `*`를 처음 생성해 init 이전의 신규 자료가 추적되지 않도록 한다. 기존 추적 파일은 ignore만으로 해제되지 않는다.
- QA 코드 지문·일반 변경 snapshot·workspace 복사는 루트 `verification/`을 제외한다. 일반 소스의 중첩 `src/verification/` 같은 경로까지 제외하지 않는다.

검증 계약을 설정한 QA 작업은 `writable_paths`에 `verification/qa`를 명시해야 한다. 기존 `.harness` 전용 계약은 자동으로 권한을 넓히지 않으며 새 실행 전에 계약을 재구성한다. 제출 산출물 자체의 소유 범위 검사는 유지한다. 기존 QA 시도의 artifact 경로·해시는 그대로 읽으며 자동 이관하지 않는다. TASK 상태·이벤트·세션 원문·순차 명령 수집 원장은 계속 `.harness/`를 사용한다. `qa-tools/`는 격리 QA workspace 내부의 증거 작성 경로다. 저장 폴더 생성은 실제 검증·사용자 승인·원격 백업을 뜻하지 않는다. 기존 설치본에는 선택 버전의 명시적 update/init 이후 적용한다.
