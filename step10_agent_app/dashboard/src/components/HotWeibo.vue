<template>
  <div class="hot-weibo">
    <el-skeleton v-if="loading" :rows="4" animated />
    <div v-else-if="error" class="error-state">
      <el-empty description="数据暂时不可用，请稍后刷新">
        <el-button type="primary" @click="$emit('retry')">重新加载</el-button>
      </el-empty>
    </div>
    <el-empty v-else-if="!data || data.length === 0" description="暂无热点数据" />
    <div v-else class="weibo-list">
      <div v-for="(item, index) in data.slice(0, 10)" :key="item.weibo_id || index" class="weibo-item">
        <div class="weibo-rank" :class="{ top3: index < 3 }">{{ index + 1 }}</div>
        <div class="weibo-content">
          <div class="weibo-header">
            <el-avatar :size="32" style="background:#409EFF">{{ (item.username || '?').charAt(0) }}</el-avatar>
            <span class="username">{{ item.username }}</span>
            <el-tag size="small" type="danger" effect="light" style="margin-left:auto">
              热度 {{ item.hotspot_score?.toFixed(1) || '—' }}
            </el-tag>
          </div>
          <p class="weibo-text">{{ item.content }}</p>
          <div class="weibo-stats">
            <span><el-icon><Pointer /></el-icon> {{ formatNum(item.like_count) }}</span>
            <span><el-icon><ChatDotRound /></el-icon> {{ formatNum(item.comment_count) }}</span>
            <span><el-icon><Share /></el-icon> {{ formatNum(item.repost_count) }}</span>
            <span class="publish-time">{{ item.publish_time }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Pointer, ChatDotRound, Share } from '@element-plus/icons-vue'

defineProps({
  data: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
})

defineEmits(['retry'])

function formatNum(num) {
  if (num == null) return '0'
  if (num >= 10000) return (num / 10000).toFixed(1) + '万'
  return num.toLocaleString()
}
</script>

<style scoped>
.weibo-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.weibo-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: #fafafa;
  border-radius: 8px;
  transition: all 0.2s;
}
.weibo-item:hover {
  background: #f0f7ff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.1);
}
.weibo-rank {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: #c0c4cc;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  flex-shrink: 0;
}
.weibo-rank.top3 {
  background: linear-gradient(135deg, #f56c6c, #e6a23c);
}
.weibo-content {
  flex: 1;
  min-width: 0;
}
.weibo-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.username {
  font-weight: 600;
  color: #303133;
  font-size: 14px;
}
.weibo-text {
  margin: 0 0 8px;
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.weibo-stats {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #909399;
}
.weibo-stats span {
  display: flex;
  align-items: center;
  gap: 4px;
}
.publish-time {
  margin-left: auto;
}
</style>
