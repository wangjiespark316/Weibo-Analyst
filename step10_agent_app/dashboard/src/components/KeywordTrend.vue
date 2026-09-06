<template>
  <div class="keyword-trend">
    <el-skeleton v-if="loading" :rows="4" animated />
    <div v-else-if="error" class="error-state">
      <el-empty description="数据暂时不可用，请稍后刷新">
        <el-button type="primary" @click="$emit('retry')">重新加载</el-button>
      </el-empty>
    </div>
    <div v-else>
      <div ref="chartRef" class="chart" style="height:320px"></div>
      <div class="kw-summary">
        <el-tag v-for="(item, idx) in topKeywords" :key="idx"
          :type="tagTypes[idx % tagTypes.length]" effect="light" size="large">
          {{ item.keyword }}: {{ item.total }} 次
        </el-tag>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, nextTick } from 'vue'
// ECharts 按需引入，减少首屏体积
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Object, default: () => ({}) },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
})

defineEmits(['retry'])

const chartRef = ref(null)
let chart = null

const tagTypes = ['primary', 'success', 'warning', 'danger', 'info']

const topKeywords = ref([])

function initChart() {
  if (!chartRef.value) return
  chart = echarts.init(chartRef.value)
  window.addEventListener('resize', () => chart?.resize())
}

function updateChart() {
  if (!chart || !props.data) return

  const keywords = Object.keys(props.data)
  const series = []
  const allDates = new Set()

  for (const kw of keywords) {
    const kwData = props.data[kw]
    if (!kwData || !kwData.trend) continue
    const trend = kwData.trend
    const data = trend.map(t => [t.date, t.count])
    trend.forEach(t => allDates.add(t.date))
    series.push({ name: kw, type: 'line', data, smooth: true, symbol: 'none' })
  }

  const dates = Array.from(allDates).sort()

  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: keywords, type: 'scroll', bottom: 0 },
    grid: { left: 40, right: 20, top: 20, bottom: 50 },
    xAxis: { type: 'category', data: dates, axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', name: '提及量' },
    color: ['#409EFF', '#67C23A', '#E6A23C', '#F56C6C', '#909399', '#9C27B0', '#00BCD4', '#FF9800'],
    series,
  })

  // 计算 TOP 关键词
  const kwList = keywords
    .map(kw => ({
      keyword: kw,
      total: props.data[kw]?.total_mentions || props.data[kw]?.post_count || 0,
    }))
    .sort((a, b) => b.total - a.total)
  topKeywords.value = kwList.slice(0, 5)
}

watch(() => props.data, () => {
  nextTick(() => updateChart())
}, { deep: true })

onMounted(() => {
  nextTick(() => {
    initChart()
    updateChart()
  })
})
</script>

<style scoped>
.chart {
  width: 100%;
}
.kw-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  justify-content: center;
}
</style>
