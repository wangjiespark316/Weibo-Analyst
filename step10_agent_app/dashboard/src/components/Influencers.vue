<template>
  <div class="influencers">
    <el-skeleton v-if="loading" :rows="4" animated />
    <div v-else-if="error" class="error-state">
      <el-icon :size="40" color="#CBD5E1"><Warning /></el-icon>
      <div class="error-text">影响力数据加载失败</div>
      <el-button size="small" type="primary" plain @click="$emit('retry')">重试</el-button>
    </div>
    <div v-else-if="!hasData" class="error-state">
      <el-icon :size="40" color="#CBD5E1"><User /></el-icon>
      <div class="error-text">暂无影响力数据</div>
    </div>
    <div v-else class="influencer-grid">
      <!-- 粉丝量排行 -->
      <div class="influencer-col">
        <div class="col-title">
          <el-icon :size="16" color="#1D4ED8"><User /></el-icon>
          高粉丝账号 TOP10
        </div>
        <div class="rank-list">
          <div v-for="(item, idx) in data.followers" :key="item.user_id || idx" class="rank-item">
            <div class="rank-num" :class="{ top: idx < 3 }">{{ idx + 1 }}</div>
            <div class="rank-avatar" :style="{ background: avatarColor(item.username) }">
              {{ (item.username || '?').charAt(0) }}
            </div>
            <div class="rank-info">
              <div class="rank-name">{{ item.username }}</div>
              <div class="rank-sub">{{ item.post_count || 0 }} 条帖子</div>
            </div>
            <div class="rank-value followers">{{ formatNum(item.followers_count) }}</div>
          </div>
        </div>
      </div>
      <!-- 互动量排行 -->
      <div class="influencer-col">
        <div class="col-title">
          <el-icon :size="16" color="#F59E0B"><TrendCharts /></el-icon>
          高互动账号 TOP10
        </div>
        <div class="rank-list">
          <div v-for="(item, idx) in data.engagement" :key="item.user_id || idx" class="rank-item">
            <div class="rank-num" :class="{ top: idx < 3 }">{{ idx + 1 }}</div>
            <div class="rank-avatar" :style="{ background: avatarColor(item.username) }">
              {{ (item.username || '?').charAt(0) }}
            </div>
            <div class="rank-info">
              <div class="rank-name">{{ item.username }}</div>
              <div class="rank-sub">{{ item.post_count || 0 }} 条帖子</div>
            </div>
            <div class="rank-value engagement">{{ formatNum(item.total_engagement) }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { User, TrendCharts, Warning } from '@element-plus/icons-vue'

const props = defineProps({
  data: { type: Object, default: () => ({ followers: [], engagement: [] }) },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
})
defineEmits(['retry'])

const hasData = computed(() =>
  (props.data?.followers?.length > 0) || (props.data?.engagement?.length > 0)
)

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

function formatNum(num) {
  if (num == null) return '0'
  if (num >= 100000000) return (num / 100000000).toFixed(1) + '亿'
  if (num >= 10000) return (num / 10000).toFixed(1) + '万'
  return num.toLocaleString()
}
</script>

<style scoped>
.influencer-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
@media (max-width: 900px) {
  .influencer-grid { grid-template-columns: 1fr; }
}
.col-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 14px;
  margin-bottom: 14px;
  color: var(--text-primary);
}
.rank-list { display: flex; flex-direction: column; gap: 0; }
.rank-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--gray-100);
  transition: background 0.15s;
}
.rank-item:last-child { border-bottom: none; }
.rank-item:hover { background: var(--gray-50); margin: 0 -8px; padding: 10px 8px; border-radius: 8px; }
.rank-num {
  width: 24px; height: 24px;
  border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700;
  background: var(--gray-100); color: var(--text-muted);
  flex-shrink: 0;
}
.rank-num.top { background: linear-gradient(135deg, #FBBF24, #F59E0B); color: #fff; }
.rank-avatar {
  width: 32px; height: 32px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-size: 13px; font-weight: 600;
  flex-shrink: 0;
  border: 2px solid var(--gray-100);
}
.rank-info { flex: 1; min-width: 0; }
.rank-name { font-size: 13.5px; font-weight: 600; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rank-sub { font-size: 11.5px; color: var(--text-muted); }
.rank-value { font-size: 15px; font-weight: 700; flex-shrink: 0; }
.rank-value.followers { color: var(--primary); }
.rank-value.engagement { color: var(--warning); }
</style>
