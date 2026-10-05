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
      <div class="card">
        <h3>我在河南招生的院校分布</h3>
        <div ref="chartEl" class="chart"></div>
      </div>
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
import { onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { provinceStats } from '@/api/recommend'

const chartEl = ref<HTMLDivElement>()

onMounted(async () => {
  try {
    const res = await provinceStats()
    const items = (res.items || []).slice(0, 15)
    if (!chartEl.value || !items.length) return
    const chart = echarts.init(chartEl.value)
    chart.setOption({
      grid: { left: 60, right: 20, top: 20, bottom: 30 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: items.map((i: any) => i.name), axisLabel: { interval: 0, rotate: 30 } },
      yAxis: { type: 'value', name: '招生记录数' },
      series: [
        {
          type: 'bar',
          data: items.map((i: any) => i.value),
          itemStyle: { color: '#4f46e5', borderRadius: [4, 4, 0, 0] }
        }
      ]
    })
    window.addEventListener('resize', () => chart.resize())
  } catch {
    /* 图表失败不影响页面 */
  }
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
.chart {
  height: 320px;
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
}
</style>
