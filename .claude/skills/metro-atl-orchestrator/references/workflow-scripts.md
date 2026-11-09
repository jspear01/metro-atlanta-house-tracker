# Metro Atlanta Real Estate Tracker — 워크플로 스크립트 레시피

`metro-atl-orchestrator`의 2단계(워크플로 조율)에서 `Workflow` 도구의 `script` 매개변수로 전달하는 순수 JavaScript 스크립트 모음이다.

## 작성 및 검증 규칙
- `meta` 객체에는 변수나 함수 호출 없이 **리터럴만** 사용한다.
- TypeScript 타입 표기(`: string[]` 등)를 쓰지 않고 순수 JavaScript로 작성한다.
- `Date.now()`, `new Date()`, `Math.random()`을 쓰지 않는다. 타임스탬프나 시드가 필요하면 `args`로 전달한다.
- `phase()`에 전달하는 문자열은 `meta.phases`의 `title`과 정확히 일치시킨다.
- `pipeline()`과 `parallel()` 결과에는 항상 `.filter(Boolean)`을 적용해 실패한 `agent()`의 `null` 반환을 안전하게 걸러낸다.
- 확인 범위를 일부 서브마켓이나 상위 N건으로 제한했을 때는 제외한 항목 수를 반드시 `log()`로 남긴다.

---

## 레시피 1: 서브마켓·데이터 소스 분산 점검 및 적대적 검증

여러 서브마켓이나 데이터 소스(`realtor`, `foreclosure`, `evictions`, `mortgage_delinquency`)의 수집·정규화·집계 상태를 분산 점검한 뒤, 발견된 이상 징후나 결함을 `qa-verifier`가 적대적 검증(`confirmed` / `refuted` / `uncertain`)으로 걸러내는 스크립트다.

```javascript
export const meta = {
  name: 'metro-atl-submarket-audit',
  description: '서브마켓 및 데이터 소스별 상태를 점검하고 발견된 결함을 적대적 검증한다',
  phases: [
    { title: '점검', detail: '서브마켓·데이터 소스별 수집 및 집계 정합성을 조사한다' },
    { title: '검증', detail: '발견된 항목마다 실제 코드와 데이터 근거를 대조해 검증한다' },
  ],
}

const FINDINGS_SCHEMA = {
  type: 'object',
  required: ['target', 'findings'],
  properties: {
    target: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['title', 'file', 'evidence', 'severity'],
        properties: {
          title: { type: 'string' },
          file: { type: 'string' },
          evidence: { type: 'string' },
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
        },
      },
    },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['status', 'reason'],
  properties: {
    status: { type: 'string', enum: ['confirmed', 'refuted', 'uncertain'] },
    reason: { type: 'string' },
  },
}

const allTargets = args.targets ?? []
const maxTargets = args.limit ?? allTargets.length
const selectedTargets = allTargets.slice(0, maxTargets)
const skippedCount = allTargets.length - selectedTargets.length
if (skippedCount > 0) {
  log(`전체 ${allTargets.length}개 대상 중 ${selectedTargets.length}개만 점검합니다 (제외된 대상: ${skippedCount}개).`)
}

phase('점검')
const verifiedNested = await pipeline(
  selectedTargets,
  t =>
    agent(
      `대상 [${t.name}] (${t.scope})의 수집·정규화·집계 코드와 데이터를 점검하고 문제나 이상 징후를 반환하라. 최종 출력은 반환 데이터(JSON)다.`,
      {
        agentType: 'ingestion-specialist',
        label: `점검:${t.name}`,
        phase: '점검',
        schema: FINDINGS_SCHEMA,
      }
    ),
  report => {
    const items = report?.findings ?? []
    return parallel(
      items.map(f => () =>
        agent(
          `다음 점검 결과를 실제 파일(${f.file})과 대조해 적대적 검증하라. 코드·데이터 근거가 명확하면 confirmed, 반박되면 refuted, 판단 근거가 부족하면 uncertain으로 판정하라: ${JSON.stringify(f)}`,
          {
            agentType: 'qa-verifier',
            label: `검증:${f.file}`,
            phase: '검증',
            schema: VERDICT_SCHEMA,
            effort: 'high',
          }
        ).then(verdict => (verdict ? { ...f, target: report.target, verdict } : null))
      )
    )
  }
)

const flatResults = verifiedNested.filter(Boolean).flat().filter(Boolean)
const confirmed = flatResults.filter(item => item.verdict?.status === 'confirmed')
const discardedCount = flatResults.length - confirmed.length
log(`총 ${flatResults.length}건의 후보 중 ${confirmed.length}건이 confirmed 판정을 받았습니다 (기각/보류: ${discardedCount}건, 점검 제외 대상: ${skippedCount}개).`)

return {
  inspectedTargets: selectedTargets.map(t => t.name),
  skippedTargetsCount: skippedCount,
  totalCandidates: flatResults.length,
  confirmedCount: confirmed.length,
  confirmed,
}
```

