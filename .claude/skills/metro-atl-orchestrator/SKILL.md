---
name: metro-atl-orchestrator
description: "메트로 애틀랜타 부동산 가격·경매·임대·거시 위험지표 추적 프로젝트(metro-atl-tracker)의 에이전트 팀 워크플로를 조율한다. 서브마켓 추가, 스크래퍼·수집 파이프라인 실행 및 개선, DB·DuckDB KPI 분석 확장, FastAPI 엔드포인트 및 Streamlit 대시보드 기능 구현, 전체 데이터·코드 품질 감사를 요청할 때 사용한다. 결과 수정, 부분 재실행, 업데이트, 보완, 다시 실행, 이전 결과를 바탕으로 개선, 특정 서브마켓이나 대시보드 탭만 다시 처리하는 후속 작업에도 반드시 사용한다."
---

# Metro Atlanta Real Estate Tracker 오케스트레이터

## 실행 모드: 혼합

작업 성격에 따라 단계별로 가장 적합한 Harness v2 실행 모드를 조합한다. `TeamCreate`, `TeamDelete`, 실험 기능 플래그 같은 v1 방식은 사용하지 않는다.

| 단계 | 실행 모드 | 선택 이유 |
|------|----------|-----------|
| 0단계(기존 작업 및 체크포인트 확인) | 메인 에이전트 직접 수행 | `_workspace/` 존재 여부, 부분 재실행 대상, `run_meta.json`, `.state/checkpoint.json`을 먼저 확인해야 한다. |
| 1단계(범위 및 대상 목록 확정) | 메인 에이전트 직접 수행 | 대상 서브마켓(`Duluth`, `Suwanee` 등), 데이터 소스, 수정할 모듈 목록을 확정해 `args`와 `_workspace/00_input/`에 기록한다. |
| 2단계(서브마켓·소스별 수집/진단 및 적대적 검증) | 워크플로 조율 (`Workflow`) | 서브마켓·소스 목록이 배열로 정해져 있으므로 `pipeline()`으로 분산 점검·수집하고 `VERDICT` 스키마로 적대적 검증을 수행한다. |
| 3단계(DB·분석·API·대시보드 구현 및 조율) | 지속형 에이전트 협업 (`Agent(name:)` + `SendMessage` + `TaskCreate`) | `ingestion-specialist`, `analytics-engineer`, `fullstack-builder`가 스키마와 API·차트 필드 계약을 대화 맥락을 유지하며 맞춰야 한다. |
| 4단계(통합 정합성 및 테스트 검증) | 서브에이전트 위임 (`Agent`) | `qa-verifier`가 동결된 산출물과 코드를 독립적으로 대조하고 `pytest` 및 `checkpoint.py`를 실행해 결과만 보고하면 된다. |

**실행 모드 전환 규칙:**
- **워크플로 조율(2단계) → 지속형 에이전트 협업(3단계)**: 워크플로가 반환한 구조화 JSON 결과(`confirmed` 항목 및 누락 로그)를 `_workspace/02_workflow_verified.json`에 저장하고, 3단계 지속형 에이전트 프롬프트에 이 파일 경로를 전달한다.
- **지속형 에이전트 협업(3단계) → 서브에이전트 위임(4단계)**: 3단계 팀원들의 산출물을 동결(`shasum _workspace/03_* > _workspace/freeze_03.sha`)한 뒤, 4단계 `qa-verifier` 프롬프트에 산출물 경로와 해시 파일 경로를 함께 넘긴다.

## 에이전트 구성

| 이름 / `agentType` | 모델 | 역할 | 연결 스킬 | 산출물 경로 |
|------|------|------|------|------|
| `ingestion-specialist` | `sonnet` (정형화된 수집·정규화·캐시 폴백 처리) | MLS/Realtor/Redfin/경매/임대/거시지표 수집 및 중복 제거 | `data-ingestion` | `_workspace/{phase}_ingestion-specialist_{artifact}.md` |
| `analytics-engineer` | `opus` (SQLite/DuckDB 스키마·분위수·코호트 설계) | ORM 모델, 리포지토리, DuckDB/Pandas KPI 및 알림 엔진 | `market-analytics` | `_workspace/{phase}_analytics-engineer_{artifact}.md` |
| `fullstack-builder` | `opus` (FastAPI 계약 및 Streamlit/Plotly 시각화) | REST API 엔드포인트 및 대시보드 탭·차트·지도 구현 | `api-and-dashboard` | `_workspace/{phase}_fullstack-builder_{artifact}.md` |
| `qa-verifier` | `opus` (모듈 간 경계 대조 및 적대적 검증) | DB-분석-API-UI 계약 대조, `pytest` 실행, 체크포인트 검증 | `qa-and-checkpoint` | `_workspace/{phase}_qa-verifier_{artifact}.md` |

## 작업 절차

### 0단계: 기존 작업 확인(후속 요청 처리)

**실행 모드:** 메인 에이전트 직접 수행

1. `_workspace/` 디렉터리와 `.state/checkpoint.json`을 확인한다.
   - `_workspace/`가 없으면 → 새로 만들고 처음부터 실행한다.
   - `_workspace/`가 있고 일부 단계나 특정 에이전트(예: "대시보드 차트만 다시", "Duluth 수집만 재실행")만 고쳐 달라는 요청이면 → 기존 산출물을 유지하고 해당 단계·에이전트만 다시 실행한다.
   - `_workspace/`가 있고 완전히 새로운 주제나 전체 재실행 요청이면 → 기존 `_workspace/`를 `_workspace_{timestamp}/`로 옮긴 뒤 새로 만든다.
2. 2단계 워크플로를 일부만 다시 실행할 때 `_workspace/run_meta.json`에 직전 `runId`가 기록되어 있으면 `resumeFromRunId`를 지정해 재개한다. 변경되지 않은 `agent()` 호출은 캐시 결과를 즉시 반환받아 비용을 아낀다.

### 1단계: 범위 및 대상 목록 확정

**실행 모드:** 메인 에이전트 직접 수행

1. 사용자 요청을 분석해 작업 유형을 판별한다:
   - **데이터 수집·진단·감사 포함 시**: 2단계(워크플로 조율)부터 실행한다.
   - **기능 구현·스키마·UI 수정 중심일 때**: 1단계에서 대상 파일과 요구사항을 `_workspace/00_input/request_spec.md`에 정리한 뒤 3단계(지속형 에이전트 협업)로 바로 진입할 수 있다.
2. 대상 서브마켓(`src/config.py`의 `TARGET_SUBMARKETS`), 데이터 소스(`realtor`, `foreclosure`, `redfin`, `evictions`, `mortgage_delinquency`, `mock`), 검토 차원을 배열로 확정해 `_workspace/00_input/targets.json`에 기록한다.

### 2단계: 서브마켓·소스별 분산 점검 및 적대적 검증

**실행 모드:** 워크플로 조율 (`Workflow`)

사용자가 이 오케스트레이터 스킬을 호출하면 `Workflow` 도구 사용에 동의한 것으로 본다. 기본 실행 규모는 2~4개 대상(소규모)으로 제한하며, 사용자가 "전수", "철저히", "모든 서브마켓"을 요청한 경우에만 전체 목록으로 확장한다.

1. 실행할 순수 JavaScript 워크플로 스크립트는 [references/workflow-scripts.md](references/workflow-scripts.md)의 레시피를 사용한다.
2. 스크립트 핵심 구조:
   - `meta`: 리터럴만 사용 (`name: 'metro-atl-audit'`, `phases: [{ title: '점검' }, { title: '검증' }]`)
   - `args`: `{ targets: [...], runLabel: '...' }` (`Date.now()`나 `Math.random()`은 절대 쓰지 않고 타임스탬프가 필요하면 `args`로 전달)
   - `phase('점검')`: `pipeline(args.targets, ...)`로 `ingestion-specialist` 또는 `analytics-engineer`를 호출해 `FINDINGS` 스키마(`findings: [{ title, file, evidence, metric }]`)로 결과를 수집
   - `phase('검증')`: 각 항목에 대해 `qa-verifier`가 `VERDICT` 스키마(`status: 'confirmed' | 'refuted' | 'uncertain'`, `reason`)로 적대적 검증 수행 후 `.filter(Boolean)` 적용
   - 샘플링이나 상위 N개 제한을 둔 경우 제외한 항목 수를 반드시 `log()`로 기록
3. 워크플로 완료 알림을 받은 뒤 반환된 결과를 `_workspace/02_workflow_verified.json`에 저장하고 `runId`를 `_workspace/run_meta.json`에 기록한다.

### 3단계: DB·분석·API·대시보드 협업 구현

**실행 모드:** 지속형 에이전트 협업 (`Agent(name:)` + `SendMessage` + `TaskCreate`)

1. 필요한 전문 에이전트를 한 메시지에서 이름을 붙여 병렬로 실행한다:
   - `Agent(name: "ingestion", subagent_type: "ingestion-specialist", prompt: "...")`
   - `Agent(name: "analytics", subagent_type: "analytics-engineer", prompt: "...")`
   - `Agent(name: "fullstack", subagent_type: "fullstack-builder", prompt: "...")`
2. `TaskCreate`로 공유 작업과 의존 관계를 등록한다:
   - 작업 1 (`assignee: "ingestion"`): 수집·정규화 모듈 업데이트 및 `_workspace/03_ingestion-specialist_spec.md` 작성
   - 작업 2 (`assignee: "analytics"`, `depends_on: [작업 1]`): DB 모델·리포지토리·DuckDB/Pandas 집계 업데이트 및 `_workspace/03_analytics-engineer_contract.md` 작성
   - 작업 3 (`assignee: "fullstack"`, `depends_on: [작업 2]`): FastAPI 엔드포인트 및 Streamlit 대시보드 반영 후 `_workspace/03_fullstack-builder_changes.md` 작성
3. 조율 및 피드백 루프:
   - 각 에이전트의 첫 보고에서 사용 가능한 도구 목록을 확인한다. 만약 `TaskUpdate`가 누락된 에이전트가 있으면 리더가 대신 작업 상태를 갱신한다.
   - `analytics`가 반환 키와 컬럼 계약을 확정하면 `SendMessage({to: "fullstack"}, ...)`로 전달해 UI와 API가 정확한 필드명을 쓰도록 조율한다.
4. **산출물 동결(4단계 진입 전 필수)**:
   - 모든 3단계 작업 완료를 확인한 뒤 각 팀원에게 `SendMessage`로 동결을 선언한다: `"3단계 산출물을 동결한다. 이후 수정이 필요하면 기존 파일을 고치지 말고 03_{agent}_{artifact}_v2.md로 작성한 뒤 리더에게 알려라."`
   - `shasum _workspace/03_* > _workspace/freeze_03.sha`로 해시를 기록한다.

### 4단계: 독립 통합 정합성 및 테스트 검증

**실행 모드:** 서브에이전트 위임 (`Agent`)

1. `qa-verifier`를 호출하되, 동결된 산출물 경로와 `_workspace/freeze_03.sha`를 프롬프트에 전달한다:
   - `Agent(subagent_type: "qa-verifier", prompt: ".claude/skills/qa-and-checkpoint/SKILL.md 절차에 따라 1) freeze_03.sha 해시 대조, 2) DB-분석-API-대시보드 필드 계약 대조, 3) PYTHONPATH=. ./venv/bin/pytest -v tests/test_tracker.py 실행, 4) ./venv/bin/python scripts/checkpoint.py status 확인을 수행하고 검증 결과를 반환하라.")`
2. 검증 결과를 `_workspace/04_qa-verifier_report.md`에 저장한다.
3. 결함이 발견되면 3단계의 해당 지속형 에이전트에게 `SendMessage`로 `파일:줄 번호`를 전달해 수정하게 하고(최대 2회 반복), 수정 후 `qa-verifier`로 재검증한다.

### 5단계: 상태 동기화 및 최종 보고

**실행 모드:** 메인 에이전트 직접 수행

1. `shasum -c _workspace/freeze_03.sha`로 동결 이후 무단 변경이 없었는지 최종 확인한다.
2. 마일스톤이나 태스크 상태 변경이 있으면 `./venv/bin/python scripts/checkpoint.py sync`를 실행해 `PROJECT_STATE.md`를 최신화한다.
3. `_workspace/`를 보존한 채 사용자에게 완료된 작업, 검증 통과 결과, 누락·제외된 항목(있다면)을 투명하게 보고한다.

## 오류 처리

| 상황 | 대응 방법 |
|------|------|
| 워크플로 내 개별 `agent()` 실패(`null` 반환) | 결과 배열에 `.filter(Boolean)`을 적용해 제외하고, 제외된 항목 수를 `log()` 및 최종 보고서에 명시한다. |
| 지속형 에이전트 무응답 또는 중지 | `SendMessage`로 상태를 한 번 확인하고 재지시한다. 그래도 응답하지 않으면 같은 `subagent_type`을 새 이름(예: `"fullstack-b"`)으로 실행하고 `_workspace/`의 이전 산출물 경로를 프롬프트로 넘긴다. |
| 사용량 한도 소진, 인증 만료, 권한 거부, 외부 사이트 IP 차단(403/429) | 재시도해도 결과가 같거나 차단을 악화시키므로 **절대 재시도하지 않는다**. 부분 산출물과 `journal`을 직접 열어 실제 진행 범위를 확인하고, 누락 내역을 `_workspace/incomplete_report.md`에 기록한 뒤 사용자에게 보고한다(사용량 한도라면 해제 시각 포함). 리더는 직접 확인한 사실만 반영하며 에이전트의 판단을 추측해 메우지 않는다. |
| 데이터 소스 간 수치·스키마 충돌 | 임의로 한쪽 데이터를 삭제하지 않고 `DATA_SOURCES` 출처 및 `FETCH_STATUS`(`live` vs `cache`/`mock`)와 함께 나란히 기록한다. |
| 절반이 넘는 에이전트 실패 | 즉시 실행을 멈추고 사용자에게 현 상태와 실패 원인을 알린 뒤 진행 여부를 확인받는다. |

## 테스트 시나리오

### 정상 흐름
1. 사용자가 `"Johns Creek과 Alpharetta 서브마켓의 가격 인하율 분석 지표를 대시보드와 API에 추가해줘"`라고 요청한다.
2. 0~1단계에서 `_workspace/`를 준비하고 대상 서브마켓과 수정 범위(`metrics.py`, `main.py`, `dashboard.py`)를 `_workspace/00_input/request_spec.md`에 기록한다.
3. 3단계에서 `analytics`(`analytics-engineer`)와 `fullstack`(`fullstack-builder`)을 실행해 KPI 계산 함수와 API/대시보드 차트를 구현하고 `_workspace/freeze_03.sha`로 동결한다.
4. 4단계에서 `qa-verifier`가 `metrics.py` 반환 키와 `dashboard.py` 참조 키 일치 여부를 검증하고 `pytest` 전체 통과를 확인한다.
5. 예상 결과: API와 대시보드에 새 지표가 반영되고 `_workspace/04_qa-verifier_report.md`에 검증 통과 기록이 남는다.

### 오류 흐름
1. 사용자가 `"전체 서브마켓 실시간 수집 파이프라인 점검 및 대시보드 업데이트해줘"`라고 요청한다.
2. 2단계 워크플로 실행 중 외부 사이트 레이트 리미팅으로 `Norcross` 수집 `agent()`가 `null`을 반환한다.
3. 워크플로 스크립트가 `.filter(Boolean)`으로 `null`을 걸러내고 `log("1건(Norcross) 실시간 수집 실패 — 제외됨")`을 기록한다.
4. 3단계에서 `ingestion-specialist`가 `Norcross`에 대해 로컬 캐시/Mock 폴백 경로가 정상 작동하는지 확인하고, 최종 보고서에 `"Norcross 실시간 수집 1건 실패(로컬 폴백 적용)"`을 명시해 보고한다.

