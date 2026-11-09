---
name: data-ingestion
description: "메트로 애틀랜타 매물(MLS/Realtor, Redfin), 법원 경매 공고(RLSE Law, Auction.com), 임대 매물, 거시 위험지표(Fulton 카운티 퇴거 소송 Socrata API, CFPB 모기지 연체율 CSV), 합성(Mock) 데이터를 수집·정규화·중복 제거하여 SQLite DB에 적재한다. 스크래퍼 수정, 새 서브마켓/ZIP 추가, 수집 파이프라인 실행·재실행·오류 복구 요청 시 사용한다. 이미 적재된 데이터의 KPI 집계나 차트 시각화는 market-analytics 또는 api-and-dashboard 스킬을 사용한다."
---

# Data Ingestion — 부동산 매물 및 거시 지표 수집·정규화 스킬

메트로 애틀랜타 서브마켓 매물과 거시 위험지표를 안전하게 수집하고 정규화해 `data/tracker.db` 및 로컬 캐시에 적재한다.

## 1. 대상 서브마켓 및 설정 확인

수집 작업을 시작하거나 확장할 때는 항상 `src/config.py`의 `TARGET_SUBMARKETS`, `ALL_ZIP_CODES`, `ALL_CITIES`를 먼저 확인한다.
- 새로운 도시나 ZIP 코드를 추가할 때는 `src/config.py`의 `TARGET_SUBMARKETS`에 `county`, `zip_codes`, `center`(`lat`, `lon`)를 함께 등록해야 지리공간 지도와 서브마켓 필터가 깨지지 않는다.
- 데이터 소스별 상세 엔드포인트와 정규화 스키마는 [references/sources-and-schemas.md](references/sources-and-schemas.md)를 참고한다.

## 2. 외부 수집 안전 수칙 (레이트 리미팅 및 폴백)

1. **지터(Jitter) 기반 레이트 리미팅 유지**:
   - `HomeHarvest` 및 웹 스크래핑 호출 사이에는 `DEFAULT_RATE_LIMIT_MIN_SEC`(1.5초)~`DEFAULT_RATE_LIMIT_MAX_SEC`(3.0초) 무작위 지연을 둔다. 고정 간격이나 무지연 요청은 외부 MLS·포털의 봇 차단을 유발하기 때문이다.
2. **명시적 타임아웃 및 캐시 폴백**:
   - 외부 HTTP 요청(`requests.get`)에는 반드시 `timeout=12`~`15`를 지정한다.
   - `src/ingestion/distress_trends.py`의 Socrata API나 CFPB CSV 다운로드가 성공하면 `data/eviction_filings_cache.csv`, `data/mortgage_delinquency_cache.csv`를 갱신하고 `FETCH_STATUS`를 `"live"`로 기록한다.
   - 네트워크 오류나 4xx/5xx 응답 시에는 즉시 로컬 캐시 CSV로 폴백하고 `FETCH_STATUS`를 `"cache"`로 설정한다.
3. **합성(Mock) 생성기 동기화**:
   - `src/ingestion/mock_generator.py`는 오프라인 데모와 `pytest` CI 검증의 기준 데이터다. `Property` 모델에 필수 필드가 추가되면 `mock_generator.py`에도 동일 필드를 생성하도록 함께 갱신한다.

## 3. 정규화 및 중복 제거(`src/ingestion/pipeline.py`)

`ingest_records(records, source_name)`를 수정하거나 새 소스를 연결할 때 다음 규칙을 지킨다:

1. **2단계 중복 식별**:
   - 1순위: `mls_id`가 있으면 `Property.mls_id == mls_id`로 기존 매물을 찾는다.
   - 2순위: `mls_id`가 없거나 매칭되지 않으면 `(Property.formatted_address == address, Property.zip_code == zip_code)`로 찾는다.
   - 경매 공고나 여러 포털에서 같은 매물이 다른 ID로 들어와도 주소+ZIP으로 묶어야 중복 적재와 이력 단절을 막을 수 있다.
2. **가격 변동 감지 및 `PriceHistory` 기록**:
   - 기존 매물의 `current_list_price`와 신규 수집 가격의 차이가 `$1.0`를 초과하면(`abs(current_price - old_price) > 1.0`) 가격 변동으로 판정한다.
   - 가격이 인하된 경우(`current_price < existing.original_list_price`) `is_price_drop = True`, `price_drop_amount`, `price_drop_pct`를 계산해 갱신하고 새 `PriceHistory` 레코드를 추가한다.
3. **알림 규칙 즉시 평가**:
   - 매물 삽입·갱신 직후 `evaluate_property_alerts(session, prop)`를 호출해 활성 `AlertRule` 조건(도시, ZIP, 최대 가격, 최소 침실 수, 최소 인하율, 최대 평당 가격)에 맞으면 중복 방지(최근 24시간 내 동일 규칙·매물 알림 여부 확인) 후 `AlertLog`를 생성한다.
4. **스냅샷 기록**:
   - 파이프라인 실행이 끝나면 `IngestionSnapshot`에 `source`, `total_scraped`, `new_inserted`, `price_updated`, `alerts_triggered`를 기록한다.

## 4. 표준 실행 및 검증 명령

코드를 수정한 뒤에는 아래 명령으로 파이프라인 동작을 검증한다:

```bash
# Mock 파이프라인 실행 검증
PYTHONPATH=. ./venv/bin/python -c "from src.ingestion.pipeline import run_pipeline; print(run_pipeline(source='mock'))"

# 거시 위험지표 수집(Live 또는 Cache 폴백) 확인
PYTHONPATH=. ./venv/bin/python -c "from src.ingestion.distress_trends import fetch_historical_eviction_filings, fetch_historical_mortgage_delinquency, FETCH_STATUS; print(len(fetch_historical_eviction_filings()), len(fetch_historical_mortgage_delinquency()), FETCH_STATUS)"
```

