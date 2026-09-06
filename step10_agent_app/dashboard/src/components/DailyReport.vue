<template>
  <div class="daily-report">
    <el-skeleton v-if="loading" :rows="8" animated />
    <el-empty v-else-if="!data" description="日报生成中，请稍候..." />
    <div v-else class="report-content" v-html="renderedHtml"></div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps({
  data: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})

const renderedHtml = computed(() => {
  if (!props.data) return ''
  try {
    return marked.parse(props.data)
  } catch (e) {
    return `<pre>${props.data}</pre>`
  }
})
</script>

<style scoped>
.report-content {
  padding: 16px;
  background: #fafafa;
  border-radius: 8px;
  max-height: 600px;
  overflow-y: auto;
  line-height: 1.8;
}
.report-content :deep(h1) {
  font-size: 20px;
  color: #303133;
  border-bottom: 2px solid #409EFF;
  padding-bottom: 8px;
  margin-top: 0;
}
.report-content :deep(h2) {
  font-size: 16px;
  color: #409EFF;
  margin-top: 20px;
  padding-left: 8px;
  border-left: 3px solid #409EFF;
}
.report-content :deep(h3) {
  font-size: 14px;
  color: #606266;
  margin-top: 16px;
}
.report-content :deep(p) {
  margin: 8px 0;
  color: #606266;
  font-size: 13px;
}
.report-content :deep(ul), .report-content :deep(ol) {
  padding-left: 20px;
  color: #606266;
  font-size: 13px;
}
.report-content :deep(li) {
  margin: 4px 0;
}
.report-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 12px;
}
.report-content :deep(th) {
  background: #409EFF;
  color: #fff;
  padding: 8px;
  text-align: left;
}
.report-content :deep(td) {
  padding: 6px 8px;
  border-bottom: 1px solid #ebeef5;
}
.report-content :deep(tr:nth-child(even)) {
  background: #f5f7fa;
}
.report-content :deep(strong) {
  color: #303133;
}
</style>
