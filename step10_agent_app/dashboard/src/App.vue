<template>
  <div class="dashboard">
    <!-- 顶部导航 -->
    <el-header class="header">
      <div class="header-left">
        <el-icon :size="28" color="#409EFF"><DataAnalysis /></el-icon>
        <h1 class="title">微博舆情分析 Dashboard</h1>
      </div>
      <div class="header-right">
        <el-tag type="success" effect="dark">AI 行业数据集</el-tag>
        <el-button :icon="Refresh" circle @click="refreshAll" :loading="loading" />
      </div>
    </el-header>

    <el-main class="main">
      <!-- 数据概览卡片 -->
      <el-row :gutter="16" class="stats-row">
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-icon" style="background:#e1f3d8"><el-icon :size="24" color="#67c23a"><TrendCharts /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.hotCount }}</div>
              <div class="stat-label">热点微博</div>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-icon" style="background:#fdf6ec"><el-icon :size="24" color="#e6a23c"><Search /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.keywordCount }}</div>
              <div class="stat-label">关键词监测</div>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-icon" style="background:#f0f9eb"><el-icon :size="24" color="#67c23a"><CircleCheck /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.positiveRate }}%</div>
              <div class="stat-label">正面情绪</div>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-icon" style="background:#fef0f0"><el-icon :size="24" color="#f56c6c"><User /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.influencerCount }}</div>
              <div class="stat-label">影响力账号</div>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 今日热点 -->
      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="card-header">
            <el-icon color="#409EFF"><HotWater /></el-icon>
            <span>今日热点 TOP10</span>
          </div>
        </template>
        <HotWeibo :data="hotWeiboData" :loading="loading" />
      </el-card>

      <!-- 关键词趋势 + 情感分析 -->
      <el-row :gutter="16">
        <el-col :xs="24" :lg="14">
          <el-card shadow="never" class="section-card">
            <template #header>
              <div class="card-header">
                <el-icon color="#e6a23c"><TrendCharts /></el-icon>
                <span>关键词趋势</span>
              </div>
            </template>
            <KeywordTrend :data="keywordTrendData" :loading="loading" />
          </el-card>
        </el-col>
        <el-col :xs="24" :lg="10">
          <el-card shadow="never" class="section-card">
            <template #header>
              <div class="card-header">
                <el-icon color="#67c23a"><PieChart /></el-icon>
                <span>用户情绪分析</span>
              </div>
            </template>
            <Sentiment :data="sentimentData" :loading="loading" />
          </el-card>
        </el-col>
      </el-row>

      <!-- 影响力排行 -->
      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="card-header">
            <el-icon color="#f56c6c"><Trophy /></el-icon>
            <span>影响力账号排行</span>
          </div>
        </template>
        <Influencers :data="influencerData" :loading="loading" />
      </el-card>

      <!-- AI 日报 -->
      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="card-header">
            <el-icon color="#909399"><Document /></el-icon>
            <span>AI 舆情日报</span>
            <el-tag size="small" type="info" style="margin-left:8px">基于 API 数据自动生成</el-tag>
          </div>
        </template>
        <DailyReport :data="dailyReportData" :loading="loading" />
      </el-card>
    </el-main>

    <el-footer class="footer">
      <span>数据来源：微博分析 API · 最后更新：{{ lastUpdate }}</span>
    </el-footer>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  DataAnalysis, Refresh, TrendCharts, Search, CircleCheck,
  User, HotWater, PieChart, Trophy, Document,
} from '@element-plus/icons-vue'
import {
  getHotWeibo, getKeywordTrend, getSentiment,
  getInfluencers, getDailyReport,
} from './api/weibo'
import HotWeibo from './components/HotWeibo.vue'
import KeywordTrend from './components/KeywordTrend.vue'
import Sentiment from './components/Sentiment.vue'
import Influencers from './components/Influencers.vue'
import DailyReport from './components/DailyReport.vue'

const loading = ref(false)
const lastUpdate = ref('—')

const stats = reactive({
  hotCount: 0,
  keywordCount: 0,
  positiveRate: 0,
  influencerCount: 0,
})

const hotWeiboData = ref([])
const keywordTrendData = ref({})
const sentimentData = ref(null)
const influencerData = ref({ followers: [], engagement: [] })
const dailyReportData = ref('')

const KEYWORDS = ['豆包', '飞书', 'Agent', '大模型', 'AI办公', 'ChatGPT', '企业AI', '智能体']

async function loadAll() {
  loading.value = true
  try {
    // 并行加载所有数据
    const [hotRes, sentimentRes, infFollowers, infEngagement, dailyRes] = await Promise.allSettled([
      getHotWeibo(20),
      getSentiment(2000),
      getInfluencers('followers', 10),
      getInfluencers('engagement', 10),
      getDailyReport(),
    ])

    // 热点微博
    if (hotRes.status === 'fulfilled') {
      hotWeiboData.value = hotRes.value.data || []
      stats.hotCount = hotRes.value.total || 0
    }

    // 情感分析
    if (sentimentRes.status === 'fulfilled') {
      sentimentData.value = sentimentRes.value
      stats.positiveRate = sentimentRes.value.positive_ratio || 0
    }

    // 影响力
    if (infFollowers.status === 'fulfilled') {
      influencerData.value.followers = infFollowers.value.data || []
      stats.influencerCount = (infFollowers.value.data || []).length
    }
    if (infEngagement.status === 'fulfilled') {
      influencerData.value.engagement = infEngagement.value.data || []
    }

    // 日报
    if (dailyRes.status === 'fulfilled') {
      dailyReportData.value = dailyRes.value.report || dailyRes.value.content || JSON.stringify(dailyRes.value, null, 2)
    }

    // 关键词趋势（逐个加载，因为每个关键词一个请求）
    const kwResults = {}
    let kwOk = 0
    for (const kw of KEYWORDS) {
      try {
        const res = await getKeywordTrend(kw, 30)
        kwResults[kw] = res
        kwOk++
      } catch (e) {
        console.warn(`关键词 ${kw} 加载失败:`, e.message)
      }
    }
    keywordTrendData.value = kwResults
    stats.keywordCount = kwOk

    lastUpdate.value = new Date().toLocaleString('zh-CN')
    ElMessage.success('数据加载完成')
  } catch (e) {
    console.error('加载失败:', e)
    ElMessage.error('部分数据加载失败，请刷新重试')
  } finally {
    loading.value = false
  }
}

function refreshAll() {
  loadAll()
}

onMounted(() => {
  loadAll()
})
</script>

<style scoped>
.dashboard {
  min-height: 100vh;
  background: #f5f7fa;
}
.header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  color: #fff;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.main {
  padding: 16px;
  max-width: 1600px;
  margin: 0 auto;
}
.stats-row {
  margin-bottom: 16px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 12px;
  border-radius: 8px;
}
.stat-card :deep(.el-card__body) {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
}
.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}
.stat-label {
  font-size: 13px;
  color: #909399;
  margin-top: 2px;
}
.section-card {
  margin-bottom: 16px;
  border-radius: 8px;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 15px;
}
.footer {
  text-align: center;
  color: #909399;
  font-size: 12px;
  padding: 16px;
  background: #fff;
  border-top: 1px solid #ebeef5;
}
</style>
