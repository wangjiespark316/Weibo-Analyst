<template>
  <div class="sentiment-wrap">
    <!-- Loading -->
    <div v-if="loading" class="sentiment-loading">
      <el-skeleton :rows="3" animated />
    </div>

    <!-- Error -->
    <div v-else-if="error" class="error-state">
      <el-icon :size="40" color="#CBD5E1"><Warning /></el-icon>
      <div class="error-text">情绪数据加载失败</div>
      <el-button size="small" type="primary" plain @click="$emit('retry')">重试</el-button>
    </div>

    <!-- Chart -->
    <div v-else class="sentiment-content">
      <div ref="chartRef" class="sentiment-chart"></div>
      <div class="sentiment-legend">
        <div class="legend-item">
          <div class="legend-left">
            <span class="legend-dot" style="background:#10B981"></span>
            <span class="legend-name">正面</span>
          </div>
          <div class="legend-right">
            <span class="legend-pct">{{ positiveRate }}%</span>
            <span class="legend-count">{{ positiveCount }} 条</span>
          </div>
        </div>
        <div class="legend-item">
          <div class="legend-left">
            <span class="legend-dot" style="background:#CBD5E1"></span>
            <span class="legend-name">中性</span>
          </div>
          <div class="legend-right">
            <span class="legend-pct">{{ neutralRate }}%</span>
            <span class="legend-count">{{ neutralCount }} 条</span>
          </div>
        </div>
        <div class="legend-item">
          <div class="legend-left">
            <span class="legend-dot" style="background:#EF4444"></span>
            <span class="legend-name">负面</span>
          </div>
          <div class="legend-right">
            <span class="legend-pct">{{ negativeRate }}%</span>
            <span class="legend-count">{{ negativeCount }} 条</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { Warning } from '@element-plus/icons-vue'

echarts.use([PieChart, TooltipComponent, CanvasRenderer])

const props = defineProps({
  data: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
})
defineEmits(['retry'])

const chartRef = ref(null)
let chartInstance = null

const total = computed(() => props.data?.total_analyzed || 0)
const positiveRate = computed(() => Math.round(props.data?.positive_ratio || 0))
const neutralRate = computed(() => Math.round(props.data?.neutral_ratio || 0))
const negativeRate = computed(() => Math.round(props.data?.negative_ratio || 0))
const positiveCount = computed(() => Math.round(total.value * positiveRate.value / 100))
const neutralCount = computed(() => Math.round(total.value * neutralRate.value / 100))
const negativeCount = computed(() => Math.round(total.value * negativeRate.value / 100))

function renderChart() {
  if (!chartRef.value || !props.data) return
  if (!chartInstance) chartInstance = echarts.init(chartRef.value)
  chartInstance.setOption({
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(15,23,42,0.92)',
      borderColor: 'transparent',
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: '{b}: {c} 条 ({d}%)',
    },
    series: [{
      type: 'pie',
      radius: ['62%', '82%'],
      center: ['50%', '50%'],
      avoidLabelOverlap: false,
      label: {
        show: true,
        position: 'center',
        formatter: `{total|${total.value}}\n{sub|条评论}`,
        rich: {
          total: { fontSize: 22, fontWeight: 800, color: '#0F172A', lineHeight: 28 },
          sub: { fontSize: 12, color: '#94A3B8' },
        },
      },
      labelLine: { show: false },
      data: [
        { value: positiveCount.value, name: '正面', itemStyle: { color: '#10B981' } },
        { value: neutralCount.value, name: '中性', itemStyle: { color: '#CBD5E1' } },
        { value: negativeCount.value, name: '负面', itemStyle: { color: '#EF4444' } },
      ],
      animationType: 'scale',
      animationEasing: 'elasticOut',
      animationDuration: 1000,
    }],
  })
}

function handleResize() { chartInstance?.resize() }

watch(() => props.data, () => { nextTick(renderChart) }, { deep: true })
onMounted(() => { nextTick(renderChart); window.addEventListener('resize', handleResize) })
onUnmounted(() => { window.removeEventListener('resize', handleResize); chartInstance?.dispose() })
</script>

<style scoped>
.sentiment-wrap { width: 100%; }
.sentiment-loading { padding: 20px; }
.sentiment-content { display: flex; flex-direction: column; align-items: center; gap: 16px; }
.sentiment-chart { width: 100%; height: 200px; }
.sentiment-legend { display: flex; flex-direction: column; gap: 10px; width: 100%; }
.legend-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--gray-50);
  border-radius: 8px;
}
.legend-left { display: flex; align-items: center; gap: 8px; }
.legend-dot { width: 10px; height: 10px; border-radius: 3px; }
.legend-name { font-size: 13px; color: var(--text-body); font-weight: 500; }
.legend-right { display: flex; align-items: center; gap: 10px; }
.legend-pct { font-size: 14px; font-weight: 700; color: var(--text-primary); }
.legend-count { font-size: 12px; color: var(--text-muted); }
</style>
