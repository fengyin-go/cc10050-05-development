/** 试判 / 规则更正 / 重算轮次工作流接口。结构以后端返回为准，这里保持宽松类型。 */

export type JsonRecord = Record<string, any>

export type RuleVersion = {
  version: string
  归一规格?: string
  target_caliber?: string
  包装要求?: string
  数量要求?: number | string
  单瓶容量ml?: number | string
  总容量ml?: number | string
  包含关键词?: string[]
  排除关键词?: string[]
  标签要求?: string
  版本说明?: string
  created_at?: string
  created_by?: string
  [key: string]: unknown
}

export type SpecRule = {
  id: number
  rule_code: string
  规则名称: string
  商品标识: string
  商品名称?: string
  归一规格: string
  target_caliber: string
  映射优先级?: number | string
  active_version: string
  status: string
  重叠组?: string
  versions: RuleVersion[]
  [key: string]: unknown
}

export type PriceQuote = JsonRecord & {
  id: number
  报价编号?: string
  报价金额: number | string
}

export type RuleCheck = {
  维度: string
  要求: unknown
  实际: unknown
  通过: boolean
  原因: string
}

export type Evaluation = {
  rule_id: number
  rule_code: string
  规则名称: string
  rule_version: string
  归一规格: string
  命中: boolean
  checks: RuleCheck[]
  failed_checks: RuleCheck[]
  priority: number
}

export type TrialResult = JsonRecord & {
  key: string
  quote_id?: number
  报价编号?: string
  报价金额?: number | string
  comparable: boolean
  actual_spec: string
  matched_rule_ref: string
  evaluations: Evaluation[]
  verdict: { 可比: boolean; reason: string; mismatches: RuleCheck[] }
  input: JsonRecord
  normalized: JsonRecord
}

export type TrialRecord = {
  id: number
  ran_at: string
  rule_batch: JsonRecord[]
  results: TrialResult[]
  [key: string]: unknown
}

export type QuoteSnapshot = JsonRecord & {
  quote_id?: number
  报价编号?: string
  报价金额?: number | string
  reason?: string
}

export type Round = JsonRecord & {
  id: number
  code: string
  status: '待确认' | '已确认' | '已发布' | string
  adopted: {
    adopted_at: string
    rule_batch: JsonRecord[]
    caliber: JsonRecord
    caliber_text: string
    classifications: TrialResult[]
    participating: QuoteSnapshot[]
    excluded: QuoteSnapshot[]
    excluded_amount: number
    preview_price: number | null
  }
  confirmation: null | {
    confirmed_at: string
    baseline_price: number
    participating: QuoteSnapshot[]
    excluded: QuoteSnapshot[]
    excluded_amount: number
    [key: string]: unknown
  }
  publication: null | JsonRecord
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = ''
    try {
      detail = (await response.json())?.detail ?? ''
    } catch {
      /* ignore */
    }
    throw new Error(detail || `接口返回 ${response.status}`)
  }
  return (await response.json()) as T
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  return parse<T>(response)
}

export async function listSpecRules(product = ''): Promise<SpecRule[]> {
  const query = product ? `?product=${encodeURIComponent(product)}` : ''
  const payload = await parse<{ items: SpecRule[] }>(await fetch(`/api/spec-rules${query}`))
  return payload.items
}

export async function correctSpecRule(
  id: number,
  values: Record<string, unknown>,
  operator = '数据工程组',
): Promise<{ ok: boolean; message: string; entry: SpecRule }> {
  return postJson(`/api/spec-rules/${id}/correct`, { values, operator })
}

export async function listPriceQuotes(product = ''): Promise<PriceQuote[]> {
  const query = product ? `?product=${encodeURIComponent(product)}` : ''
  const payload = await parse<{ items: PriceQuote[] }>(await fetch(`/api/price-quotes${query}`))
  return payload.items
}

export async function listSpecBaselines(): Promise<JsonRecord[]> {
  const payload = await parse<{ items: JsonRecord[] }>(await fetch('/api/spec-baselines'))
  return payload.items
}

export async function runTrial(body: Record<string, unknown>): Promise<{ trial: TrialRecord; message: string }> {
  return postJson('/api/trial/run', body)
}

export async function createRound(
  trialId: number,
  baselineId?: number,
): Promise<{ ok: boolean; message: string; round: Round }> {
  return postJson('/api/recalc-rounds', { trial_id: trialId, baseline_id: baselineId ?? null })
}

export async function listRounds(baselineId?: number): Promise<Round[]> {
  const query = baselineId ? `?baseline_id=${baselineId}` : ''
  const payload = await parse<{ items: Round[] }>(await fetch(`/api/recalc-rounds${query}`))
  return payload.items
}

export async function getRound(id: number): Promise<Round> {
  return parse<Round>(await fetch(`/api/recalc-rounds/${id}`))
}

export async function confirmRound(id: number): Promise<{ ok: boolean; message: string; round: Round }> {
  return postJson(`/api/recalc-rounds/${id}/confirm`, {})
}

export async function publishRound(id: number): Promise<{ ok: boolean; message: string; round: Round }> {
  return postJson(`/api/recalc-rounds/${id}/publish`, {})
}

export async function recomputeBaseline(
  id: number,
): Promise<{ ok: boolean; message: string; round: Round }> {
  return postJson(`/api/spec-baselines/${id}/recompute`, {})
}
