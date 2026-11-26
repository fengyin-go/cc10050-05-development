<template>
  <section class="workflow-panel baseline-rounds" data-testid="baseline-round-panel" aria-label="重算申请与基线发布">
    <div class="workflow-head">
      <div>
        <h3>重算申请轮次 · 口径快照 / 同次确认 / 发布一致</h3>
        <p class="workflow-tip">
          每一轮重算申请都冻结该轮真正采用的规则版本、规格口径、参与报价与排除报价；
          基线金额与参与报价必须来自同一次确认，发布价格与样本依据保持一致。
        </p>
      </div>
      <button class="btn" type="button" data-testid="refresh-rounds" @click="refreshAll">刷新申请</button>
    </div>

    <!-- 规格级基线（消费规格归一数据） -->
    <div class="baseline-cards" data-testid="spec-baseline-list">
      <article v-for="baseline in baselines" :key="baseline.id" class="baseline-card" :data-testid="`spec-baseline-${baseline.id}`">
        <div class="baseline-card-head">
          <strong>{{ baseline.归一规格 }}</strong>
          <span class="badge" :class="baseline.status === '已生效' ? 'ok' : 'warn'">{{ baseline.status }}</span>
        </div>
        <div class="muted-text">{{ baseline.商品标识 }} · {{ baseline.商品名称 }}</div>
        <div class="baseline-price-line">
          当前基线：<strong data-testid="spec-baseline-price">{{ money(baseline.基线价格) }}</strong> 元
        </div>
        <div class="muted-text">实际规格口径：{{ baseline.caliber?.包装形式 }} × {{ baseline.caliber?.数量 }} × {{ baseline.caliber?.单瓶容量ml }}ml</div>
        <div v-if="baseline.current_confirmation" class="basis-line" data-testid="baseline-confirmed-basis">
          已确认依据：{{ baseline.current_confirmation.quote_count }} 条报价 ·
          基线 {{ money(baseline.current_confirmation.baseline_price) }} ·
          排除金额 {{ money(baseline.current_confirmation.excluded_amount) }}
          <span class="muted-text">（{{ (baseline.current_confirmation.rule_batch ?? []).map((r: any) => `${r.rule_code}@${r.version}`).join('，') }}）</span>
        </div>
        <div class="mini-actions">
          <button
            class="btn primary"
            type="button"
            :data-testid="`recompute-baseline-${baseline.id}`"
            :disabled="recomputingId === baseline.id"
            @click="recomputeLatest(baseline.id)"
          >
            {{ recomputingId === baseline.id ? '复算中…' : '复算相同规格的报价数据（按最新规则）' }}
          </button>
        </div>
      </article>
    </div>

    <p v-if="actionMessage" class="success-text" role="status" data-testid="round-action-message">{{ actionMessage }}</p>
    <p v-if="errorMessage" class="error-text" role="alert" data-testid="round-error">{{ errorMessage }}</p>

    <div class="round-layout">
      <!-- 轮次列表 -->
      <aside class="round-list-col">
        <h4>重算申请（按轮次保存，不随筛选变化）</h4>
        <ul class="round-list" data-testid="round-list">
          <li v-if="!rounds.length" class="muted-text empty-rounds">暂无重算申请，可在规格归一器试判后生成</li>
          <li v-for="round in rounds" :key="round.id">
            <button
              type="button"
              class="round-list-item"
              :class="{ active: currentRound?.id === round.id }"
              :data-testid="`round-row-${round.id}`"
              :data-status="round.status"
              @click="openRound(round.id)"
            >
              <span class="round-code" :data-testid="`round-code-${round.id}`">{{ round.code }}</span>
              <span class="badge" :class="statusClass(round.status)">{{ round.status }}</span>
              <span class="round-meta">{{ round.商品标识 }} · {{ adoptedCaliberText(round) }}</span>
              <span class="round-meta">
                参与 {{ participatingOf(round).length }} 条 ·
                排除金额 {{ money(excludedAmountOf(round)) }}
              </span>
            </button>
          </li>
        </ul>
      </aside>

      <!-- 轮次详情：全部来自该轮快照 -->
      <div v-if="currentRound" class="round-detail" data-testid="round-detail" :data-round-id="currentRound.id">
        <div class="round-detail-head">
          <h4 data-testid="round-title">
            {{ currentRound.code }}
            <span class="badge" :class="statusClass(currentRound.status)" data-testid="round-status">{{ currentRound.status }}</span>
          </h4>
          <span class="muted-text">来源：{{ sourceText(currentRound.source) }} · 创建于 {{ formatTime(currentRound.created_at) }}</span>
        </div>

        <!-- 该轮采用的口径（冻结） -->
        <section class="snapshot-block" data-testid="round-caliber">
          <h5>该轮真正采用的规格口径（生成申请时冻结）</h5>
          <p class="caliber-text" data-testid="round-caliber-text">{{ adoptedCaliberText(currentRound) }}</p>
          <p>
            <span class="muted-text">采用规则批次：</span>
            <span
              v-for="ref in currentRound.adopted?.rule_batch ?? []"
              :key="`${ref.rule_code}-${ref.version}`"
              class="badge version"
              data-testid="round-rule-batch"
            >
              {{ ref.rule_code }}@{{ ref.version }}
            </span>
          </p>
          <details class="trace-details">
            <summary>查看规则条件快照</summary>
            <pre class="trace-json">{{ JSON.stringify(currentRound.adopted?.rule_batch ?? [], null, 2) }}</pre>
          </details>
        </section>

        <!-- 基线金额：只来自同一次确认 -->
        <section class="snapshot-block amount-block">
          <template v-if="currentRound.confirmation">
            <h5>基线金额（来自 {{ formatTime(currentRound.confirmation.confirmed_at) }} 的同一次确认）</h5>
            <div class="baseline-amount" data-testid="baseline-amount" :data-value="currentRound.confirmation.baseline_price">
              ￥{{ money(currentRound.confirmation.baseline_price) }}
            </div>
            <p class="muted-text">
              确认人 {{ currentRound.confirmation.confirmed_by }} ·
              参与报价 {{ currentRound.confirmation.quote_count }} 条 ·
              参与报价合计 {{ money(currentRound.confirmation.participating_amount) }} ·
              排除金额 {{ money(currentRound.confirmation.excluded_amount) }}
            </p>
          </template>
          <template v-else>
            <h5>基线金额（尚未确认）</h5>
            <div class="baseline-amount pending" data-testid="preview-amount">
              试算 ￥{{ money(currentRound.adopted?.preview_price) }}
            </div>
            <p class="muted-text">试算金额仅作预览；点击「确认本轮结果」后，金额与参与报价将来自同一次确认并冻结。</p>
          </template>

          <div class="confirm-actions">
            <button
              v-if="!currentRound.confirmation"
              class="btn primary"
              type="button"
              data-testid="confirm-round"
              :disabled="acting"
              @click="confirmCurrent"
            >
              确认本轮结果（金额与报价一并冻结）
            </button>
            <button
              v-if="currentRound.confirmation && !currentRound.publication"
              class="btn primary"
              type="button"
              data-testid="publish-round"
              :disabled="acting"
              @click="publishCurrent"
            >
              发布基线（价格与样本依据保持一致）
            </button>
            <button
              class="btn"
              type="button"
              data-testid="recompute-this-baseline"
              :disabled="acting"
              @click="recomputeLatest(currentRound.baseline_id ?? 1)"
            >
              按最新规则复算相同规格报价（另开一轮）
            </button>
          </div>
        </section>

        <!-- 参与报价：已确认后读 confirmation，否则读 adopted 预览 -->
        <section class="snapshot-block" data-testid="participating-quotes">
          <h5>
            参与计价报价（{{ participatingOf(currentRound).length }} 条）
            <span v-if="currentRound.confirmation" class="badge ok">同次确认快照</span>
          </h5>
          <table class="data-table compact">
            <thead>
              <tr><th>报价</th><th>站点</th><th>金额</th><th>实际规格</th><th>命中规则版本</th></tr>
            </thead>
            <tbody>
              <tr
                v-for="quote in participatingOf(currentRound)"
                :key="`p-${quote.quote_id ?? quote.报价编号}`"
                :data-testid="`participating-row-${quote.quote_id ?? quote.报价编号}`"
              >
                <td>{{ quote.报价编号 || `#${quote.quote_id}` }}</td>
                <td>{{ quote.站点名称 }}</td>
                <td :data-testid="`participating-amount-${quote.quote_id ?? quote.报价编号}`">￥{{ money(quote.报价金额) }}</td>
                <td>{{ quote.actual_spec }}</td>
                <td>{{ quote.matched_rule_ref }}</td>
              </tr>
              <tr v-if="!participatingOf(currentRound).length">
                <td colspan="5" class="empty-state">没有参与计价的报价</td>
              </tr>
            </tbody>
          </table>
        </section>

        <!-- 排除报价 + 排除金额 -->
        <section class="snapshot-block" data-testid="excluded-quotes">
          <h5>
            排除报价（{{ excludedOf(currentRound).length }} 条）·
            排除金额合计
            <strong class="excluded-total" data-testid="excluded-amount" :data-value="excludedAmountOf(currentRound)">
              ￥{{ money(excludedAmountOf(currentRound)) }}
            </strong>
          </h5>
          <table class="data-table compact">
            <thead>
              <tr><th>报价</th><th>金额</th><th>实际规格/规则</th><th>排除原因与版本追溯</th></tr>
            </thead>
            <tbody>
              <tr
                v-for="quote in excludedOf(currentRound)"
                :key="`e-${quote.quote_id ?? quote.报价编号}`"
                :data-testid="`excluded-row-${quote.quote_id ?? quote.报价编号}`"
              >
                <td>{{ quote.报价编号 || `#${quote.quote_id}` }}</td>
                <td :data-testid="`excluded-amount-${quote.quote_id ?? quote.报价编号}`">￥{{ money(quote.报价金额) }}</td>
                <td>
                  <div>{{ quote.actual_spec || '未识别' }}</div>
                  <div class="muted-text">{{ quote.matched_rule_ref || '无命中规则' }}</div>
                </td>
                <td class="trace-cell">
                  <span class="fail-text" data-testid="excluded-reason">{{ quote.reason }}</span>
                  <ul v-if="quote.rule_evaluations?.length" class="eval-visible-list">
                    <li v-for="ev in quote.rule_evaluations" :key="ev.rule">
                      <span :class="ev.命中 ? 'pass-text' : 'fail-text'">
                        {{ ev.命中 ? '✓' : '✗' }} {{ ev.rule }}
                      </span>
                      <span v-if="!ev.命中 && ev.failed_checks?.length" class="fail-text">
                        ：{{ ev.failed_checks[0].原因 || ev.failed_checks[0].维度 + '不符' }}
                      </span>
                    </li>
                  </ul>
                  <details class="trace-details">
                    <summary>追溯输入与规则版本</summary>
                    <pre class="trace-json">{{ JSON.stringify({ 输入: quote.input, 结构化: quote.normalized, 不符项: quote.mismatches, 规则判定: quote.rule_evaluations }, null, 2) }}</pre>
                  </details>
                </td>
              </tr>
              <tr v-if="!excludedOf(currentRound).length">
                <td colspan="4" class="empty-state">没有排除报价</td>
              </tr>
            </tbody>
          </table>
        </section>

        <!-- 发布信息：价格与样本依据一致 -->
        <section v-if="currentRound.publication" class="snapshot-block published-block" data-testid="published-info">
          <h5>已发布 · 价格与样本依据</h5>
          <p>
            发布价格：<strong data-testid="published-price">￥{{ money(currentRound.publication.baseline_price) }}</strong>
            <span
              class="badge"
              :class="currentRound.publication.consistent ? 'ok' : 'bad'"
              data-testid="basis-consistent"
            >
              {{ currentRound.publication.consistent ? '价格与样本依据一致' : '价格与样本依据不一致' }}
            </span>
          </p>
          <p class="muted-text">
            发布时间 {{ formatTime(currentRound.publication.published_at) }} ·
            样本依据报价ID [{{ (currentRound.publication.sample_basis_quote_ids ?? []).join(', ') }}] ·
            规则批次 {{ (currentRound.publication.rule_batch_refs ?? []).join('，') }}
          </p>
        </section>
      </div>

      <div v-else class="round-detail empty-detail" data-testid="round-detail-empty">
        <p>请选择左侧一轮重算申请，或从规格归一器的试判结果「到价格基线库打开重算申请」。</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  confirmRound,
  getRound,
  listRounds,
  listSpecBaselines,
  publishRound,
  recomputeBaseline,
  type JsonRecord,
  type Round,
} from '@/api/workflow'

const emit = defineEmits<{ changed: [] }>()
const route = useRoute()
const router = useRouter()

const baselines = ref<JsonRecord[]>([])
const rounds = ref<Round[]>([])
const currentRound = ref<Round | null>(null)
const acting = ref(false)
const recomputingId = ref<number | null>(null)
const actionMessage = ref('')
const errorMessage = ref('')

function money(value: unknown): string {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '0.00'
}

function formatTime(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function statusClass(status: string): string {
  if (status === '已发布' || status === '已生效') return 'ok'
  if (status === '已确认') return 'version'
  return 'warn'
}

function sourceText(source?: string): string {
  if (source === 'trial') return '上线前试判生成'
  if (source === 'recompute-latest') return '已确认基线按最新规则复算'
  if (source === 'baseline-action') return '基线行「重算基线」动作'
  return source || '手工发起'
}

function adoptedCaliberText(round: Round): string {
  return round.adopted?.caliber_text || round.caliber_text || round.归一规格 || '未记录口径'
}

function participatingOf(round: Round): JsonRecord[] {
  // 已确认后只展示同一次确认里的参与报价，杜绝金额与报价来自两次结果
  if (round.confirmation?.participating) return round.confirmation.participating
  return round.adopted?.participating ?? []
}

function excludedOf(round: Round): JsonRecord[] {
  if (round.confirmation?.excluded) return round.confirmation.excluded
  return round.adopted?.excluded ?? []
}

function excludedAmountOf(round: Round): number {
  const list = excludedOf(round)
  return Math.round(list.reduce((sum, q) => sum + (Number(q.报价金额) || 0), 0) * 100) / 100
}

async function loadBaselines() {
  baselines.value = await listSpecBaselines()
}

async function loadRounds(selectId?: number) {
  rounds.value = await listRounds()
  if (selectId != null) {
    await openRound(selectId)
  } else if (currentRound.value) {
    const fresh = rounds.value.find((r) => r.id === currentRound.value?.id)
    if (fresh) currentRound.value = fresh
  }
}

async function openRound(id: number) {
  errorMessage.value = ''
  try {
    currentRound.value = await getRound(id)
    if (!route.query.round || Number(route.query.round) !== id) {
      router.replace({ path: '/price_baseline', query: { ...route.query, round: String(id) } })
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重算申请读取失败'
  }
}

async function confirmCurrent() {
  if (!currentRound.value) return
  acting.value = true
  actionMessage.value = ''
  try {
    const result = await confirmRound(currentRound.value.id)
    if (!result.ok) throw new Error(result.message)
    currentRound.value = result.round
    actionMessage.value = result.message
    await loadRounds()
    emit('changed')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '确认失败'
  } finally {
    acting.value = false
  }
}

async function publishCurrent() {
  if (!currentRound.value) return
  acting.value = true
  actionMessage.value = ''
  try {
    const result = await publishRound(currentRound.value.id)
    if (!result.ok) throw new Error(result.message)
    currentRound.value = result.round
    actionMessage.value = result.message
    await Promise.all([loadRounds(), loadBaselines()])
    emit('changed')
    window.dispatchEvent(new CustomEvent('generic-baseline-reload'))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发布失败'
  } finally {
    acting.value = false
  }
}

async function recomputeLatest(baselineId: number) {
  recomputingId.value = baselineId
  acting.value = true
  errorMessage.value = ''
  actionMessage.value = ''
  try {
    const result = await recomputeBaseline(baselineId || 1)
    actionMessage.value = result.message
    await loadRounds(result.round.id)
    await loadBaselines()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复算失败'
  } finally {
    recomputingId.value = null
    acting.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadBaselines(), loadRounds()])
  if (route.query.round) await openRound(Number(route.query.round))
}

function onRoundsChanged() {
  void loadRounds()
}

function onVisibility() {
  if (document.visibilityState === 'visible') {
    const queryId = pickQueryId()
    if (queryId != null) void openRound(queryId)
  }
}

function pickQueryId(): number | null {
  for (const key of ['round', 'request', 'roundId', 'requestId', 'recalc', 'apply']) {
    const value = route.query[key]
    if (value != null) {
      const id = Number(Array.isArray(value) ? value[0] : value)
      if (!Number.isNaN(id)) return id
    }
  }
  return null
}

onMounted(async () => {
  await Promise.all([loadBaselines(), loadRounds()])
  const queryId = pickQueryId()
  if (queryId != null) await openRound(queryId)
  window.addEventListener('recalc-rounds-changed', onRoundsChanged)
  document.addEventListener('visibilitychange', onVisibility)
})

onBeforeUnmount(() => {
  window.removeEventListener('recalc-rounds-changed', onRoundsChanged)
  document.removeEventListener('visibilitychange', onVisibility)
})

watch(
  () => [route.query.round, route.query.request, route.query.requestId, route.query.roundId],
  () => {
    const queryId = pickQueryId()
    if (queryId != null) void openRound(queryId)
  },
)
</script>
