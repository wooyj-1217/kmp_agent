# 승인된 개발 기술 결정의 동결과 검사

개발 소스의 계약이다. 별도 승인 원장이나 제품 스택을 만들지 않고 [요구사항 출처·일치 계약](requirement-lineage.md)의 `requirement-lineage.json`을 재사용한다. 설치본·릴리스·적용 프로젝트로 자동 전파하지 않는다.

설치된 제품의 raw 도구 호출·종료·게시 연결은 [제품 도구 검사](product-tool-enforcement.md)를 따른다. PRODUCT 기술 결정은 구조상 출처 연결뿐 아니라 현재 native 인간 승인도 필요하다. 기능 기획 승인만으로 기술 정책을 바꾸거나 승인 레이블을 직접 기재해 적용하지 않는다.

## 원본과 구성

DB 초기 결정은 [DB 기본 스택 확인](project-settings.md#db-기본-스택-확인)에 따라 공통 기본 조합의 사용/변경을 확인한다. 기본안 제시는 제품의 승인된 DB 결정이나 사용 여부를 대신하지 않으며, 확정 뒤 이 계약에 연결한다.

정확히 하나의 authoritative requirement의 `expected.development_constraints`에 아래 정책을 둔다. 승인 의미·원본 진위는 기존 독립 requirements QA가 확인한다. AGENT_DERIVED나 설정의 CONFIRMED 표기만으로 기술 변경을 승인하지 않는다. PRODUCT의 `code_implementation` 작업에는 필수이며 PRODUCT lineage가 필요하다. 그 밖의 작업은 lineage에 이 정책을 명시한 경우에만 적용한다. 정책을 명시하지 않은 기존 입력 해석·시험을 소급 인증하지 않는다.

```json
{
  "settings": {
    "implementation_targets": ["android", "ios", "web"],
    "ui_technology": "<프로젝트 설정의 승인 값과 같은 값/구조>",
    "database": {"engine": "<승인 엔진>", "location": "<승인 저장 위치>", "role": "<원본 저장/캐시 등 승인 역할>"},
    "server_mode": "<승인 값>",
    "code_ownership": "<프로젝트 설정의 승인 값과 같은 값/구조>"
  },
  "ui_sharing": "shared",
  "ui_owners": {"composeApp/src/commonMain": "kmp"},
  "platform_entrypoints": {
    "android": ["<Android 진입 파일>"],
    "ios": ["<iOS 진입 파일>"],
    "web": ["<웹 진입 파일>"]
  },
  "target_commands": {
    "android": [["rtk", "proxy", "./gradlew", ":composeApp:assembleDebug"]],
    "ios": [["rtk", "proxy", "./gradlew", ":composeApp:iosSimulatorArm64Test"]],
    "web": [["rtk", "proxy", "./gradlew", ":composeApp:wasmJsBrowserTest"]]
  },
  "source_rules": [{"glob": "<제품 소스 glob>", "required_patterns": ["<필수 regex>"], "forbidden_patterns": ["<금지 regex>"]}]
}
```

자리표시자와 Gradle 명령은 설명용이며 제품에서 실제 값·경로·명령·패턴을 승인해 채워야 한다. 명령은 `rtk proxy` 인자 배열을 사용하며 예시의 모듈·태스크가 제품에 존재한다고 가정하지 않는다. 공통 하네스가 SQLite나 특정 DB 위치·Compose·웹 기술을 선택하지 않는다. DB 없음은 `database: null`과 프로젝트 설정의 NOT_APPLICABLE 사유로 명시한다. DB가 있으면 engine/location/role이 모두 필요하다. 승인된 원본 저장을 임의의 로컬 SQLite나 캐시로 바꾸지 않는다.

정책의 최상위 키와 settings 키는 예시의 집합과 정확히 같아야 한다. 설정의 다섯 값은 [단계 설정](project-settings.md)의 CONFIRMED 값 또는 NOT_APPLICABLE의 null과 일치해야 한다. `ui_sharing`은 shared/platform_specific/none이며, shared의 UI 소유자는 모두 kmp다. UI가 있으면 소유 경로가 필요하다. 허용 소유 영역은 kmp/android/ios/web/server다. 공유 UI를 플랫폼 담당별 UI로 재분배하려면 원본 결정을 변경하고 재검토해야 한다.

진입 파일과 명령은 선택 타깃 전체를 정확히 포함하고, 각 타깃에 하나 이상 있어야 한다. 웹이 선택되면 웹 진입 파일과 명령도 필수다. 경로는 프로젝트 상대 경로이고 소스 규칙의 glob 외에는 패턴을 허용하지 않는다. `source_rules`는 하나 이상이며 각 규칙은 glob/required_patterns/forbidden_patterns를 가진다. 각 규칙에 최소 하나의 regex가 필요하다. 필수 패턴은 해당 glob에 맞는 각 파일에서 확인하고, 금지 패턴은 일치 파일에서 거절한다. 제품은 실제 구조를 검증하는 범위로 glob과 패턴을 정해야 한다.

## 동결·전달·변경

기존 `configure-stage`가 정책·digest·requirement ID·lineage와 출처 snapshot을 stage_contract에 묶고 작업 inputs에 포함한다. 이후 lifecycle 게이트는 현재 원본·snapshot·설정 일치를 확인한다. 변경·누락·손상은 재구성·재검토 대상으로 차단하며 원본만 고쳐 동결 입력을 교체할 수 없다.

[개발 위임](development-delegation.md)은 부모의 단계 계약과 입력을 자식에게 상속하고 worker packet에 정책을 전달한다. 계획의 ui_owners는 승인 정책과 정확히 같아야 하고 통합 명령은 모든 타깃 명령을 포함해야 한다. integration_verification 단계는 구현 위임으로 대체하지 않고 별도 제품 인수를 유지한다.

자식 제출·작업본 검사에서는 금지 소스 패턴을 확인한다. 부모 제출·통합/검토에서는 필수 패턴·진입 파일·UI 소유 경로 존재까지 확인한다. 자식의 영역 PASS는 제품 전체 구조나 모든 타깃 완료를 인증하지 않는다. 완료 상태 갱신에서도 현재 코드/계약의 검증 유효성을 다시 점검한다.

부모의 전체 검사에서는 소스 규칙에 일치하는 파일·진입 파일·UI 소유 경로 아래 파일이 개발 추적의 `code_paths` 범위와 실제 capture 파일 목록에 모두 포함되어야 한다. Git ignore 등으로 fingerprint에서 빠진 미추적 소스를 존재 여부만으로 승인하지 않는다.

## 명령 증거와 완료 경계

부모 필수 기준의 PASS evidence에는 `constraints_sha256`, `constraint_review_run_id`, `constraint_target_results`를 기록한다. 각 타깃 결과는 target/result/commands를 가지며 각 명령 증거는 argv/exit_code/call_id/stdout_sha256/stderr_sha256를 가진다. 위임 통합 경로는 기존 명령 logger의 실제 결과에서 이를 생성한다.

검토는 제출 outputs와 연결된 최신 종료 work 실행에 review_run_id를 묶고, 타깃별 승인 argv·성공 종료와 같은 task/agent_run/call_id의 native command_started/command_finished 각 한 쌍, 순서·run_id·argv digest·출력 digest를 대조한다. 시작·종료 양쪽의 `cwd`는 프로젝트 루트 `.`이어야 하고 `code_state_sha256`는 제출 코드의 현재 capture digest와 같아야 한다. 수동 PASS 문자열이나 다른 실행·코드 상태의 로그로 대체할 수 없다. 환경이 없어 실행하지 못하면 NOT_RUN/BLOCKED이며 PASS가 아니다.

개발 추적 refresh도 보존된 PASS 검토의 동결 보고서와 native 명령 증거를 다시 대조한다. 이후 보고서·시작/종료 증거의 유실·변조 또는 현재 코드와의 불일치는 과거 PASS를 현재 유효한 검증으로 유지하지 못하게 한다.

이 검사는 선언한 구조·패턴·명령 증거의 일치 검사다. 코드의 의미, 실제 DB 사용 경로, UI 공유의 충분성, 명령이 제품 인수 조건을 충분히 시험하는지, 사용자 승인 진위를 자동 증명하지 못한다. [독립 QA](qa.md)와 실제 제품의 플랫폼·연동·end-to-end 인수는 유지한다. 제한 하네스 시험이나 실행 경로 통과를 실제 제품 e2e·전체 실행 경로 완료로 확대하지 않는다.
