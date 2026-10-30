# 프로젝트별 검증 절차

공통 도구는 절차의 형식·초안 생성·구조 검사를 제공한다. 실행 명령·선택자·인증 확인·기능 경로는 대상 프로젝트가 소유한다. 새로운 작업 원장이나 실행 상태 파일을 만들지 않는다. 절차 JSON은 기존 task 입력 artifact로 고정하고 검증 결과에서 그 SHA-256과 플랫폼을 연결한다.

```sh
rtk proxy python3 -B -m harness.verification_procedure generate --owner project-qa --platform android --platform ios --platform web
rtk proxy python3 -B -m harness.verification_procedure check path/to/project-verification.json
```

generate는 표준 출력에 불완전한 초안을 낸다. 파일 저장은 호출자가 정한다. `TODO`를 실제 프로젝트 지시로 채우기 전에는 check가 실패한다. check의 `format: VALID`는 형식 검사이며 `execution: NOT_RUN`이다. 도구는 JSON 안의 명령을 실행하지 않으며, 형식 검사만으로 task 기준을 PASS 처리하지 않는다. Python API는 `template(required_platforms, owner)`와 `validate(data)`다. 후자는 실패 시 ValueError, 성공 시 원본의 복사본을 반환한다.

android·ios·web·server를 모두 명시하고 각각 required·reason·procedure를 둔다. 불필요한 플랫폼은 required=false와 구체적 이유, procedure=null로 표현한다. 필수 플랫폼에는 아래 여섯 부분을 모두 작성한다. 해당하지 않는 Doctor 항목도 빈칸 대신 이유와 확인 범위를 적는다.

| 부분 | 필수 내용 |
| --- | --- |
| launch | commands, ready_when, initial_data: 실제 실행·준비 완료 판정·초기 데이터 |
| doctor | build, process, device, port, authentication, environment: 의도한 대상·환경의 식별 확인 |
| drive | id, action, expected, side_effects, evidence: 실제 사용자 조작·기대 결과·저장/네트워크 등의 효과·수집 방법 |
| evidence | paths, capture, verify_after_cleanup: 프로젝트 상대 보존 경로·수집·정리 후 파일/해시 재확인 방법 |
| cleanup | commands, owned_resources, temporary_paths, preserve_evidence=true: 자신이 생성한 자원만 정리 |
| feature_map | id, entry, preconditions, success, cautions, drive_steps: 기능별 진입·사전 조건·성공·주의·조작 연결 |

모든 drive ID는 유일해야 하고 feature_map에서 참조되어야 한다. 정리 경로와 증거 경로는 부모·자식 관계도 허용하지 않는다. 이는 선언된 경로 검사다. 자유문 명령의 안전성·실제 정리 결과·증거 내용의 의미를 자동 검증하지 않는다. 실제 실행 담당은 전후 파일과 해시를 기존 artifact 검사로 확인하고, 자신의 PID·기기·포트·임시 데이터만 소유했는지 확인한다. 다른 검증자와 기기·앱 인스턴스를 공유하면 순차 실행한다.

실제 실행 결과는 기존 독립 QA·task 검토 경로에 남긴다. 필수 플랫폼 미실행은 NOT_RUN, 기기·도구·인증 부재는 차단 사유와 미검증 기준을 기록한다. Server API 성공을 모바일 UI 검증으로 사용하지 않고 빌드 성공을 Drive 성공으로 사용하지 않는다. 입력 절차·코드·환경이 바뀌면 영향받은 실행 결과를 다시 검증한다. 기대와 관찰, 증거 위치·해시, 실행 주체와 실제 명령/조작을 각 기준에 연결한다.

실제 완료 게이트에 연결하려면 [검증 계약·적용 절차](verification-reliability.md#계약과-실제-결과-연결)의 `configure-verification`을 사용한다. `procedure`와 `environment` 파일, 모든 task 기준의 `platforms`·`method`·`evidence_required: true`·`kind`를 고정한다. 절차에서 required=true인 플랫폼마다 필수 `kind: execution` 기준이 있어야 한다. `kind: requirements`의 명세 대응 검토만으로 필수 플랫폼 실행을 대체할 수 없다. 프로젝트 정책은 신규 task에만 적용하며 기존 작업에 계약을 소급 부여하지 않는다.

직접 검토 receipt의 `platform_results`는 플랫폼별 result·environment·command_or_steps·expected·observed·doctor·drive·cleanup·evidence를 담는다. 실행 기준의 PASS에는 doctor/drive/cleanup 각각 PASS와 정리 후 유효한 artifact 증거가 필요하다. 독립 QA worker가 반환하는 같은 필드의 evidence는 격리 workspace 상대 경로 목록이며 QA 경로가 로컬 증거로 복사·고정한다. 이것은 별도 원격 보관/복구 기능이 아니다. 실제 실행을 못 한 플랫폼은 해당하지 않는다고 바꿔 완료시키지 않고 차단 범위를 남긴다.

절차 유지보수에서 잘못된 경로·오타는 문서 오류, 캡처/조작 불가능은 검증 도구 한계, 올바른 조작 후 기대 미충족은 제품 결함으로 구분해 기존 이슈에 기록한다. 요구사항 누락은 실행 결함과 별도 대응 검토로 확인하며, 제품 결함을 통과시키기 위해 기대 결과를 낮추지 않는다. 생성·형식 검사·실제 실행·독립 판정은 서로 다른 근거다.
