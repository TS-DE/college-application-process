<template>
  <div class="page">
    <h2 class="title">智能选志愿</h2>

    <!-- 第一步：高考信息 -->
    <el-card shadow="never">
      <template #header><b>第一步 · 高考信息</b></template>

      <div class="exam-tabs">
        <div class="tab on">普通类</div>
        <div class="tab disabled" @click="ElMessage.info('暂只支持普通类')">艺术类</div>
      </div>

      <el-form label-position="top" class="form-grid">
        <el-form-item label="考试地区">
          <!-- 0.11.1：省份下拉改为全国 31 省动态渲染 -->
          <el-select v-model="form.province" style="width: 100%" @change="onProvinceChange">
            <el-option v-for="p in provinceOptions" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
        <el-form-item label="科类">
          <!-- 0.11.1：科类跟随省份级联（北京=综合 / 河南=物理类·历史类 / 新疆=理科·文科） -->
          <el-select v-model="form.category" style="width: 100%" @change="onCategoryChange">
            <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="参考年份">
          <el-select v-model="form.year" style="width: 100%" @change="onDimensionChange">
            <el-option v-for="y in yearOptions" :key="y" :label="y" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="成绩类型">
          <el-radio-group v-model="form.level" @change="onLevelChange">
            <el-radio value="ben">本科</el-radio>
            <el-radio value="zhuan">专科</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>

      <!-- 3+1+2 省份才需要选具体科目；3+3 省份只有「综合」，不显示这一块 -->
      <div v-if="needSubjectPick" class="subject-row">
        <span class="label">高考科目（3 + 1 + 2）</span>
        <div class="pills">
          <button
            v-for="s in SUBJECTS"
            :key="s"
            type="button"
            class="pill"
            :class="{ on: subjects.includes(s), disabled: isDisabled(s) }"
            @click="toggleSubject(s)"
          >
            {{ s }}
          </button>
        </div>
        <div class="muted">请选择首选科目（物理 / 历史）及最多 2 门再选科目</div>
      </div>

      <el-form label-position="top" class="form-grid">
        <el-form-item label="预估分数">
          <el-input v-model="form.score" type="number" :placeholder="scorePlaceholder" @change="autoCheck" />
          <div v-if="scoreError" class="err">{{ scoreError }}</div>
        </el-form-item>
        <el-form-item label="对应位次">
          <el-input v-model="form.rank" type="number" placeholder="填入分数后自动换算" />
          <div class="muted">填入分数后自动换算，可手动修改</div>
        </el-form-item>
        <el-form-item label="填报批次">
          <div class="batch-wrap">
            <el-select v-model="form.batch" placeholder="请完善信息" style="width: 160px" @change="onBatchChange">
              <el-option label="本科批" value="本科批" />
              <el-option label="专科批" value="专科批" />
            </el-select>
            <el-tag v-if="batchAuto" type="warning" size="small">推荐</el-tag>
          </div>
        </el-form-item>
      </el-form>

      <div v-if="rankRange" class="rank-tip">
        分数对应 <b>{{ form.year }} 年</b> 排名区间为 <b>{{ rankRange }}</b> 名，可手动输入
      </div>

      <el-button type="primary" class="full" :loading="loading" @click="onRecommend">
        智能选志愿
      </el-button>
    </el-card>

    <!-- 第二步：推荐结果 -->
    <div v-if="result" class="result">
      <el-card v-for="tier in tiers" :key="tier.key" shadow="never" class="tier-card">
        <template #header>
          <span :class="['tier-tag', tier.key]">{{ tier.label }}</span>
          <span class="muted">共 {{ result[tier.key].length }} 条</span>
        </template>
        <el-table :data="result[tier.key]" size="small" max-height="420">
          <el-table-column prop="university_name" label="院校" min-width="160" />
          <el-table-column prop="major_name" label="专业" min-width="160" />
          <el-table-column prop="min_score" label="最低分" width="90" />
          <el-table-column prop="min_rank" label="最低位次" width="100" />
          <el-table-column prop="rank_diff" label="位次差" width="90" />
          <el-table-column label="概率" width="90">
            <template #default="{ row }">
              {{ row.probability != null ? row.probability + '%' : '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="school_province" label="省份" width="90" />
          <el-table-column prop="tuition" label="学费" width="90" />
        </el-table>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { controlLines, metaOptions, recommend as recommendApi, scoreCheck } from '@/api/recommend'
import type { RecommendResult } from '@/types/recommend'

const SUBJECTS = ['物理', '化学', '生物', '政治', '历史', '地理']
const FIRST_SUBJECTS = ['物理', '历史']

const form = reactive({
  province: '河南',
  // 0.11.1：科类由下拉框显式选择（不再只靠首选科目推导），默认河南为物理类
  category: '物理类',
  year: 2025,
  level: '' as '' | 'ben' | 'zhuan',
  score: '',
  rank: '',
  batch: ''
})

const subjects = ref<string[]>([])
const bounds = ref<Record<string, { min: number; max: number }>>({})
const fullScore = ref(750)
const scoreError = ref('')
const rankRange = ref('')
const batchAuto = ref(false)
const loading = ref(false)
const result = ref<RecommendResult | null>(null)

// ---- 0.11.1 全国省份 / 科类级联 ----
const provinceOptions = ref<string[]>(['河南'])
const categoriesMap = ref<Record<string, string[]>>({ 河南: ['物理类', '历史类'] })
const yearOptions = ref<number[]>([2025])

/** 当前省份支持的科类列表（北京 → ['综合']；河南 → ['物理类','历史类']） */
const categoryOptions = computed(() => categoriesMap.value[form.province] || [])

/** 是否为 3+3 省份（只有「综合」），这类省份不需要选 3+1+2 的具体科目 */
const needSubjectPick = computed(
  () => categoryOptions.value.length > 1 || categoryOptions.value.includes('物理类')
)

const tiers = [
  { key: 'chong' as const, label: '冲' },
  { key: 'wen' as const, label: '稳' },
  { key: 'bao' as const, label: '保' }
]

/** 实际提交给后端的科类：以「科类」下拉为准；老高考年份做一次写法映射 */
const category = computed(() => {
  const c = form.category || ''
  if (form.year >= 2025) return c
  if (c === '物理类') return '理科'
  if (c === '历史类') return '文科'
  return c
})

const scorePlaceholder = computed(() => {
  const b = form.level ? bounds.value[form.level] : null
  return b ? `请输入分数${b.min}-${b.max}` : `请输入分数1-${fullScore.value}`
})

function isDisabled(s: string) {
  if (subjects.value.includes(s)) return false
  if (subjects.value.length >= 3) return true
  if (s === '物理' && subjects.value.includes('历史')) return true
  if (s === '历史' && subjects.value.includes('物理')) return true
  return false
}

function toggleSubject(s: string) {
  const i = subjects.value.indexOf(s)
  if (i >= 0) subjects.value.splice(i, 1)
  else {
    if (subjects.value.length >= 3) {
      ElMessage.warning('高考科目最多选择 3 门')
      return
    }
    subjects.value.push(s)
  }
  // 首选科目变化时，把「科类」下拉同步过去，避免两处不一致
  if (FIRST_SUBJECTS.includes(s)) {
    const want = form.year >= 2025 ? `${s}类` : s === '物理' ? '理科' : '文科'
    if (categoryOptions.value.includes(want)) form.category = want
  }
  loadLines()
}

// ---------------- 0.11.1 省份 / 科类级联 ----------------

/** 切换省份：重置科类为该省第一个，清空旧的位次/批次/分数校验态 */
function onProvinceChange() {
  const cats = categoryOptions.value
  form.category = cats[0] || ''
  // 3+3 省份只有「综合」，清掉 3+1+2 科目选择，避免提交无意义的选科
  if (!needSubjectPick.value) subjects.value = []
  else if (form.category === '物理类' && !subjects.value.includes('物理')) subjects.value = ['物理']
  else if (form.category === '历史类' && !subjects.value.includes('历史')) subjects.value = ['历史']

  form.rank = ''
  form.batch = ''
  form.score = ''
  batchAuto.value = false
  rankRange.value = ''
  scoreError.value = ''
  result.value = null
  loadLines()
}

/** 切换科类：反向同步首选科目，并重新拉批次线 */
function onCategoryChange() {
  const c = form.category
  if (c === '物理类') subjects.value = ['物理', ...subjects.value.filter((s) => !FIRST_SUBJECTS.includes(s))]
  else if (c === '历史类') subjects.value = ['历史', ...subjects.value.filter((s) => !FIRST_SUBJECTS.includes(s))]
  else if (!needSubjectPick.value) subjects.value = []

  form.rank = ''
  rankRange.value = ''
  scoreError.value = ''
  loadLines()
  autoCheck()
}

/** 拉取全国省份与「省份 → 科类」映射，初始化级联下拉 */
async function loadOptions() {
  try {
    const res = await metaOptions(form.province)
    provinceOptions.value = res.provinces?.length ? res.provinces : provinceOptions.value
    categoriesMap.value = res.categories_map || categoriesMap.value
    yearOptions.value = res.years?.length ? res.years : [2025]
    const cats = categoriesMap.value[form.province] || []
    if (cats.length && !cats.includes(form.category)) form.category = cats[0]
    if (!needSubjectPick.value) subjects.value = []
  } catch {
    // 拉取失败时保留默认值（河南 / 物理类），不影响主流程
  }
}

async function loadLines() {
  try {
    const res = await controlLines(form.province, form.year, category.value || '物理类')
    bounds.value = res.bounds || {}
    fullScore.value = res.full_score || 750
  } catch {
    bounds.value = {}
  }
}

function onDimensionChange() {
  form.rank = ''
  form.batch = ''
  batchAuto.value = false
  rankRange.value = ''
  loadLines()
}

function onLevelChange() {
  batchAuto.value = false
  autoCheck()
}

function onBatchChange() {
  batchAuto.value = false
  autoCheck()
}

async function autoCheck() {
  scoreError.value = ''
  const n = Number(form.score)
  if (!form.score) {
    form.rank = ''
    return
  }
  if (!Number.isFinite(n) || n < 1 || n > fullScore.value) {
    scoreError.value = `请输入 1 - ${fullScore.value} 之间的分数`
    return
  }
  const b = form.level ? bounds.value[form.level] : null
  if (b && (n < b.min || n > b.max)) {
    scoreError.value = `${form.level === 'ben' ? '本科' : '专科'}成绩类型可填写 ${b.min} - ${b.max} 分`
    form.rank = ''
    return
  }
  if (!category.value) {
    scoreError.value = '请先选择科类'
    return
  }
  try {
    const res = await scoreCheck({
      province: form.province,
      year: form.year,
      category: category.value,
      score: n
    })
    if (res.below_all) {
      ElMessage.warning('该分数未达到本省最低批次线，请检查输入')
      form.rank = ''
      return
    }
    form.rank = String(res.rank)
    form.batch = res.recommend_batch || form.batch
    batchAuto.value = true
    rankRange.value = res.rank_range || ''
  } catch (e: any) {
    scoreError.value = e?.message || '换算失败'
  }
}

async function onRecommend() {
  if (!category.value) {
    ElMessage.warning('请先选择科类')
    return
  }
  if (!form.score || !form.rank || !form.batch) {
    ElMessage.warning('请填写完整：分数、位次、批次')
    return
  }
  loading.value = true
  try {
    result.value = await recommendApi({
      province: form.province,
      year: form.year,
      category: category.value,
      batch: form.batch,
      score: Number(form.score),
      rank: Number(form.rank),
      filters: { subject_selected: subjects.value.filter((s) => !FIRST_SUBJECTS.includes(s)) },
      use_ai: false
    })
    if (!result.value?.chong?.length && !result.value?.wen?.length && !result.value?.bao?.length) {
      ElMessage.info('没有匹配的志愿，试试放宽条件')
    }
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadOptions()
  loadLines()
})
</script>

<style scoped>
.title {
  margin: 0 0 14px;
}
.exam-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 16px;
}
.tab {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 14px;
  cursor: pointer;
  font-size: 14px;
}
.tab.on {
  border-color: var(--primary);
  background: var(--primary-light);
  color: var(--primary);
  font-weight: 600;
}
.tab.disabled {
  opacity: 0.55;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0 16px;
}
.subject-row {
  margin-bottom: 14px;
}
.subject-row .label {
  font-size: 13px;
  color: var(--text-sub);
}
.pills {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin: 8px 0 6px;
}
.pill {
  border: 1px solid var(--border);
  background: #fff;
  border-radius: 18px;
  padding: 6px 16px;
  font-size: 13px;
  cursor: pointer;
}
.pill.on {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}
.pill.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.batch-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}
.full {
  width: 100%;
  margin-top: 8px;
}
.err {
  color: var(--danger);
  font-size: 12px;
}
.rank-tip {
  background: #fff7ed;
  border: 1px solid #ffedd5;
  border-radius: var(--radius-sm);
  padding: 10px 14px;
  font-size: 13px;
  margin-bottom: 12px;
}
.rank-tip b {
  color: #ea580c;
}
.result {
  margin-top: 16px;
  display: grid;
  gap: 14px;
}
.tier-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  color: #fff;
  font-size: 13px;
  margin-right: 8px;
}
.tier-tag.chong {
  background: #ef4444;
}
.tier-tag.wen {
  background: #10b981;
}
.tier-tag.bao {
  background: #3b82f6;
}
@media (max-width: 900px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
