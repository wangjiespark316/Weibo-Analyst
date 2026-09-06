<template>
  <div class="daily-report">
    <el-skeleton v-if="loading" :rows="8" animated />
    <div v-else-if="error" class="error-state">
      <el-icon :size="40" color="#CBD5E1"><Warning /></el-icon>
      <div class="error-text">日报生成中或暂时不可用</div>
      <el-button size="small" type="primary" plain @click="$emit('retry')">重新加载</el-button>
    </div>
    <div v-else-if="!data" class="error-state">
      <el-icon :size="40" color="#CBD5E1"><Document /></el-icon>
      <div class="error-text">日报生成中，请稍候...</div>
    </div>
    <div v-else class="report-content markdown-body" v-html="renderedHtml"></div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import { Warning, Document } from '@element-plus/icons-vue'

const props = defineProps({
  data: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
})
defineEmits(['retry'])

const renderedHtml = computed(() => {
  if (!props.data) return ''
  try { return marked.parse(props.data) }
  catch (e) { return `<pre>${props.data}</pre>` }
})
</script>

<style scoped>
.daily-report { width: 100%; }
.report-content {
  max-height: 70vh;
  overflow-y: auto;
  padding: 8px 4px;
}
.report-content :deep(h1) {
  font-size: 20px; font-weight: 700; color: var(--text-primary);
  padding-bottom: 10px; margin-bottom: 16px; border-bottom: 1px solid var(--gray-200);
}
.report-content :deep(h2) {
  font-size: 16px; font-weight: 600; color: var(--text-primary);
  margin-top: 22px; margin-bottom: 10px;
}
.report-content :deep(h3) {
  font-size: 14.5px; font-weight: 600; color: var(--gray-600);
  margin-top: 14px; margin-bottom: 6px;
}
.report-content :deep(p) { margin-bottom: 10px; color: var(--gray-700); font-size: 14px; line-height: 1.8; }
.report-content :deep(ul), .report-content :deep(ol) {
  padding-left: 22px; margin-bottom: 10px; color: var(--gray-700); font-size: 14px;
}
.report-content :deep(li) { margin-bottom: 4px; }
.report-content :deep(blockquote) {
  border-left: 3px solid var(--gray-300);
  padding: 6px 14px; margin: 12px 0;
  background: var(--gray-50); color: var(--text-secondary);
  border-radius: 0 4px 4px 0;
}
.report-content :deep(code) {
  background: var(--gray-100); padding: 2px 6px; border-radius: 4px;
  font-size: 13px; color: #DC2626;
}
.report-content :deep(strong) { color: var(--text-primary); font-weight: 600; }
.report-content :deep(a) { color: var(--primary); text-decoration: none; }
.report-content :deep(a:hover) { text-decoration: underline; }
.report-content :deep(hr) { border: none; border-top: 1px solid var(--gray-100); margin: 18px 0; }
.report-content :deep(table) {
  width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px;
}
.report-content :deep(th) {
  background: var(--primary); color: #fff; padding: 8px 12px; text-align: left;
}
.report-content :deep(td) { padding: 8px 12px; border-bottom: 1px solid var(--gray-100); }
.report-content :deep(tr:nth-child(even)) { background: var(--gray-50); }
</style>
