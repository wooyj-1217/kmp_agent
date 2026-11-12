# 프로젝트별 회귀 시나리오 운영

시나리오는 적용 프로젝트의 `regression/catalog.json`에 누적한다. 공통 하네스는 실행과 증거 연결을 담당하고 제품의 테스트·앱 ID·UI 식별자·도구 설정은 해당 제품에 둔다. 공통 저장소는 특정 앱의 catalog나 workspace를 기본 구성으로 제공하지 않는다. `regression_workspace` 실행에는 제품 담당자가 선택한 `--workspace`가 필수다. 누락하면 어떤 제품도 탐색하거나 실행하지 않고 인자 오류로 종료한다.

workspace JSON은 `schema_version`, `required_platforms`, `projects`를 명시한다. 각 project는 `id`, `root`, `catalog`를 갖는다. `root`는 지정한 `--workspace-root` 기준 경로이며, catalog와 검증 definition은 해당 프로젝트에 보관한다. 실제 대상 프로젝트와 검증 범위를 확인한 뒤 사용한다.

각 catalog 항목은 고유 scenario ID, criterion ID, 플랫폼, 실제 도구, scope, owner, 기존 검증 definition과 check ID, smoke/full 포함 여부를 갖는다. 기대 결과·실행 명령·실제 테스트 이름·결과 파일은 연결된 definition을 재사용한다. 같은 인수 기준의 플랫폼 결과도 각각 별도 항목이다. 서버/API의 결과를 클라이언트 연동·UI·영속성 결과로 대신하지 않는다.

```sh
# 실제 프로젝트 배치와 workspace를 명시한 읽기 전용 목록
rtk proxy python3 -m harness.regression_workspace list --workspace-root <project-parent> --workspace <workspace.json> --suite smoke
rtk proxy python3 -m harness.regression_workspace list --workspace-root <project-parent> --workspace <workspace.json> --suite full
# 지정한 제품 구성의 smoke / full
rtk proxy python3 -m harness.regression_workspace run --workspace-root <project-parent> --workspace <workspace.json> --suite smoke
rtk proxy python3 -m harness.regression_workspace run --workspace-root <project-parent> --workspace <workspace.json> --suite full
# 해당 구성에 등록된 플랫폼 또는 시나리오만 선택
rtk proxy python3 -m harness.regression_workspace run --workspace-root <project-parent> --workspace <workspace.json> --platform <platform-id>
rtk proxy python3 -m harness.regression_workspace run --workspace-root <project-parent> --workspace <workspace.json> --scenario <scenario-id>
# 제품 하나만 실행
rtk proxy python3 -m harness.regression run --root <project-root> --catalog regression/catalog.json --suite smoke --output verification/regression/<unique-run>
```

실행 전에 해당 제품이 정한 빌드 도구·기기·브라우저와 검증 runner를 준비한다. 공통 하네스는 특정 앱 ID, 기기 선택 변수, 서버 프레임워크나 플랫폼 조합을 채택하지 않는다. smoke/full의 항목 수와 필수 플랫폼도 해당 workspace와 catalog가 정한다. 미지원 환경을 성공으로 간주하지 않는다.

신규 기능과 결함 수정 시 독립적으로 재현 가능한 시나리오를 해당 제품 catalog에 추가한다. 매 실행 고유 데이터를 사용하고 실행 순서에 의존하지 않는다. 실패 재실행도 새 출력 디렉터리에 보존한다.

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
