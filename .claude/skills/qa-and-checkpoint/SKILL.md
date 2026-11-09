---
name: qa-and-checkpoint
description: "DB-분석-API-대시보드 모듈 간 통합 정합성을 대조 검증하고, pytest 자동화 테스트 스위트(tests/test_tracker.py)와 체크포인트 CLI(scripts/checkpoint.py)를 실행해 품질과 프로젝트 상태를 검증한다. 기능 구현 후 검증, 코드 감사, 회귀 테스트, PROJECT_STATE.md 동기화 요청 시 사용한다."
---

# QA and Checkpoint — 통합 정합성 검증 및 체크포인트 관리 스킬

단순히 파일이 존재하는지 확인하는 데 그치지 않고, 생산자-소비자 코드 간 계약을 대조하고 실제 테스트를 실행해 결함을 잡아낸다.

## 1. 통합 정합성 검증 체크리스트 (양쪽 코드 나란히 읽기)

검증할 때는 반드시 생산자 파일과 소비자 파일을 모두 열어 필드명과 타입을 대조한다:

### 1-1. DB 모델 ↔ 수집 파이프라인 ↔ 리포지토리
- [ ] `src/ingestion/pipeline.py`에서 `Property(...)`, `PriceHistory(...)`, `AlertLog(...)`, `RentalListing(...)` 생성 시 전달하는 키워드 인자가 `src/database/models.py`의 실제 컬럼명과 일치하는가?
- [ ] `models.py`의 `to_dict()`가 새로 추가된 컬럼을 빠짐없이 반환하는가?

### 1-2. 분석 엔진(`metrics.py`) ↔ FastAPI(`main.py`) & 대시보드(`dashboard.py`)
- [ ] `compute_executive_kpis(df)`가 반환하는 딕셔너리 키(`total_inventory`, `median_price`, `median_sqft_price`, `median_dom`, `price_drop_count`, `price_drop_pct_inventory`, `avg_price_drop_rate`, `sub_220_count`, `foreclosure_count`)와 `dashboard.py` 및 `/api/analytics/kpis`가 참조하는 키가 정확히 일치하는가?
- [ ] `compute_submarket_breakdown(df)` 및 `compute_zip_code_breakdown(df)`의 반환 DataFrame 컬럼명과 Plotly 차트(`px.bar`, `px.scatter` 등)의 `x`, `y`, `color`, `hover_data` 컬럼명이 일치하는가?
- [ ] 필터 결과 `df.empty == True`일 때 API와 대시보드 모든 탭이 크래시 없이 동작하는가?

### 1-3. 산출물 동결 해시 확인 (지속형 협업 후 검증 시)
- [ ] `_workspace/freeze_*.sha` 파일이 있으면 `shasum -c _workspace/freeze_*.sha`를 실행해 동결 이후 산출물이 임의로 변경되지 않았는지 확인한다.

## 2. 자동화 테스트 스위트 실행

항상 프로젝트 가상환경(`./venv/bin/pytest`)으로 전체 테스트를 실행한다:

```bash
PYTHONPATH=. ./venv/bin/pytest -v tests/test_tracker.py
```

- 새로운 엔드포인트나 분석 함수가 추가되었다면 `tests/test_tracker.py`에 단위·통합 테스트 케이스가 포함되었는지 확인한다.

## 3. 체크포인트 상태 관리 (`scripts/checkpoint.py`)

이 프로젝트는 `.state/checkpoint.json`과 `PROJECT_STATE.md`를 동기화하는 체크포인트 프로토콜을 사용한다:

```bash
# 현재 마일스톤 및 태스크 상태 확인
./venv/bin/python scripts/checkpoint.py status

# 태스크 상태 갱신 (pending | in_progress | completed)
./venv/bin/python scripts/checkpoint.py update <TASK_ID> completed

# PROJECT_STATE.md 동기화
./venv/bin/python scripts/checkpoint.py sync
```

## 4. 검증 보고서 작성 형식

검증 결과는 다음 세 영역으로 명확히 구분해 보고한다:
1. **통과(Confirmed Pass)**: 실행한 테스트 명령과 대조 완료한 모듈 경계 목록
2. **결함(Confirmed Defect)**: `파일 경로:줄 번호`, 생산자-소비자 불일치 증거(`evidence`), 구체적인 수정 방법
3. **미검증(Unverified)**: 외부 네트워크 차단 등으로 확인하지 못한 항목과 사유

