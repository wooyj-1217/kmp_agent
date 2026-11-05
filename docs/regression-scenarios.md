# 프로젝트별 회귀 시나리오 운영

시나리오는 적용 프로젝트의 `regression/catalog.json`에 누적한다. 공통 하네스는 실행과 증거 연결을 담당하고 제품의 테스트·앱 ID·UI 식별자는 제품에 둔다. 현재 workspace는 형제 디렉터리 `kmp_agent`와 `kmp_agent_demo_app`을 묶는다. 다른 배치는 별도 workspace JSON과 `--workspace-root`, `--workspace`로 지정한다.

각 항목은 고유 scenario ID, criterion ID, 플랫폼, 실제 도구, scope, owner, 기존 검증 definition과 check ID, smoke/full 포함 여부를 갖는다. 기대 결과·실행 명령·실제 테스트 이름·결과 파일은 연결된 definition을 재사용한다. 같은 인수 기준의 Android/iOS/Web 결과는 각각 별도 항목이다. 서버 항목은 **Ktor fixture**이며 데모앱의 서버 기능이나 모바일의 HTTP 연동을 증명하지 않는다.

```sh
# 저장소 루트에서 읽기 전용 목록
python3 -m harness.regression_workspace list --suite smoke
python3 -m harness.regression_workspace list --suite full
# 네 타깃 smoke / 전체 등록 항목
python3 -m harness.regression_workspace run --suite smoke
python3 -m harness.regression_workspace run --suite full
# 특정 플랫폼 또는 시나리오 (지정한 범위만 실행)
python3 -m harness.regression_workspace run --platform ios
python3 -m harness.regression_workspace run --scenario memo.save_restore.web.playwright
# 제품 하나만 실행
python3 -m harness.regression run --root ../kmp_agent_demo_app --catalog regression/catalog.json --suite smoke --platform android --output verification/regression/manual-unique-run
```

실제 환경에서는 저장소 RTK 지침에 따라 위 명령 앞에 `rtk proxy`를 사용한다. 첫 실행 전에 제품의 빌드 도구와 실제 에뮬레이터/시뮬레이터, Maestro 및 Playwright browser를 준비한다. 모바일은 전용 기기를 기동하고 `MEMO_MAESTRO_ANDROID_DEVICE=emulator-<port>`, `MEMO_MAESTRO_IOS_DEVICE=<simulator-uuid>`로 선택한다. `MEMO_MAESTRO_ANDROID_BIN`, `MEMO_MAESTRO_IOS_BIN`으로 실제 도구를 지정할 수 있다. 승인된 실험용 도구가 필요하면 별도 경로와 `MEMO_MAESTRO_ANDROID_TOOL_ID`도 명시한다. 앱 ID는 제품 runner의 `dev.yeoback.maestro.acceptance`이고 빌드·설치·종료 후 재실행·제목/본문 assertion을 실행한다. 기존 제품 설치본을 대상으로 지정하지 않는다. 기본 Maestro가 현재 Android 기기를 탐색하지 못하는 환경에서는 성공으로 간주하지 않고 해당 runner 로그를 확인한다. Web은 제품 `tools`에서 `npm ci`로 lock된 Playwright를 설치한다. 기존 browser cache가 필요하며 자동으로 시스템 설정을 바꾸지 않는다. Web wrapper는 Wasm을 빌드하고 임의 로컬 포트의 정적 서버를 소유·정리한 후 기존 Playwright 검증을 실행한다.

현재 smoke는 Android Maestro, iOS Maestro, Web Playwright, Server Ktor HTTP의 4개이다. full은 여기에 common JVM, Android instrumentation, iOS XCTest, Android lint, Web build를 더한 9개다. 신규 기능과 결함 수정 시 독립적으로 재현 가능한 시나리오를 해당 제품 catalog에 추가한다. 매 실행 고유 데이터를 사용하고 실행 순서에 의존하지 않는다. 실패 재실행도 새 출력 디렉터리에 보존한다.

회귀 실행 시점은 다음과 같다. 매일 야간을 포함한 정기 실행은 현재 운영 범위에서 제외한다.

| 시점 | 실행 범위 |
| --- | --- |
| 구현·보완 후 QA 요청 전 | 변경에 영향받는 시나리오 |
| PR 제출·추가 커밋 후 | 영향받는 플랫폼의 smoke |
| 공통 코드·저장소·검증 설정 변경 시 | 영향받는 모든 플랫폼. 영향 범위를 확정할 수 없으면 전체 |
| 릴리스 후보 확정 후 | 후보 커밋 기준 full 전체 |

이 표는 운영 기준이다. 위 시점의 자동 실행과 CI 차단 연결은 아직 구현하지 않았으며, 실제 CI 연결과 보호 발행자 배포는 별도 범위다. 필수 항목의 삭제·제외·assertion·기준 이미지·검증 명령 변경은 기존 승인 갱신 절차를 거쳐야 한다. catalog 선택으로 승인된 완료 기준을 줄일 수 없다. 불안정한 테스트도 조용히 제외하지 않고 사유와 담당자를 남겨 승인 기준을 갱신한다.

각 프로젝트의 `verification/regression/<run-id>/`에 receipt와 결과 요약을 저장한다. workspace 요약은 하네스 `verification/regression-workspaces/<run-id>/summary.json`에서 제품 결과의 위치와 hash만 연결한다. 제품 원본 증거는 복사하지 않는다. catalog/definition hash와 원본 계획 버전, 선택 제외 항목, 코드 식별자, 실제 러너 결과를 보존한다. 모음 실행 중 코드 또는 검증 입력 변경은 성공 집계를 차단한다.

이 실행기는 `UNTRUSTED_REGRESSION_OBSERVATION`, `official=false`, `full_completion=false`를 항상 명시한다. 실행 성공은 `OBSERVED_PASS`이며 일부 시나리오 또는 full 선택 성공도 공식 완료가 아니다. 기존 완료 진입점은 승인 계획과 보호된 발행자·정확한 제출 커밋의 증거를 별도로 확인한다. 실행 실패·미지원 환경·누락 결과는 해당 프로젝트 receipt에 남고 상위 성공 집계가 차단된다.
