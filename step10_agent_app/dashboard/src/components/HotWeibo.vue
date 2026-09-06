<template>
  <div class="hot-weibo">
    <!-- Loading -->
    <div v-if="loading" class="hot-loading">
      <div v-for="i in 5" :key="i" class="hot-skeleton">
        <el-skeleton :rows="1" animated />
      </div>
    </div>

    <!-- Error -->
    <div v-else-if="error" class="error-state">
      <el-icon :size="40" color="#CBD5E1"><Warning /></el-icon>
      <div class="error-text">数据加载失败：{{ error }}</div>
      <el-button size="small" type="primary" plain @click="$emit('retry')">重新加载</el-button>
    </div>

    <!-- Empty -->
    <div v-else-if="!data || data.length === 0" class="error-state">
      <el-icon :size="40" color="#CBD5E1"><Document /></el-icon>
      <div class="error-text">暂无热点微博数据</div>
    </div>

    <!-- List -->
    <div v-else class="hot-list">
      <div v-for="(item, idx) in data" :key="item.weibo_id || idx" class="hot-item">
        <div class="hot-rank">{{ idx + 1 }}</div>
        <div class="hot-user">
          <div class="hot-avatar" :style="{ background: avatarColor(item.username) }">
            {{ (item.username || '?').charAt(0) }}
          </div>
          <div>
            <div class="hot-username">{{ item.username || '未知用户' }}</div>
            <div class="hot-time">{{ formatTime(item.publish_time) }}</div>
          </div>
        </div>
        <div class="hot-content">{{ item.content || item.text || '暂无内容' }}</div>
        <div class="hot-right">
          <div class="hot-score">
            <el-icon :size="16" color="#F59E0B"><HotWater /></el-icon>
            {{ formatScore(item.heat_score || item.hot_score) }}
          </div>
          <div class="hot-stats">
            <span><el-icon :size="12"><Pointer /></el-icon>{{ formatNum(item.like_count) }}</span>
            <span><el-icon :size="12"><ChatDotRound /></el-icon>{{ formatNum(item.comment_count) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Warning, Document, HotWater, Pointer, ChatDotRound } from '@element-plus/icons-vue'

defineProps({
  data: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
})
defineEmits(['retry'])

const colors = [
  'linear-gradient(135deg,#1D4ED8,#3B82F6)',
  'linear-gradient(135deg,#10B981,#059669)',
  'linear-gradient(135deg,#F59E0B,#D97706)',
  'linear-gradient(135deg,#EF4444,#DC2626)',
  'linear-gradient(135deg,#8B5CF6,#7C3AED)',
  'linear-gradient(135deg,#06B6D4,#0891B2)',
  'linear-gradient(135deg,#EC4899,#DB2777)',
]

function avatarColor(name) {
  if (!name) return colors[0]
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash)
  return colors[Math.abs(hash) % colors.length]
}

function formatNum(n) {
  if (n == null) return '0'
  if (n >= 10000) return (n / 10000).toFixed(1) + 'w'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return n.toLocaleString()
}

function formatScore(s) {
  if (s == null) return '—'
  return typeof s === 'number' ? s.toFixed(1) : s
}

function formatTime(t) {
  if (!t) return ''
  const d = new Date(t)
  if (isNaN(d.getTime())) return t
  const now = new Date()
  const diff = now - d
  if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前'
  if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前'
  return `${d.getMonth() + 1}月${d.getDate()}日`
}
</script>

<style scoped>
.hot-weibo { width: 100%; }
.hot-loading { padding: 0 20px; }
.hot-skeleton { padding: 16px 0; border-bottom: 1px solid var(--gray-100); }
.hot-skeleton:last-child { border-bottom: none; }
</style>
