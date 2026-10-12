<template>
  <div class="page">
    <div class="head">
      <div>
        <h2 class="title">RAG 量化评估</h2>
        <p class="sub">评估先行 · 诊断驱动 · 数据闭环：一键评估 → 可视化 → 自动诊断 → 参数自调优</p>
      </div>
      <div class="head-actions">
        <el-button @click="loadHistory">刷新历史</el-button>
        <el-button @click="loadChanges">变更日志</el-button>
      </div>
    </div>

    <!-- 顶部：数据集 + 配置覆盖 + 一键运行 -->
    <el-card shadow="never" class="block">
      <template #header><b>运行评估</b></template>
      <div class="run-bar">
        <el-select v-model="datasetId" placeholder="选择评估数据集" style="width: 280px" clearable>
          <el-option v-for="d in datasets" :key="d.dataset_id" :label="`${d.filename}（${d.sample_count} 条）`"
                     :value="d.dataset_id" />
        </el-select>
        <el-input-number v-model.number="overrides.TOP_K_FOR_EVAL" :min="1" :max="20" controls-position="right"
                         style="width: 150px" />
        <span class="tip">top_k</span>
        <el-input-number v-model.number="overrides.SIM_THRESHOLD" :min="0.1" :max="0.95" :step="0.05" :precision="2"
                         controls-position="right" style="width: 150px" />
        <span class="tip">相似度阈值</span>
        <el-checkbox v-model="overrides.LLM_METRICS_ENABLED">启用 LLM 打分指标</el-checkbox>
        <el-button type="primary" :loading="running" @click="runEvalNow">一键运行评估</el-button>
        <el-upload :show-file-list="false" accept=".json,.csv" :http-request="onUpload" class="inline-upload">
          <el-button>上传数据集</el-button>
        </el-upload>
      </div>
      <div v-if="result" class="summary">
        <el-tag :type="gradeTagType(result.grade)" size="large">综合评级：{{ result.grade }}</el-tag>
        <span class="meta">样本 {{ result.dataset_size }} 条 · 耗时 {{ result.duration_sec }}s · 报告 {{ result.report_id }}</span>
      </div>
    </el-card>

    <!-- 指标卡片 -->
    <div v-if="result" class="cards">
      <el-card v-for="m in metricCards" :key="m.key" shadow="never" class="stat">
        <div class="num">{{ fmt(result.aggregate[m.key]) }}</div>
        <div class="lbl">{{ m.label }}</div>
        <el-progress :percentage="pct(result.aggregate[m.key])" :stroke-width="4" :show-text="false" />
      </el-card>
    </div>

    <!-- 图表：柱状图 / 雷达图 / 趋势图 -->
    <div v-if="result" class="charts">
      <el-card shadow="never" class="block">
        <template #header><b>指标对比（当前 vs 上一次）</b></template>
        <div ref="barRef" class="chart" />
      </el-card>
      <el-card shadow="never" class="block">
        <template #header><b>三维指标雷达图</b></template>
        <div ref="radarRef" class="chart" />
      </el-card>
      <el-card shadow="never" class="block">
        <template #header><b>历史趋势</b></template>
        <div ref="trendRef" class="chart" />
      </el-card>
    </div>

    <!-- 诊断报告 + 一键应用 -->
    <el-card v-if="result" shadow="never" class="block">
      <template #header>
        <b>自动诊断</b>
        <span class="diagnosis-sum">{{ result.diagnosis_summary }}</span>
      </template>
      <el-empty v-if="!result.diagnoses.length" description="各项指标均达到阈值，无需优化" />
      <div v-else class="diagnosis-list">
        <div v-for="d in result.diagnoses" :key="d.suggestion_id" class="diagnosis-item">
          <div class="di-head">
            <el-tag :type="levelTag(d.level)" size="small">{{ levelText(d.level) }}</el-tag>
            <b>{{ metricLabel(d.metric) }}</b>
            <span class="score">{{ d.score }} &lt; 阈值 {{ d.threshold }}</span>
            <el-button type="primary" size="small" :loading="applying === d.suggestion_id"
                       @click="applySuggestion(d)">一键应用建议</el-button>
          </div>
          <div class="di-body">
            <p><b>问题：</b>{{ d.problem }}</p>
            <p><b>建议：</b>{{ d.suggestions.join('；') }}</p>
            <p v-if="Object.keys(d.param_changes).length">
              <b>参数变更：</b>
              <el-tag v-for="(v, k) in d.param_changes" :key="k" size="small" class="param-tag">{{ k }} → {{ v }}</el-tag>
            </p>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 明细表 -->
    <el-card v-if="result" shadow="never" class="block">
      <template #header><b>逐题明细</b></template>
      <el-table :data="result.details" border stripe max-height="420" size="small">
        <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
        <el-table-column label="上下文精确率" width="120" align="center">
          <template #default="{ row }">{{ fmt(row.context_precision) }}</template>
        </el-table-column>
        <el-table-column label="上下文召回率" width="120" align="center">
          <template #default="{ row }">{{ fmt(row.context_recall) }}</template>
        </el-table-column>
        <el-table-column label="MRR" width="90" align="center">
          <template #default="{ row }">{{ fmt(row.mrr) }}</template>
        </el-table-column>
        <el-table-column label="NDCG" width="90" align="center">
          <template #default="{ row }">{{ fmt(row.ndcg) }}</template>
        </el-table-column>
        <el-table-column label="语义相似度" width="110" align="center">
          <template #default="{ row }">{{ fmt(row.semantic_similarity) }}</template>
        </el-table-column>
        <el-table-column prop="answer" label="系统答案" min-width="240" show-overflow-tooltip />
      </el-table>
    </el-card>

    <!-- 变更日志 -->
    <el-card v-if="changes.length" shadow="never" class="block">
      <template #header>
        <b>参数变更日志</b>
        <el-button size="small" type="warning" class="rollback-btn" @click="doRollback">回滚到最近备份</el-button>
      </template>
      <el-timeline>
        <el-timeline-item v-for="(c, i) in changes" :key="i" :timestamp="c.time" placement="top">
          <b>{{ c.name || c.action }}</b>
          <span v-if="c.name">：{{ c.old_value }} → {{ c.new_value }}</span>
          <div class="change-reason">{{ c.reason || c.action }}</div>
        </el-timeline-item>
      </el-timeline>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { applySuggestion as apiApply, getReport, listChanges, listDatasets, listReports, rollbackEvaluate, runEval, uploadDataset } from '@/api/eval'

const datasets = ref<any[]>([])
const datasetId = ref<string>('')
const running = ref(false)
const applying = ref<string>('')
const result = ref<any>(null)
const changes = ref<any[]>([])

const overrides = reactive<any>({
  TOP_K_FOR_EVAL: 5,
  SIM_THRESHOLD: 0.65,
  LLM_METRICS_ENABLED: false
})

const barRef = ref<HTMLDivElement>()
const radarRef = ref<HTMLDivElement>()
const trendRef = ref<HTMLDivElement>()
let barChart: echarts.ECharts | null = null
let radarChart: echarts.ECharts | null = null
let trendChart: echarts.ECharts | null = null

/** 九宫格指标卡片：数值为空表示当前配置下未计算该指标 */
const metricCards = [
  { key: 'context_precision', label: '上下文精确率' },
  { key: 'context_recall', label: '上下文召回率' },
  { key: 'mrr', label: 'MRR' },
  { key: 'ndcg', label: 'NDCG' },
  { key: 'hit_rate', label: 'Top-K 命中率' },
  { key: 'semantic_similarity', label: '答案语义相似度' },
  { key: 'faithfulness', label: '忠实度' },
  { key: 'answer_relevance', label: '答案相关性' },
  { key: 'answer_correctness', label: '答案正确性' }
]

const METRIC_LABELS: Record<string, string> = Object.fromEntries(metricCards.map((m) => [m.key, m.label]))

const fmt = (v: any) => (v === undefined || v === null ? '-' : Number(v).toFixed(3))
const pct = (v: any) => Math.round((Number(v) || 0) * 100)
const metricLabel = (k: string) => METRIC_LABELS[k] || k
const levelTag = (l: string) => (l === 'high' ? 'danger' : l === 'medium' ? 'warning' : 'info')
const levelText = (l: string) => (l === 'high' ? '高风险' : l === 'medium' ? '中风险' : '低风险')
const gradeTagType = (g: string) => (g === '优秀' ? 'success' : g === '良好' ? 'primary' : g === '合格' ? 'warning' : 'danger')

onMounted(async () => {
  await Promise.all([loadDatasets(), loadHistory(), loadChanges()])
})

async function loadDatasets() {
  const res = await listDatasets()
  datasets.value = res.data
  if (!datasetId.value && res.data.length) {
    // 优先选中项目真实场景的高考评估集
    const preferred = res.data.find((d: any) => d.filename.includes('gaokao'))
    datasetId.value = (preferred || res.data[0]).dataset_id
  }
}

async function loadHistory() {
  const res = await listReports()
  history.value = res.data
}

async function loadChanges() {
  const res = await listChanges()
  changes.value = res.data
}

async function runEvalNow() {
  running.value = true
  try {
    result.value = await runEval({ dataset_id: datasetId.value, config_overrides: { ...overrides } })
    ElMessage.success('评估完成')
    await loadHistory()
    await nextTick()
    renderCharts()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '评估失败')
  } finally {
    running.value = false
  }
}

async function applySuggestion(d: any) {
  applying.value = d.suggestion_id
  try {
    const res = await apiApply({ report_id: result.value.report_id, suggestion_id: d.suggestion_id })
    ElMessage.success(res.message || '参数已应用，重启服务后生效')
    await loadChanges()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '应用失败')
  } finally {
    applying.value = ''
  }
}

async function doRollback() {
  try {
    const res = await rollbackEvaluate()
    ElMessage.success(res.message || '已回滚')
    await loadChanges()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '回滚失败')
  }
}

function renderCharts() {
  if (!result.value) return
  const chart = result.value.chart_data || {}

  barChart?.dispose()
  if (barRef.value) {
    barChart = echarts.init(barRef.value)
    barChart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['当前', '上一次'] },
      grid: { left: 40, right: 16, bottom: 70, top: 40 },
      xAxis: { type: 'category', data: chart.bar?.categories || [], axisLabel: { rotate: 35, fontSize: 10 } },
      yAxis: { type: 'value', max: 1 },
      series: [
        { name: '当前', type: 'bar', data: chart.bar?.current || [], itemStyle: { color: '#6a4cff' } },
        { name: '上一次', type: 'bar', data: chart.bar?.baseline || [], itemStyle: { color: '#d6d9e3' } }
      ]
    })
  }

  radarChart?.dispose()
  if (radarRef.value) {
    radarChart = echarts.init(radarRef.value)
    radarChart.setOption({
      tooltip: {},
      radar: {
        indicator: chart.radar?.indicators || [],
        radius: '65%',
        axisName: { fontSize: 11, color: '#4b5563' }
      },
      series: [{
        type: 'radar',
        data: [{
          value: chart.radar?.values || [],
          name: '本次评估',
          areaStyle: { opacity: 0.25 },
          itemStyle: { color: '#8b6dff' }
        }]
      }]
    })
  }

  trendChart?.dispose()
  if (trendRef.value) {
    trendChart = echarts.init(trendRef.value)
    trendChart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['综合得分', '上下文精确率', '上下文召回率'] },
      grid: { left: 40, right: 16, bottom: 40, top: 40 },
      xAxis: { type: 'category', data: chart.trend?.dates || [] },
      yAxis: { type: 'value', max: 1 },
      series: [
        { name: '综合得分', type: 'line', smooth: true, data: chart.trend?.overall || [], itemStyle: { color: '#6a4cff' } },
        { name: '上下文精确率', type: 'line', smooth: true, data: chart.trend?.precision || [], itemStyle: { color: '#2ec4b6' } },
        { name: '上下文召回率', type: 'line', smooth: true, data: chart.trend?.recall || [], itemStyle: { color: '#ff9f1c' } }
      ]
    })
  }
}

const history = ref<any[]>([])

/** 打开历史报告（趋势图点击后加载该报告详情） */
async function openReport(id: string) {
  result.value = await getReport(id)
  await nextTick()
  renderCharts()
}

defineExpose({ openReport })
</script>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}
.title {
  margin: 0 0 4px;
}
.sub {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
}
.block {
  margin-bottom: 16px;
}
.run-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.tip {
  font-size: 12px;
  color: var(--text-muted);
}
.inline-upload {
  display: inline-flex;
}
.summary {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.meta {
  font-size: 12px;
  color: var(--text-muted);
}
.cards {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.stat {
  text-align: center;
}
.num {
  font-size: 20px;
  font-weight: 700;
  color: var(--primary);
}
.lbl {
  font-size: 12px;
  color: var(--text-muted);
  margin: 2px 0 6px;
}
.charts {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}
.chart {
  height: 300px;
}
.diagnosis-sum {
  margin-left: 10px;
  font-size: 12px;
  color: var(--text-muted);
}
.diagnosis-item {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 10px;
}
.di-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.di-head .score {
  font-size: 12px;
  color: var(--text-muted);
}
.di-body {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}
.di-body p {
  margin: 4px 0;
}
.param-tag {
  margin-right: 6px;
}
.change-reason {
  font-size: 12px;
  color: var(--text-muted);
}
.rollback-btn {
  margin-left: 12px;
}
@media (max-width: 1100px) {
  .charts {
    grid-template-columns: 1fr;
  }
  .cards {
    grid-template-columns: repeat(3, 1fr);
  }
}
</style>
