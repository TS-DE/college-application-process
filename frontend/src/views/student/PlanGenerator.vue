<template>
  <div class="page plan-page">
    <div class="topbar">
      <el-button text @click="$router.push('/ai-chat')">← 返回 AI 助手</el-button>
      <div class="title-wrap">
        <h2>🤖 智能生成志愿方案</h2>
        <p class="muted">
          AI 先出一版初稿，你改完再定稿 —— 最终决定权始终在你手上。
        </p>
      </div>
      <el-tag size="small" type="info">人机协同 · 可反复调整</el-tag>
    </div>

    <el-card shadow="never" class="steps-card">
      <el-steps :active="step" align-center finish-status="success">
        <el-step title="填写信息" description="分数 / 科类 / 偏好" />
        <el-step title="人工确认" description="看初稿、提意见" />
        <el-step title="最终方案" description="导出或保存" />
      </el-steps>
    </el-card>

    <!-- ================= 步骤一：填信息 ================= -->
    <el-card v-if="step === 0" shadow="never">
      <el-form label-position="top" class="form-grid">
        <el-form-item label="考生省份">
          <el-select v-model="form.province" style="width: 100%" @change="onProvinceChange">
            <el-option v-for="p in provinces" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
        <el-form-item label="科类">
          <el-select v-model="form.category" style="width: 100%">
            <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="高考分数">
          <el-input v-model.number="form.score" placeholder="例如 600" @keyup.enter="onStart">
            <template #append>分</template>
          </el-input>
        </el-form-item>
        <el-form-item label="参考年份">
          <el-select v-model="form.year" style="width: 100%">
            <el-option v-for="y in years" :key="y" :label="y" :value="y" />
          </el-select>
        </el-form-item>
      </el-form>

      <el-form-item label="有什么特别想要的？（选填）">
        <el-input
          v-model="form.preferences"
          type="textarea"
          :rows="2"
          maxlength="200"
          show-word-limit
          placeholder="例如：想去江浙沪、想学计算机、不想去太冷的地方"
        />
      </el-form-item>

      <div class="actions">
        <el-button
          type="primary"
          size="large"
          :loading="starting"
          @click="onStart"
        >
          生成初稿
        </el-button>
        <span class="muted small">AI 会结合你的分数、位次与画像，生成冲稳保三档方案</span>
      </div>
    </el-card>

    <!-- ================= 步骤二：初稿 + 人机干预 ================= -->
    <template v-else-if="step === 1">
      <el-card shadow="never" class="draft-card">
        <template #header>
          <div class="card-head">
            <b>初步方案</b>
            <span class="muted small">
              位次 {{ draftRank }} · 共 {{ draftCount }} 条
            </span>
          </div>
        </template>

        <el-alert
          class="hitl-tip"
          type="warning"
          :closable="false"
          show-icon
          title="AI 为您生成了初步方案，请问有哪些地方需要修改？"
          description="可以直接删掉不喜欢的学校，也可以加条件。确认后才生成最终版。"
        />

        <p v-if="summary" class="summary">{{ summary }}</p>

        <div v-for="t in TIERS" :key="t.key" class="tier-block">
          <div class="tier-head">
            <el-tag :type="t.type" effect="dark" size="small">{{ t.label }}</el-tag>
            <span class="muted small">{{ (draftPlan[t.key] || []).length }} 条</span>
          </div>
          <el-table :data="draftPlan[t.key] || []" size="small" border stripe>
            <el-table-column prop="university_name" label="院校" min-width="150" />
            <el-table-column prop="major_name" label="专业" min-width="130" />
            <el-table-column prop="school_province" label="地区" width="80" />
            <el-table-column prop="min_score" label="最低分" width="80" align="right" />
            <el-table-column prop="min_rank" label="最低位次" width="100" align="right">
              <template #default="{ row }">{{ fmtRank(row.min_rank) }}</template>
            </el-table-column>
            <el-table-column prop="probability" label="概率" width="80" align="right">
              <template #default="{ row }">
                <span v-if="row.probability != null">{{ row.probability }}%</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="学费" width="90" align="right">
              <template #default="{ row }">{{ fmtTuition(row.tuition) }}</template>
            </el-table-column>
          </el-table>
        </div>
      </el-card>

      <el-card shadow="never" class="feedback-card">
        <template #header><b>告诉我要改什么</b></template>
        <el-input
          v-model="feedback"
          type="textarea"
          :rows="3"
          maxlength="500"
          show-word-limit
          placeholder="例如：不想去东北、把北京的学校都去掉、想学医、学费别超过 6000"
        />
        <div class="quick-tags">
          <el-check-tag
            v-for="q in QUICK_FEEDBACK"
            :key="q"
            :checked="feedback.includes(q)"
            @change="toggleQuick(q)"
          >
            {{ q }}
          </el-check-tag>
        </div>
        <div class="actions">
          <el-button @click="onReset">重新填写</el-button>
          <el-button type="primary" :loading="resuming" @click="onResume">
            {{ feedback.trim() ? '确认修改并生成最终版' : '不改了，直接生成最终版' }}
          </el-button>
        </div>
      </el-card>
    </template>

    <!-- ================= 步骤三：终稿 ================= -->
    <template v-else>
      <el-card shadow="never">
        <template #header>
          <div class="card-head">
            <b>最终方案</b>
            <div class="head-actions">
              <el-tag type="success" size="small">共 {{ finalCount }} 条</el-tag>
              <el-button size="small" @click="onExport">导出 CSV</el-button>
              <el-button size="small" @click="onReset">再来一次</el-button>
            </div>
          </div>
        </template>

        <el-alert
          v-if="note"
          class="note"
          :type="changes.length ? 'success' : 'info'"
          :closable="false"
          show-icon
          :title="note"
        />

        <div v-if="changes.length" class="changes">
          <div class="changes-title">本次调整（{{ changes.length }} 条）</div>
          <el-tag
            v-for="(c, i) in changes.slice(0, 12)"
            :key="i"
            type="info"
            size="small"
            class="change-tag"
          >
            {{ c.university }} · {{ c.reason }}
          </el-tag>
          <span v-if="changes.length > 12" class="muted small">
            等 {{ changes.length }} 条
          </span>
        </div>

        <div v-for="t in TIERS" :key="t.key" class="tier-block">
          <div class="tier-head">
            <el-tag :type="t.type" effect="dark" size="small">{{ t.label }}</el-tag>
            <span class="muted small">{{ (finalPlan[t.key] || []).length }} 条</span>
          </div>
          <el-table :data="finalPlan[t.key] || []" size="small" border stripe>
            <el-table-column prop="university_name" label="院校" min-width="150" />
            <el-table-column prop="major_name" label="专业" min-width="130" />
            <el-table-column prop="school_province" label="地区" width="80" />
            <el-table-column prop="min_score" label="最低分" width="80" align="right" />
            <el-table-column prop="min_rank" label="最低位次" width="100" align="right">
              <template #default="{ row }">{{ fmtRank(row.min_rank) }}</template>
            </el-table-column>
            <el-table-column prop="probability" label="概率" width="80" align="right">
              <template #default="{ row }">
                <span v-if="row.probability != null">{{ row.probability }}%</span>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="学费" width="90" align="right">
              <template #default="{ row }">{{ fmtTuition(row.tuition) }}</template>
            </el-table-column>
          </el-table>
        </div>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { metaOptions } from '@/api/recommend'
import {
  resumePlan,
  startPlan,
  type PlanChange,
  type PlanItem,
  type PlanTiers
} from '@/api/plan'

const TIERS = [
  { key: 'chong' as const, label: '冲', type: 'danger' as const },
  { key: 'wen' as const, label: '稳', type: 'warning' as const },
  { key: 'bao' as const, label: '保', type: 'success' as const }
]

const QUICK_FEEDBACK = [
  '不想去东北',
  '只要江浙沪',
  '想学计算机',
  '想学医',
  '学费别超过 6000'
]

// ---------------- 表单 ----------------
const form = reactive({
  province: '河南',
  category: '物理类',
  score: 600 as number | null,
  year: 2025,
  preferences: ''
})

const provinces = ref<string[]>(['河南'])
const categoriesMap = ref<Record<string, string[]>>({ 河南: ['物理类', '历史类'] })
const years = ref<number[]>([2025])

const categoryOptions = computed(() => categoriesMap.value[form.province] || [])

function onProvinceChange() {
  form.category = categoryOptions.value[0] || ''
}

// ---------------- 流程状态 ----------------
/** 0=填信息 1=人机确认 2=终稿 */
const step = ref(0)
const starting = ref(false)
const resuming = ref(false)

const threadId = ref('')
const draftRank = ref<number | null>(null)
const draftPlan = ref<PlanTiers>({})
const summary = ref('')
const feedback = ref('')
const finalPlan = ref<PlanTiers>({})
const changes = ref<PlanChange[]>([])
const note = ref('')

const draftCount = computed(
  () => TIERS.reduce((n, t) => n + (draftPlan.value[t.key]?.length || 0), 0)
)
const finalCount = computed(
  () => TIERS.reduce((n, t) => n + (finalPlan.value[t.key]?.length || 0), 0)
)

// ---------------- 动作 ----------------
async function onStart() {
  if (!form.score) {
    ElMessage.warning('请先填写分数')
    return
  }
  starting.value = true
  try {
    const res = await startPlan({
      province: form.province,
      category: form.category,
      score: Number(form.score),
      year: form.year,
      preferences: form.preferences
    })
    threadId.value = res.thread_id
    draftRank.value = res.rank
    draftPlan.value = res.draft_plan || {}
    summary.value = res.summary || ''
    feedback.value = ''
    step.value = 1
    ElMessage.success(`初稿已生成（${draftCount.value} 条），请确认是否需要修改`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '生成初稿失败，请稍后重试')
  } finally {
    starting.value = false
  }
}

async function onResume() {
  if (!threadId.value) return
  resuming.value = true
  try {
    const res = await resumePlan(threadId.value, feedback.value.trim())
    finalPlan.value = res.final_plan || {}
    changes.value = res.changes || []
    note.value = res.note || ''
    if (res.rank) draftRank.value = res.rank
    step.value = 2
    ElMessage.success(`最终方案已生成（${finalCount.value} 条）`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '重新规划失败，请稍后重试')
  } finally {
    resuming.value = false
  }
}

function onReset() {
  step.value = 0
  threadId.value = ''
  draftPlan.value = {}
  finalPlan.value = {}
  changes.value = []
  note.value = ''
  feedback.value = ''
}

function toggleQuick(q: string) {
  if (feedback.value.includes(q)) {
    feedback.value = feedback.value.replace(q, '').replace(/[，,]\s*[，,]/g, '，').trim()
  } else {
    feedback.value = (feedback.value ? feedback.value.replace(/[，,]\s*$/, '') + '，' : '') + q
  }
}

// ---------------- 展示辅助 ----------------
function fmtRank(v?: number | null) {
  if (v == null) return '—'
  return Math.round(Number(v)).toLocaleString()
}

function fmtTuition(v?: number | null) {
  if (v === 0) return '免学费'
  if (v == null) return '—'
  return `${v} 元/年`
}

function onExport() {
  const rows: string[][] = [['档位', '院校', '专业', '地区', '最低分', '最低位次', '概率', '学费']]
  TIERS.forEach((t) => {
    (finalPlan.value[t.key] || []).forEach((it: PlanItem) => {
      rows.push([
        t.label,
        it.university_name || '',
        it.major_name || '',
        it.school_province || '',
        String(it.min_score ?? ''),
        it.min_rank != null ? String(Math.round(Number(it.min_rank))) : '',
        it.probability != null ? `${it.probability}%` : '',
        it.tuition != null ? String(it.tuition) : ''
      ])
    })
  })
  // BOM 让 Excel 正确识别 UTF-8 中文
  const csv = '\uFEFF' + rows.map((r) => r.map((c) => `"${c}"`).join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `志愿方案_${form.province}_${form.score}分.csv`
  a.click()
  URL.revokeObjectURL(a.href)
  ElMessage.success('已导出 CSV')
}

// ---------------- 初始化 ----------------
onMounted(async () => {
  try {
    const res = await metaOptions(form.province)
    if (res.provinces?.length) provinces.value = res.provinces
    if (res.categories_map) categoriesMap.value = res.categories_map
    if (res.years?.length) years.value = res.years
    const cats = categoriesMap.value[form.province] || []
    if (cats.length && !cats.includes(form.category)) form.category = cats[0]
  } catch {
    // 拉不到就用默认河南/物理类，不影响主流程
  }
})
</script>

<style scoped>
.plan-page {
  max-width: 1120px;
}
.topbar {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.title-wrap h2 {
  margin: 0 0 4px;
  font-size: 20px;
}
.title-wrap p {
  margin: 0;
  font-size: 13px;
}
.steps-card {
  margin-bottom: 16px;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0 16px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.small {
  font-size: 12.5px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.hitl-tip {
  margin-bottom: 12px;
}
.summary {
  color: var(--text-sub);
  font-size: 13px;
  margin: 0 0 12px;
  line-height: 1.7;
}
.tier-block {
  margin-bottom: 18px;
}
.tier-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.feedback-card {
  margin-top: 16px;
}
.quick-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 10px 0 4px;
}
.note {
  margin-bottom: 12px;
}
.changes {
  margin-bottom: 14px;
}
.changes-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}
.change-tag {
  margin: 0 6px 6px 0;
}
</style>
