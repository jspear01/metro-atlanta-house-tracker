# 데이터 소스 및 정규화 스키마 참조

## 1. 매물 수집 레코드 표준 스키마 (`ingest_records` 입력)

모든 스크래퍼(`scraper.py`)와 합성 생성기(`mock_generator.py`)는 아래 키를 포함한 딕셔너리 리스트를 반환해야 한다:

| 필드명 | 타입 | 필수 여부 | 설명 |
|------|------|------|------|
| `mls_id` | `str \| None` | 권장 | MLS 고유 번호 또는 소스별 고유 식별자 |
| `formatted_address` | `str` | 필수 | 전체 도로명 주소 |
| `city` | `str` | 필수 | 서브마켓 도시명 (`Duluth`, `Suwanee`, `Norcross` 등) |
| `state` | `str` | 필수 | 기본값 `"GA"` |
| `zip_code` | `str` | 필수 | 5자리 ZIP 코드 문자열 |
| `county` | `str` | 권장 | 카운티명 (`Gwinnett`, `Fulton`, `Forsyth` 등) |
| `current_list_price` | `float` | 필수 | 현재 호가 (`> 0`) |
| `original_list_price` | `float` | 선택 | 최초 등록 호가 (없으면 `current_list_price`로 초기화) |
| `beds` | `float \| None` | 선택 | 침실 수 |
| `baths` | `float \| None` | 선택 | 욕실 수 |
| `sqft` | `float \| None` | 권장 | 실내 면적 (`price_per_sqft` 계산에 사용) |
| `days_on_market` | `int` | 선택 | 시장 체류 일수 (DOM) |
| `is_foreclosure` | `bool` | 선택 | 경매/압류 매물 여부 |
| `foreclosure_stage` | `str \| None` | 선택 | 경매 단계 (`notice_of_sale`, `reo`, `auction` 등) |
| `listing_source` | `str` | 필수 | `"realtor"`, `"redfin"`, `"foreclosure"`, `"mock"` 등 |

## 2. 거시 위험지표 외부 데이터 소스 (`src/ingestion/distress_trends.py`)

| 키 | 출처 | URL / 엔드포인트 | 로컬 캐시 파일 | 반환 컬럼 |
|---|---|---|---|---|
| `evictions` | Fulton County Open Data Portal (Socrata) | `https://data.fultoncountyga.gov/resource/cbu2-qs5w.json` | `data/eviction_filings_cache.csv` | `date`, `year`, `month`, `filings`, `county`, `source` |
| `mortgage_delinquency` | CFPB National Mortgage Database | `CountyMortgagesPercent-90-plusDaysLate-thru-2025-12.csv` 외 | `data/mortgage_delinquency_cache.csv` | `county`, `date`, `year`, `late_90_plus_pct`, `late_30_89_pct` |
| `ga_legal_notices` | RLSE Law & Auction.com | `https://rlselaw.com/property-listing/georgia-property-listings/` | DB `properties` (`is_foreclosure=True`) | 매물 표준 스키마와 동일 |

