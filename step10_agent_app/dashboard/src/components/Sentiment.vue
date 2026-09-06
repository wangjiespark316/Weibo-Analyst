<template>
  <div class="sentiment">
    <el-skeleton v-if="loading" :rows="4" animated />
    <el-empty v-else-if="!data || data.total_analyzed === 0" description="情感数据加载中或暂无数据" />
    <div v-else>
      <div ref="chartRef" class="chart" style="height:260px"></div>
      <div class="sentiment-stats">
        <div class="stat-item positive">
          <div class="stat-num">{{ data.positive_ratio }}%</div>
          <div class="stat-label">正面</div>
          <div class="stat-count">{{ formatNum(data.positive_count) }} 条</div>
        </div>
        <div class="stat-item neutral">
          <div class="stat-num">{{ data.neutral_ratio }}%</div>
          <div class="stat-label">中性</div>
          <div class="stat-count">{{ formatNum(data.neutral_count) }} 条</div>
        </div>
        <div class="stat-item negative">
          <div class="stat-num">{{ data.negative_ratio }}%</div>
          <div class="stat-label">负面</div>
          <div class="stat-count">{{ formatNum(data.negative_count) }} 条</div>
        </div>
      </div>
      <div v-if="data.top_negative_viewpoints?.length" class="negative-words">
        <div class="section-title">高频负面观点词</div>
        <div class="word-tags">
          <el-tag v-for="(w, idx) in data.top_negative_viewpoints.slice(0, 8)" :key="idx"
            type="danger" effect="plain" size="small">
            {{ w.word }} ({{ w.count }})
          </el-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  data: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})

const chartRef = ref(null)
let chart = null

function formatNum(num) {
  if (num == null) return '0'
  if (num >= 10000) return (num / 10000).toFixed(1) + '万'
  return num.toLocaleString()
}

function initChart() {
  if (!chartRef.value) return
  chart = echarts.init(chartRef.value)
  window.addEventListener('resize', () => chart?.resize())
}

function updateChart() {
  if (!chart || !props.data) return
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['50%', '50%'],
      avoidLabelOverlap: false,
      label: { show: true, formatter: '{b}\n{d}%', fontSize: 11 },
      data: [
        { value: props.data.positive_count || 0, name: '正面', itemStyle: { color: '#67C23A' } },
        { value: props.data.neutral_count || 0, name: '中性', itemStyle: { color: '#909399' } },
        { value: props.data.negative_count || 0, name: '负面', itemStyle: { color: '#F56C6C' } },
      ],
    }],
  })
}

watch(() => props.data, () => nextTick(() => updateChart()), { deep: true })

onMounted(() => {
  nextTick(() => {
    initChart()
    updateChart()
  })
})
</script>

<style scoped>
.chart { width: 100%; }
.sentiment-stats {
  display: flex;
  justify-content: space-around;
  margin-top: 8px;
  padding: 12px 0;
  border-top: 1px solid #ebeef5;
}
.stat-item { text-align: center; }
.stat-num { font-size: 22px; font-weight: 700; }
.stat-item.positive .stat-num { color: #67C23A; }
.stat-item.neutral .stat-num { color: #909399; }
.stat-item.negative .stat-num { color: #F56C6C; }
.stat-label { font-size: 13px; color: #606266; margin: 2px 0; }
.stat-count { font-size: 11px; color: #909399; }
.negative-words { margin-top: 12px; padding-top: 12px; border-top: 1px solid #ebeef5; }
.section-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; }
.word-tags { display: flex; flex-wrap: wrap; gap: 6px; }
</style>
