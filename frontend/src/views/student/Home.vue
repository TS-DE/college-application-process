<template>
  <div class="page">
    <section class="hero">
      <div>
        <h1>高考志愿填报系统</h1>
        <p>河南 2024-2025 录取数据 · 冲稳保规则引擎 · 本地大模型 + 知识库问答</p>
      </div>
      <div class="btns">
        <el-button type="primary" size="large" @click="$router.push('/volunteer')">开始智能选志愿</el-button>
        <el-button size="large" @click="$router.push('/ai-chat')">问问 AI 助手</el-button>
      </div>
    </section>

    <div class="grid">
      <!-- 左：中国地图 -->
      <div class="card map-card">
        <div class="card-head">
          <div>
            <h3>各省在河南招生的专业数量</h3>
            <p class="sub">数据来源：{{ year }} 年河南 {{ batch }} {{ category }} 录取数据</p>
          </div>
          <div class="filters">
            <el-select v-model="year" size="small" style="width: 90px" @change="load">
              <el-option :label="2025" :value="2025" />
              <el-option :label="2024" :value="2024" />
            </el-select>
            <el-select v-model="category" size="small" style="width: 100px" @change="load">
              <el-option label="物理类" value="物理类" />
              <el-option label="历史类" value="历史类" />
            </el-select>
            <el-select v-model="batch" size="small" style="width: 96px" @change="load">
              <el-option label="本科批" value="本科批" />
              <el-option label="专科批" value="专科批" />
            </el-select>
          </div>
        </div>

        <!-- 图表容器常驻 DOM（避免在 0 宽容器上初始化 ECharts），加载/空态用覆盖层 -->
        <div class="chart-box">
          <div ref="chartEl" class="chart"></div>

          <div v-if="loading" class="chart-overlay">
            <el-skeleton :rows="6" animated class="skeleton" />
          </div>

          <div v-else-if="!stats.length" class="chart-overlay">
            <el-empty description="暂无数据（该年份数据集没有院校省份信息）" />
          </div>
        </div>

        <p class="legend">
          颜色越深，代表该省高校在河南投放的专业越多（点击省份可查看该省院校）
        </p>
      </div>

      <!-- 右：快捷入口（保持不变） -->
      <div class="card">
        <h3>快捷入口</h3>
        <ul class="links">
          <li><router-link to="/volunteer">志愿填报（3+1+2 分数换算 + 冲稳保）</router-link></li>
          <li><router-link to="/university">查大学 / 查专业</router-link></li>
          <li><router-link to="/ai-chat">AI 助手（基于知识库的政策问答）</router-link></li>
        </ul>
        <el-divider />
        <p class="muted">
          位次是志愿填报的核心参考：系统会把你的分数换算成全省位次，再按
          「冲 / 稳 / 保」三档给出院校专业组建议。
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { majorCountByProvince } from '@/api/recommend'
import type { ProvinceMajorStat } from '@/types/recommend'

const router = useRouter()

const year = ref(2025)
const category = ref('物理类')
const batch = ref('本科批')

const chartEl = ref<HTMLDivElement>()
const chart = shallowRef<echarts.ECharts | null>(null)
const stats = ref<ProvinceMajorStat[]>([])
const loading = ref(false)

let geoJson: any = null

/** DataV GeoJSON 里的行政区全名 → 数据里的短名 */
const NAME_MAP: Record<string, string> = {
  北京市: '北京', 天津市: '天津', 河北省: '河北', 山西省: '山西',
  内蒙古自治区: '内蒙古', 辽宁省: '辽宁', 吉林省: '吉林', 黑龙江省: '黑龙江',
  上海市: '上海', 江苏省: '江苏', 浙江省: '浙江', 安徽省: '安徽',
  福建省: '福建', 江西省: '江西', 山东省: '山东', 河南省: '河南',
  湖北省: '湖北', 湖南省: '湖南', 广东省: '广东', 广西壮族自治区: '广西',
  海南省: '海南', 重庆市: '重庆', 四川省: '四川', 贵州省: '贵州',
  云南省: '云南', 西藏自治区: '西藏', 陕西省: '陕西', 甘肃省: '甘肃',
  青海省: '青海', 宁夏回族自治区: '宁夏', 新疆维吾尔自治区: '新疆',
  台湾省: '台湾', 香港特别行政区: '香港', 澳门特别行政区: '澳门'
}

/** 载入中国地图 GeoJSON（放在 public/china.json，运行时按需拉取，避免打进 bundle） */
async function loadGeoJson() {
  if (geoJson) return geoJson
  const resp = await fetch('/china.json')
  geoJson = await resp.json()
  echarts.registerMap('china', geoJson as any)
  return geoJson
}

function buildOption(): echarts.EChartsOption {
  const data = stats.value.map((d) => ({
    name: d.province,
    value: d.major_count,
    major_count: d.major_count,
    university_count: d.university_count
  }))
  const max = Math.max(1, ...data.map((d) => d.value))

  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: any) => {
        if (!params?.data || params.data.value == null) {
          return `${params.name}<br/>暂无数据`
        }
        return `<strong>${params.name}</strong><br/>招生专业：${params.data.major_count} 个<br/>涉及院校：${params.data.university_count} 所`
      }
    },
    visualMap: {
      min: 0,
      max,
      left: 'left',
      bottom: 'bottom',
      text: ['多', '少'],
      calculable: true,
      itemWidth: 12,
      itemHeight: 90,
      textStyle: { fontSize: 11, color: '#6b7280' },
      inRange: { color: ['#f3f1ff', '#ded7ff', '#b8a9ff', '#8b6dff', '#6a4cff', '#4a2ecc'] }
    },
    series: [
      {
        name: '招生专业数量',
        type: 'map',
        map: 'china',
        nameMap: NAME_MAP as any,
        roam: false,
        zoom: 1.15,
        aspectScale: 0.78,
        layoutCenter: ['50%', '52%'],
        layoutSize: '100%',
        itemStyle: {
          areaColor: '#f7f8fa',
          borderColor: '#e0e0e0',
          borderWidth: 0.8
        },
        label: { show: true, fontSize: 10, color: '#4b5563' },
        emphasis: {
          label: { show: true, color: '#fff', fontSize: 11 },
          itemStyle: {
            areaColor: '#6a4cff',
            shadowBlur: 10,
            shadowColor: 'rgba(106, 76, 255, 0.5)'
          }
        },
        select: {
          label: { show: true, color: '#fff' },
          itemStyle: { areaColor: '#4a2ecc' }
        },
        data
      }
    ]
  }
}

function ensureChart() {
  if (!chartEl.value) return null
  if (!chart.value) {
    chart.value = echarts.init(chartEl.value)
    // 点击省份 → 跳转「查大学/专业」并带上该省份作为筛选条件
    chart.value.on('click', (params: any) => {
      const name = params?.name
      const hasData = params?.data?.value != null
      if (!name || !hasData) return
      router.push({
        path: '/university',
        query: {
          school_province: name,
          category: category.value,
          batch: batch.value,
          year: String(year.value)
        }
      })
    })
  }
  return chart.value
}

async function render() {
  const inst = ensureChart()
  if (!inst) return
  inst.setOption(buildOption(), true)
  inst.resize()
}

async function load() {
  loading.value = true
  try {
    await loadGeoJson()
    const res = await majorCountByProvince({
      province: '河南',
      year: year.value,
      category: category.value,
      batch: batch.value
    })
    stats.value = res.data || []
  } catch {
    stats.value = []
  } finally {
    loading.value = false
    // 等覆盖层移除、容器恢复可见后再渲染，保证拿到正确宽高
    await nextTick()
    await render()
  }
}

function onResize() {
  chart.value?.resize()
}

let resizeObserver: ResizeObserver | null = null

onMounted(async () => {
  await load()
  window.addEventListener('resize', onResize)
  // 容器尺寸变化（不限于窗口 resize）时也自适应
  if (chartEl.value && 'ResizeObserver' in window) {
    resizeObserver = new ResizeObserver(() => chart.value?.resize())
    resizeObserver.observe(chartEl.value)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  resizeObserver?.disconnect()
  resizeObserver = null
  chart.value?.dispose()
  chart.value = null
})
</script>

<style scoped>
.hero {
  background: linear-gradient(135deg, #4f46e5, #7c3aed);
  color: #fff;
  border-radius: var(--radius);
  padding: 32px 28px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}
.hero h1 {
  margin: 0 0 8px;
  font-size: 26px;
}
.hero p {
  margin: 0;
  opacity: 0.9;
  font-size: 14px;
}
.grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 16px;
  margin-top: 16px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 10px;
}
.card-head h3 {
  margin: 0;
  font-size: 15px;
}
.sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}
.filters {
  display: flex;
  gap: 6px;
}
.chart-box {
  position: relative;
  height: 480px;
  width: 100%;
}
.chart {
  height: 100%;
  width: 100%;
}
.chart-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
}
.skeleton {
  width: 100%;
  padding: 20px;
}
.legend {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
}
.links {
  padding-left: 18px;
  line-height: 2;
  font-size: 14px;
  color: var(--primary);
}
@media (max-width: 900px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .chart-box {
    height: 380px;
  }
}
</style>
