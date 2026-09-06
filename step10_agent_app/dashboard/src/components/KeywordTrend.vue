<template>
  <div class="keyword-trend">
    <el-skeleton v-if="loading" :rows="4" animated />
    <div v-else-if="error" class="error-state">
      <el-icon :size="40" color="#CBD5E1"><Warning /></el-icon>
      <div class="error-text">趋势数据加载失败</div>
      <el-button size="small" type="primary" plain @click="$emit('retry')">重试</el-button>
    </div>
    <div v-else ref="chartRef" class="chart"></div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { Warning } from '@element-plus/icons-vue'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Object, default: () => ({}) },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
})
defineEmits(['retry'])

const chartRef = ref(null)
let chart = null

const colorMap = {
  '豆包': '#1D4ED8', '飞书': '#10B981', 'Agent': '#F59E0B', '大模型': '#8B5CF6',
  'AI办公': '#06B6D4', 'ChatGPT': '#EF4444', '企业AI': '#EC4899', '智能体': '#84CC16',
}
const fallbackColors = ['#1D4ED8', '#10B981', '#F59E0B', '#8B5CF6', '#06B6D4', '#EF4444', '#EC4899', '#84CC16']

function getColor(kw, idx) { return colorMap[kw] || fallbackColors[idx % fallbackColors.length] }

function initChart() {
  if (!chartRef.value) return
  chart = echarts.init(chartRef.value)
}

function updateChart() {
  if (!chart || !props.data) return
  const keywords = Object.keys(props.data)
  const allDates = new Set()
  const seriesData = []

  keywords.forEach((kw, idx) => {
    const kwData = props.data[kw]
    if (!kwData || !kwData.trend) return
    const data = kwData.trend.map(t => [t.date, t.count])
    kwData.trend.forEach(t => allDates.add(t.date))
    const color = getColor(kw, idx)
    seriesData.push({
      name: kw, type: 'line', data, smooth: true, symbol: 'none',
      lineStyle: { width: idx === 0 ? 2.5 : 2, color },
      itemStyle: { color },
      areaStyle: idx < 2 ? {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: color + '29' },
          { offset: 1, color: color + '03' },
        ]),
      } : undefined,
    })
  })

  const dates = Array.from(allDates).sort()

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(15,23,42,0.92)',
      borderColor: 'transparent',
      textStyle: { color: '#fff', fontSize: 12 },
      padding: [10, 14],
    },
    legend: {
      data: keywords,
      top: 0, right: 0,
      textStyle: { color: '#64748B', fontSize: 12 },
      itemWidth: 14, itemHeight: 8, itemGap: 20,
    },
    grid: { left: 40, right: 20, top: 40, bottom: 30 },
    xAxis: {
      type: 'category', data: dates,
      axisLine: { lineStyle: { color: '#E2E8F0' } },
      axisLabel: { color: '#94A3B8', fontSize: 11, interval: Math.max(0, Math.floor(dates.length / 8) - 1) },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: '#94A3B8', fontSize: 11 },
      splitLine: { lineStyle: { color: '#F1F5F9', type: 'dashed' } },
    },
    series: seriesData,
    animationDuration: 1200,
    animationEasing: 'cubicOut',
  }, true)
}

function handleResize() { chart?.resize() }

watch(() => props.data, () => { nextTick(updateChart) }, { deep: true })
onMounted(() => { nextTick(() => { initChart(); updateChart() }); window.addEventListener('resize', handleResize) })
onUnmounted(() => { window.removeEventListener('resize', handleResize); chart?.dispose() })
</script>

<style scoped>
.keyword-trend { width: 100%; }
.chart { width: 100%; height: 320px; }
</style>
