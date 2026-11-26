<template>
  <section class="workflow-panel spec-trial" data-testid="trial-panel" aria-label="上线前试判与规则更正">
    <div class="workflow-head">
      <div>
        <h3>上线前试判 · 重叠规则判定</h3>
        <p class="workflow-tip">
          选中同一规格（同商品、总量重叠）的两条规则，用具体样品试判命中规则与实际规格；
          单件与组合装即使总容量相同也必须区分。
        </p>
      </div>
      <button v-if="!showTrialModal" class="btn primary" data-testid="open-trial" type="button" @click="openTrial()">
        新增试判
      </button>
    </div>

    <!-- 重叠规则列表：勾选两条，或直接做规则更正 -->
    <div class="rule-pick-bar">
      <span>已选规则 {{ selectedRuleIds.length }} 条（建议选择同一规格的两条重叠规则）</span>
    </div>
    <table class="data-table rule-table" data-testid="spec-rule-table">
      <thead>
        <tr>
          <th class="col-check">选择</th>
          <th>规则编码 / 名称</th>
          <th>适用商品</th>
          <th>当前版本与口径</th>
          <th>判定条件（当前版本）</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="rule in rules"
          :key="rule.id"
          :data-testid="`rule-row-${rule.id}`"
          :data-rule-code="rule.rule_code"
          :data-active-version="rule.active_version"
        >
          <td class="col-check">
            <input
              type="checkbox"
              :data-testid="`rule-checkbox-${rule.id}`"
              :aria-label="`选择规则 ${rule.规则名称}`"
              :checked="selectedRuleIds.includes(rule.id)"
              @change="toggleRule(rule.id)"
            />
          </td>
          <td>
            <strong>{{ rule.rule_code }}</strong>
            <div>{{ rule.规则名称 }}</div>
            <span v-if="rule.重叠组" class="badge muted">重叠组：{{ rule.重叠组 }}</span>
          </td>
          <td>
            <div>{{ rule.商品标识 }}</div>
            <div class="muted-text">{{ rule.商品名称 }}</div>
          </td>
          <td>
            <span class="badge version" :data-testid="`rule-version-${rule.id}`">{{ rule.active_version }}</span>
            <div>{{ rule.归一规格 }}</div>
            <div class="muted-text">共 {{ rule.versions.length }} 个版本</div>
          </td>
          <td class="criteria-cell">
            <template v-for="(text, idx) in criteriaLines(rule)" :key="idx">
              <span class="criteria-chip">{{ text }}</span>
            </template>
          </td>
          <td>
            <button
              class="link"
              type="button"
              :data-testid="`correct-rule-${rule.id}`"
              @click="openCorrection(rule.id)"
            >
              规则更正
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- 试判工作台弹窗 -->
    <div v-if="showTrialModal" class="modal-backdrop" data-testid="trial-modal">
      <div class="modal modal-wide" role="dialog" aria-modal="true" aria-label="新增试判">
        <h3>新增试判 · 选择重叠规则与样品报价</h3>

        <div class="trial-rule-selects">
          <label class="create-field">
            <span>重叠规则一</span>
            <select v-model="pickA" data-testid="trial-rule-select-1" aria-label="重叠规则一">
              <option value="">请选择规则</option>
              <option v-for="rule in rules" :key="`a-${rule.id}`" :value="String(rule.id)">
                {{ rule.rule_code }} {{ rule.规则名称 }}（{{ rule.active_version }}）
              </option>
            </select>
          </label>
          <label class="create-field">
            <span>重叠规则二</span>
            <select v-model="pickB" data-testid="trial-rule-select-2" aria-label="重叠规则二">
              <option value="">请选择规则</option>
              <option v-for="rule in rules" :key="`b-${rule.id}`" :value="String(rule.id)">
                {{ rule.rule_code }} {{ rule.规则名称 }}（{{ rule.active_version }}）
              </option>
            </select>
          </label>
        </div>
        <div class="trial-check-row">
          <label v-for="rule in rules" :key="`m-${rule.id}`" class="inline-check">
            <input
              type="checkbox"
              :data-testid="`trial-rule-check-${rule.id}`"
              :checked="selectedRuleIds.includes(rule.id)"
              @change="toggleRule(rule.id)"
            />
            <span>{{ rule.rule_code }}@{{ rule.active_version }} {{ rule.规则名称 }}</span>
          </label>
        </div>

        <!-- 报价样品池：勾选已有报价 -->
        <div class="sample-pool">
          <div class="sub-head">
            <h4>报价样品池（按实际数据，不按总量推断）</h4>
            <div class="mini-actions">
              <button class="btn ghost" type="button" data-testid="pick-scenario-quotes" @click="pickScenarioPool">
                勾选场景三条报价
              </button>
            </div>
          </div>
          <table class="data-table compact" data-testid="quote-pool-table">
            <thead>
              <tr>
                <th class="col-check">参与试判</th>
                <th>编号</th>
                <th>商品</th>
                <th>源规格文本</th>
                <th>包装</th>
                <th>数量</th>
                <th>单瓶ml</th>
                <th>报价金额</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="quote in quotes" :key="quote.id" :data-testid="`quote-row-${quote.id}`">
                <td class="col-check">
                  <input
                    type="checkbox"
                    :data-testid="`quote-checkbox-${quote.id}`"
                    :aria-label="`选择报价 ${quote.报价编号 || quote.id}`"
                    :checked="checkedQuoteIds.includes(quote.id)"
                    @change="toggleQuote(quote.id)"
                  />
                </td>
                <td>{{ quote.报价编号 }}</td>
                <td>{{ quote.商品标识 }}</td>
                <td class="spec-text-cell">{{ quote.源规格文本 }}</td>
                <td>{{ quote.包装形式 }}</td>
                <td>{{ quote.数量 }}</td>
                <td>{{ quote.单瓶容量ml }}</td>
                <td data-testid="`quote-pool-amount-${quote.id}`">{{ money(quote.报价金额) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 手工录入具体样品 -->
        <div class="sample-form">
          <h4>录入具体样品报价</h4>
          <div class="sample-grid">
            <label class="create-field">
              <span>商品标识</span>
              <input v-model="sampleForm.商品标识" data-testid="trial-input-product" aria-label="商品标识" />
            </label>
            <label class="create-field">
              <span>源规格文本</span>
              <input v-model="sampleForm.源规格文本" data-testid="trial-input-spec-text" aria-label="源规格文本" placeholder="如：500ml 手工改标" />
            </label>
            <label class="create-field">
              <span>包装形式</span>
              <select v-model="sampleForm.包装形式" data-testid="trial-input-packaging" aria-label="包装形式">
                <option value="单件">单件（单瓶）</option>
                <option value="组合装">组合装（多瓶/套装）</option>
              </select>
            </label>
            <label class="create-field">
              <span>数量（瓶/件）</span>
              <input v-model.number="sampleForm.数量" type="number" min="1" data-testid="trial-input-quantity" aria-label="数量" />
            </label>
            <label class="create-field">
              <span>单瓶容量ml</span>
              <input v-model.number="sampleForm.单瓶容量ml" type="number" data-testid="trial-input-unit-ml" aria-label="单瓶容量ml" />
            </label>
            <label class="create-field">
              <span>报价金额（元）</span>
              <input v-model="sampleForm.报价金额" type="number" min="0" step="0.01" data-testid="trial-input-price" aria-label="报价金额" />
            </label>
            <label class="create-field">
              <span>标签状态</span>
              <select v-model="sampleForm.标签状态" data-testid="trial-input-label" aria-label="标签状态">
                <option value="">未填写</option>
                <option value="原厂标签">原厂标签</option>
                <option value="手工改标">手工改标</option>
              </select>
            </label>
            <div class="sample-add-action">
              <button class="btn" type="button" data-testid="add-trial-sample" @click="addSample">加入待试判样品</button>
            </div>
          </div>
          <div class="quick-samples">
            <button class="link" type="button" data-testid="fill-scenario-samples" @click="fillScenarioSamples">
              填入场景三笔：单瓶500ml/100元、手工改标仍单瓶/90元、两瓶各250ml/60元
            </button>
          </div>
          <ul v-if="manualSamples.length" class="sample-chip-list" data-testid="trial-sample-list">
            <li v-for="(sample, idx) in manualSamples" :key="sample._key" :data-testid="`trial-sample-chip-${idx}`">
              {{ sample.商品标识 }}｜{{ sample.源规格文本 }}｜{{ sample.包装形式 }}×{{ sample.数量 }}｜{{ sample.报价金额 }}元
              <button class="link danger" type="button" :data-testid="`remove-sample-${idx}`" @click="manualSamples.splice(idx, 1)">移除</button>
            </li>
          </ul>
        </div>

        <p v-if="errorMessage" class="error-text" role="alert" data-testid="trial-error">{{ errorMessage }}</p>

        <div class="page-actions modal-actions">
          <button class="btn" type="button" @click="showTrialModal = false">关闭</button>
          <button class="btn primary" type="button" data-testid="submit-trial" :disabled="running" @click="submitTrial">
            {{ running ? '试判中…' : '开始试判' }}
          </button>
        </div>

        <!-- 试判结果 -->
        <div v-if="trialResult" class="trial-result" data-testid="trial-result" :data-trial-id="trialResult.id">
          <h4>试判结果 #{{ trialResult.id }}：碰到的规则与实际规格</h4>
          <p class="muted-text">
            采用规则批次：
            <span v-for="ref in trialResult.rule_batch" :key="`${ref.rule_code}@${ref.version}`" class="badge version">
              {{ ref.rule_code }}@{{ ref.version }}
            </span>
          </p>
          <table class="data-table compact" data-testid="trial-result-table">
            <thead>
              <tr>
                <th>样品 / 报价</th>
                <th>命中规则（版本）</th>
                <th>实际规格</th>
                <th>判定</th>
                <th>不可比原因与追溯</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in trialResult.results"
                :key="item.key"
                :data-testid="`trial-result-row-${item.quote_id ?? item.key}`"
                :data-comparable="item.comparable ? 'true' : 'false'"
              >
                <td>
                  <div><strong>{{ item.报价编号 || '手工样品' }}</strong> ￥{{ money(item.报价金额) }}</div>
                  <div class="spec-text-cell">{{ item.input?.源规格文本 }}</div>
                  <div class="muted-text">
                    输入：{{ item.input?.商品标识 }} / {{ item.normalized?.包装形式 }} /
                    数量{{ item.normalized?.数量 }} / 单瓶{{ item.normalized?.单瓶容量ml }}ml
                  </div>
                </td>
                <td data-testid="hit-rules">
                  <div v-if="item.matched_rule_ref" class="hit-ref" data-testid="matched-rule-ref">
                    ✓ {{ item.matched_rule_ref }}
                  </div>
                  <div v-else class="miss-ref">无规则命中</div>
                  <ul class="eval-visible-list" data-testid="eval-summary">
                    <li v-for="ev in item.evaluations" :key="`v-${item.key}-${ev.rule_code}-${ev.rule_version}`">
                      <span :class="ev.命中 ? 'pass-text' : 'fail-text'">
                        {{ ev.命中 ? '✓' : '✗' }} {{ ev.rule_code }}@{{ ev.rule_version }}
                      </span>
                      <span v-if="!ev.命中 && ev.failed_checks?.length" class="fail-text">
                        ：{{ ev.failed_checks[0].原因 || ev.failed_checks[0].维度 + '不符' }}
                        <template v-if="ev.failed_checks.length > 1"> 等{{ ev.failed_checks.length }}项</template>
                      </span>
                    </li>
                  </ul>
                  <details class="trace-details">
                    <summary>全部候选规则判定（含版本）</summary>
                    <ul class="eval-list">
                      <li v-for="ev in item.evaluations" :key="`${item.key}-${ev.rule_code}-${ev.rule_version}`">
                        <span :class="ev.命中 ? 'pass-text' : 'fail-text'">
                          {{ ev.命中 ? '✓ 命中' : '✗ 未命中' }}
                        </span>
                        {{ ev.rule_code }}@{{ ev.rule_version }} {{ ev.规则名称 }}
                        <ul v-if="ev.failed_checks?.length" class="failed-checks">
                          <li v-for="(check, ci) in ev.failed_checks" :key="ci">
                            {{ check.维度 }}：{{ check.原因 }}
                          </li>
                        </ul>
                      </li>
                    </ul>
                  </details>
                </td>
                <td data-testid="actual-spec"><strong>{{ item.actual_spec }}</strong></td>
                <td>
                  <span v-if="item.comparable" class="badge ok" data-testid="comparable-badge">可比 · 参与计价</span>
                  <span v-else class="badge bad" data-testid="incomparable-badge">不可比 · 排除</span>
                </td>
                <td class="trace-cell">
                  <div v-if="item.verdict?.reason" class="fail-text" data-testid="incomparable-reason">{{ item.verdict.reason }}</div>
                  <details class="trace-details" :data-testid="`trace-${item.quote_id ?? item.key}`">
                    <summary>追溯：哪些输入与哪版规则导致</summary>
                    <pre class="trace-json">{{ traceJson(item) }}</pre>
                  </details>
                </td>
              </tr>
            </tbody>
          </table>

          <div class="create-round-bar">
            <button class="btn primary" type="button" data-testid="create-round" :disabled="creatingRound" @click="createRecalcRound">
              {{ creatingRound ? '生成中…' : '由这次判断生成重算申请' }}
            </button>
            <RouterLink
              v-if="createdRound"
              class="btn primary outline"
              :to="`/price_baseline?round=${createdRound.id}`"
              :data-testid="`goto-round-${createdRound.id}`"
            >
              到价格基线库打开重算申请 {{ createdRound.code }}
            </RouterLink>
            <span v-if="roundMessage" class="success-text" role="status">{{ roundMessage }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 规则更正弹窗：追加新版本，不改旧版本 -->
    <div v-if="showCorrectionModal" class="modal-backdrop" data-testid="correction-modal">
      <form class="modal modal-wide" @submit.prevent="submitCorrection">
        <h3>规则更正 · {{ correctingRule?.rule_code }} {{ correctingRule?.规则名称 }}</h3>
        <p class="workflow-tip">
          当前生效版本：
          <strong data-testid="correction-current-version">{{ correctingRule?.active_version }}</strong>
          。提交后追加新版本并启用，旧版本与已产生的重算申请快照保持不变。
        </p>
        <div class="correction-grid">
          <label class="create-field">
            <span>归一规格</span>
            <input v-model="correctionForm.归一规格" data-testid="correction-归一规格" />
          </label>
          <label class="create-field">
            <span>包装要求</span>
            <select v-model="correctionForm.包装要求" data-testid="correction-包装要求">
              <option value="不限">不限</option>
              <option value="单件">单件</option>
              <option value="组合装">组合装</option>
            </select>
          </label>
          <label class="create-field">
            <span>数量要求</span>
            <input v-model="correctionForm.数量要求" type="number" min="0" data-testid="correction-数量要求" />
          </label>
          <label class="create-field">
            <span>单瓶容量ml</span>
            <input v-model="correctionForm.单瓶容量ml" type="number" data-testid="correction-单瓶容量ml" />
          </label>
          <label class="create-field">
            <span>总容量ml</span>
            <input v-model="correctionForm.总容量ml" type="number" data-testid="correction-总容量ml" />
          </label>
          <label class="create-field">
            <span>标签要求</span>
            <select v-model="correctionForm.标签要求" data-testid="correction-标签要求">
              <option value="不限">不限（改标不改变实物规格）</option>
              <option value="原厂标签">原厂标签</option>
              <option value="手工改标">手工改标</option>
            </select>
          </label>
          <label class="create-field">
            <span>包含关键词（逗号分隔）</span>
            <input v-model="correctionForm.包含关键词" data-testid="correction-包含关键词" />
          </label>
          <label class="create-field">
            <span>排除关键词（逗号分隔）</span>
            <input v-model="correctionForm.排除关键词" data-testid="correction-排除关键词" />
          </label>
          <label class="create-field correction-note">
            <span>更正说明</span>
            <input v-model="correctionForm.版本说明" data-testid="correction-note" placeholder="说明这版更正解决的判定冲突" />
          </label>
        </div>
        <div class="quick-correct">
          <button
            class="btn ghost"
            type="button"
            data-testid="apply-relabel-correction"
            @click="applyRelabelCorrection"
          >
            套用更正：手工改标但仍为单瓶500ml → 取消排除关键词与标签限制
          </button>
        </div>
        <p v-if="correctionError" class="error-text" role="alert">{{ correctionError }}</p>
        <p v-if="correctionMessage" class="success-text" role="status" data-testid="correction-success">{{ correctionMessage }}</p>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCorrectionModal = false">取消</button>
          <button class="btn primary" type="submit" data-testid="submit-correction" :disabled="correcting">
            {{ correcting ? '提交中…' : '提交规则更正' }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import {
  correctSpecRule,
  createRound,
  listPriceQuotes,
  listSpecRules,
  runTrial,
  type PriceQuote,
  type Round,
  type SpecRule,
  type TrialRecord,
} from '@/api/workflow'

const props = defineProps<{ product?: string }>()
const emit = defineEmits<{ changed: [] }>()
const route = useRoute()

const rules = ref<SpecRule[]>([])
const quotes = ref<PriceQuote[]>([])
// 默认不预选：由运营显式“选中两条重叠规则”，避免点击选择时把已选项取消。
const selectedRuleIds = ref<number[]>([])
const checkedQuoteIds = ref<number[]>([])

const showTrialModal = ref(false)
const running = ref(false)
const creatingRound = ref(false)
const errorMessage = ref('')
const trialResult = ref<TrialRecord | null>(null)
const createdRound = ref<Round | null>(null)
const roundMessage = ref('')

const showCorrectionModal = ref(false)
const correctingRule = ref<SpecRule | null>(null)
const correcting = ref(false)
const correctionError = ref('')
const correctionMessage = ref('')

type ManualSample = Record<string, any> & { _key: string }
const manualSamples = ref<ManualSample[]>([])
const sampleForm = ref<Record<string, any>>({
  商品标识: 'SP-W500',
  源规格文本: '',
  包装形式: '单件',
  数量: 1,
  单瓶容量ml: 500,
  报价金额: '',
  标签状态: '',
})

const correctionForm = ref<Record<string, any>>({})

const pickA = computed<string>({
  get: () => (selectedRuleIds.value[0] != null ? String(selectedRuleIds.value[0]) : ''),
  set: (value) => {
    const a = Number(value)
    const b = selectedRuleIds.value[1]
    selectedRuleIds.value = value ? (b && b !== a ? [a, b] : [a]) : b ? [b] : []
  },
})
const pickB = computed<string>({
  get: () => (selectedRuleIds.value[1] != null ? String(selectedRuleIds.value[1]) : ''),
  set: (value) => {
    const b = Number(value)
    const a = selectedRuleIds.value[0]
    selectedRuleIds.value = value ? (a && a !== b ? [a, b] : [b]) : a ? [a] : []
  },
})

function money(value: unknown): string {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : String(value ?? '')
}

function criteriaLines(rule: SpecRule): string[] {
  const version = rule.versions?.find((v) => v.version === rule.active_version) ?? rule.versions?.[0]
  if (!version) return []
  const lines: string[] = []
  if (version.包装要求 && version.包装要求 !== '不限') lines.push(`包装=${version.包装要求}`)
  if (version.数量要求 !== '' && version.数量要求 != null) lines.push(`数量=${version.数量要求}`)
  if (version.单瓶容量ml) lines.push(`单瓶=${version.单瓶容量ml}ml`)
  if (version.总容量ml) lines.push(`总量=${version.总容量ml}ml`)
  if (version.标签要求 && version.标签要求 !== '不限') lines.push(`标签=${version.标签要求}`)
  for (const keyword of version.排除关键词 ?? []) lines.push(`排除「${keyword}」`)
  return lines
}

function toggleRule(id: number) {
  if (selectedRuleIds.value.includes(id)) {
    selectedRuleIds.value = selectedRuleIds.value.filter((x) => x !== id)
  } else {
    selectedRuleIds.value = [...selectedRuleIds.value, id]
  }
}

function toggleQuote(id: number) {
  if (checkedQuoteIds.value.includes(id)) {
    checkedQuoteIds.value = checkedQuoteIds.value.filter((x) => x !== id)
  } else {
    checkedQuoteIds.value = [...checkedQuoteIds.value, id]
  }
}

function pickScenarioPool() {
  checkedQuoteIds.value = quotes.value.map((q) => q.id)
}

function fillScenarioSamples() {
  manualSamples.value = [
    { _key: 's1', 商品标识: 'SP-W500', 源规格文本: '单瓶500ml', 包装形式: '单件', 数量: 1, 单瓶容量ml: 500, 报价金额: 100, 标签状态: '原厂标签' },
    { _key: 's2', 商品标识: 'SP-W500', 源规格文本: '500ml 手工改标（仍为单瓶）', 包装形式: '单件', 数量: 1, 单瓶容量ml: 500, 报价金额: 90, 标签状态: '手工改标' },
    { _key: 's3', 商品标识: 'SP-W500', 源规格文本: '两瓶各250ml', 包装形式: '组合装', 数量: 2, 单瓶容量ml: 250, 报价金额: 60, 标签状态: '原厂标签' },
  ]
}

function addSample() {
  errorMessage.value = ''
  if (sampleForm.value.报价金额 === '' || sampleForm.value.报价金额 == null) {
    errorMessage.value = '请填写报价金额'
    return
  }
  manualSamples.value.push({ ...sampleForm.value, _key: `m-${Date.now()}` })
  // 清空整张表单，避免“已加入”的样品在直接提交时被重复带入
  sampleForm.value = {
    商品标识: sampleForm.value.商品标识 || 'SP-W500',
    源规格文本: '',
    包装形式: '单件',
    数量: 1,
    单瓶容量ml: 500,
    报价金额: '',
    标签状态: '',
  }
}

function openTrial() {
  errorMessage.value = ''
  trialResult.value = null
  createdRound.value = null
  roundMessage.value = ''
  showTrialModal.value = true
}

async function loadAll() {
  try {
    const [ruleRows, quoteRows] = await Promise.all([
      listSpecRules(props.product ?? ''),
      listPriceQuotes(props.product ?? ''),
    ])
    rules.value = ruleRows
    quotes.value = quoteRows
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '规则读取失败'
  }
}

function currentFormSample(): Record<string, unknown> | null {
  const form = sampleForm.value
  const hasPrice = form.报价金额 !== '' && form.报价金额 != null
  const hasText = String(form.源规格文本 ?? '').trim() !== ''
  if (!hasPrice && !hasText) return null
  return { ...form }
}

async function submitTrial() {
  running.value = true
  errorMessage.value = ''
  try {
    if (!selectedRuleIds.value.length) throw new Error('请先选中至少一条规则（建议同一规格的两条重叠规则）')
    // 兼容“填完表单直接提交”：未点“加入”时也把当前表单作为一条样品。
    const pendingFormSample = currentFormSample()
    const samples = [
      ...manualSamples.value.map(({ _key, ...rest }) => rest),
      ...(pendingFormSample ? [pendingFormSample] : []),
    ]
    if (!samples.length && !checkedQuoteIds.value.length) {
      // 没有显式样品时，默认拿该商品报价池里的全部报价试判
      const payload: Record<string, unknown> = {
        rule_ids: selectedRuleIds.value,
        use_product_quotes: true,
        product: props.product ?? sampleForm.value.商品标识 ?? 'SP-W500',
        baseline_id: 1,
      }
      const result = await runTrial(payload)
      trialResult.value = result.trial
      createdRound.value = null
      return
    }
    const payload: Record<string, unknown> = {
      rule_ids: selectedRuleIds.value,
      quote_ids: checkedQuoteIds.value,
      samples,
      product: props.product ?? 'SP-W500',
      baseline_id: 1,
    }
    const result = await runTrial(payload)
    trialResult.value = result.trial
    createdRound.value = null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '试判失败'
  } finally {
    running.value = false
  }
}

async function createRecalcRound() {
  if (!trialResult.value) return
  creatingRound.value = true
  roundMessage.value = ''
  try {
    const result = await createRound(trialResult.value.id, 1)
    createdRound.value = result.round
    roundMessage.value = result.message
    emit('changed')
    window.dispatchEvent(new CustomEvent('recalc-rounds-changed'))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '生成重算申请失败'
  } finally {
    creatingRound.value = false
  }
}

function traceJson(item: TrialRecord['results'][number]): string {
  return JSON.stringify(
    {
      输入: item.input,
      结构化: item.normalized,
      采用规则: item.matched_rule_ref || '无',
      候选规则版本: (item.evaluations ?? []).map((ev) => ({
        规则: `${ev.rule_code}@${ev.rule_version}`,
        命中: ev.命中,
        未过项: ev.failed_checks?.map((c) => ({ 维度: c.维度, 要求: c.要求, 实际: c.实际, 原因: c.原因 })),
      })),
      与基线口径对比: item.verdict,
    },
    null,
    2,
  )
}

function openCorrection(ruleId: number) {
  const rule = rules.value.find((r) => r.id === ruleId) ?? null
  correctingRule.value = rule
  correctionError.value = ''
  correctionMessage.value = ''
  const version = rule?.versions?.find((v) => v.version === rule.active_version) ?? rule?.versions?.[0]
  correctionForm.value = {
    归一规格: version?.归一规格 ?? rule?.归一规格 ?? '',
    包装要求: version?.包装要求 ?? '不限',
    数量要求: version?.数量要求 ?? '',
    单瓶容量ml: version?.单瓶容量ml ?? '',
    总容量ml: version?.总容量ml ?? '',
    标签要求: version?.标签要求 ?? '不限',
    包含关键词: (version?.包含关键词 ?? []).join(','),
    排除关键词: (version?.排除关键词 ?? []).join(','),
    版本说明: version?.版本说明 ?? '',
  }
  showCorrectionModal.value = true
}

function applyRelabelCorrection() {
  correctionForm.value.排除关键词 = ''
  correctionForm.value.标签要求 = '不限'
  correctionForm.value.包装要求 = '单件'
  correctionForm.value.数量要求 = 1
  correctionForm.value.单瓶容量ml = 500
  correctionForm.value.总容量ml = 500
  correctionForm.value.版本说明 = '规则更正：500ml手工改标不改变包装与容量，仍按单瓶500ml参与单瓶基线'
}

async function submitCorrection() {
  if (!correctingRule.value) return
  correcting.value = true
  correctionError.value = ''
  correctionMessage.value = ''
  try {
    const result = await correctSpecRule(correctingRule.value.id, { ...correctionForm.value })
    if (!result.ok) throw new Error(result.message)
    correctionMessage.value = result.message
    await loadAll()
    emit('changed')
    window.dispatchEvent(new CustomEvent('spec-rules-changed'))
    setTimeout(() => {
      showCorrectionModal.value = false
      correctionMessage.value = ''
    }, 1200)
  } catch (error) {
    correctionError.value = error instanceof Error ? error.message : '规则更正失败'
  } finally {
    correcting.value = false
  }
}

function applyRouteHints() {
  const panel = route.query.panel ?? route.query.tab
  if (route.query.trial != null || panel === 'trial') {
    openTrial()
  }
  const correctId = route.query.correct
  if (correctId != null || panel === 'correction') {
    const id = Number(Array.isArray(correctId) ? correctId[0] : correctId ?? 1)
    if (!Number.isNaN(id)) openCorrection(id)
  }
}

onMounted(async () => {
  await loadAll()
  applyRouteHints()
  window.addEventListener('spec-rules-changed', loadAll)
})

watch(() => route.query, applyRouteHints)
</script>
