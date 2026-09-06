<template>
  <div class="influencers">
    <el-skeleton v-if="loading" :rows="4" animated />
    <div v-else-if="error" class="error-state">
      <el-empty description="数据暂时不可用，请稍后刷新">
        <el-button type="primary" @click="$emit('retry')">重新加载</el-button>
      </el-empty>
    </div>
    <el-empty v-else-if="!hasData" description="暂无影响力数据" />
    <div v-else class="influencer-grid">
      <!-- 粉丝量排行 -->
      <div class="influencer-col">
        <div class="col-title">
          <el-icon color="#409EFF"><User /></el-icon>
          高粉丝账号 TOP10
        </div>
        <el-table :data="data.followers" size="small" stripe style="width:100%">
          <el-table-column type="index" label="#" width="40" align="center" />
          <el-table-column prop="username" label="账号" min-width="120">
            <template #default="{ row }">
              <span class="username">{{ row.username }}</span>
            </template>
          </el-table-column>
          <el-table-column label="粉丝数" width="100" align="right">
            <template #default="{ row }">
              <span class="followers">{{ formatNum(row.followers_count) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="发帖" width="70" align="right">
            <template #default="{ row }">{{ row.post_count || 0 }}</template>
          </el-table-column>
        </el-table>
      </div>
      <!-- 互动量排行 -->
      <div class="influencer-col">
        <div class="col-title">
          <el-icon color="#E6A23C"><TrendCharts /></el-icon>
          高互动账号 TOP10
        </div>
        <el-table :data="data.engagement" size="small" stripe style="width:100%">
          <el-table-column type="index" label="#" width="40" align="center" />
          <el-table-column prop="username" label="账号" min-width="120">
            <template #default="{ row }">
              <span class="username">{{ row.username }}</span>
            </template>
          </el-table-column>
          <el-table-column label="总互动" width="100" align="right">
            <template #default="{ row }">
              <span class="engagement">{{ formatNum(row.total_engagement) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="发帖" width="70" align="right">
            <template #default="{ row }">{{ row.post_count || 0 }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { User, TrendCharts } from '@element-plus/icons-vue'

const props = defineProps({
  data: { type: Object, default: () => ({ followers: [], engagement: [] }) },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
})

defineEmits(['retry'])

const hasData = computed(() =>
  (props.data?.followers?.length > 0) || (props.data?.engagement?.length > 0)
)

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
  gap: 16px;
}
@media (max-width: 900px) {
  .influencer-grid { grid-template-columns: 1fr; }
}
.col-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 8px;
  color: #303133;
}
.username { font-weight: 500; color: #303133; }
.followers { color: #409EFF; font-weight: 600; }
.engagement { color: #E6A23C; font-weight: 600; }
</style>
