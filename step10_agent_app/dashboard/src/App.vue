<template>
  <el-config-provider :locale="zhCn">
  <div class="dashboard">
    <!-- 顶部导航 -->
    <el-header class="header">
      <div class="header-left">
        <el-icon :size="28" color="#fff"><DataAnalysis /></el-icon>
        <h1 class="title">微博舆情分析 Dashboard</h1>
      </div>
      <div class="header-right">
        <el-tag type="success" effect="dark">AI 行业数据集</el-tag>
        <el-button :icon="Refresh" circle @click="refreshAll" :loading="refreshing" />
      </div>
    </el-header>

    <el-main class="main">
      <!-- 数据概览卡片 -->
      <el-row :gutter="16" class="stats-row">
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-icon" style="background:#e1f3d8"><el-icon :size="24" color="#67c23a"><TrendCharts /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.hotCount || '—' }}</div>
              <div class="stat-label">热点微博</div>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-icon" style="background:#fdf6ec"><el-icon :size="24" color="#e6a23c"><Search /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.keywordCount || '—' }}</div>
              <div class="stat-label">关键词监测</div>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-icon" style="background:#f0f9eb"><el-icon :size="24" color="#67c23a"><CircleCheck /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.positiveRate ? stats.positiveRate + '%' : '—' }}</div>
              <div class="stat-label">正面情绪</div>
            </div>
          </el-card>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-icon" style="background:#fef0f0"><el-icon :size="24" color="#f56c6c"><User /></el-icon></div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.influencerCount || '—' }}</div>
              <div class="stat-label">影响力账号</div>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 今日热点（优先级1，最先加载） -->
      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="card-header">
            <el-icon color="#409EFF"><HotWater /></el-icon>
            <span>今日热点 TOP10</span>
            <el-tag v-if="hotWeibo.error" type="danger" size="small" style="margin-left:auto">加载失败</el-tag>
          </div>
        </template>
        <HotWeibo :data="hotWeibo.data" :loading="hotWeibo.loading" :error="hotWeibo.error" @retry="loadHotWeibo" />
      </el-card>

      <!-- 关键词趋势 + 情感分析 -->
      <el-row :gutter="16">
        <el-col :xs="24" :lg="14">
          <el-card shadow="never" class="section-card">
            <template #header>
              <div class="card-header">
                <el-icon color="#e6a23c"><TrendCharts /></el-icon>
                <span>关键词趋势</span>
                <el-tag v-if="keywordTrend.error" type="danger" size="small" style="margin-left:auto">加载失败</el-tag>
              </div>
            </template>
            <KeywordTrend :data="keywordTrend.data" :loading="keywordTrend.loading" :error="keywordTrend.error" @retry="loadKeywordTrend" />
          </el-card>
        </el-col>
        <el-col :xs="24" :lg="10">
          <el-card shadow="never" class="section-card">
            <template #header>
              <div class="card-header">
                <el-icon color="#67c23a"><PieChart /></el-icon>
                <span>用户情绪分析</span>
                <el-tag v-if="sentiment.error" type="danger" size="small" style="margin-left:auto">加载失败</el-tag>
              </div>
            </template>
            <Sentiment :data="sentiment.data" :loading="sentiment.loading" :error="sentiment.error" @retry="loadSentiment" />
          </el-card>
        </el-col>
      </el-row>

      <!-- 影响力排行 -->
      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="card-header">
            <el-icon color="#f56c6c"><Trophy /></el-icon>
            <span>影响力账号排行</span>
            <el-tag v-if="influencers.error" type="danger" size="small" style="margin-left:auto">加载失败</el-tag>
          </div>
        </template>
        <Influencers :data="influencers.data" :loading="influencers.loading" :error="influencers.error" @retry="loadInfluencers" />
      </el-card>

      <!-- AI 日报（优先级3，最后加载） -->
      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="card-header">
            <el-icon color="#909399"><Document /></el-icon>
            <span>AI 舆情日报</span>
            <el-tag size="small" type="info" style="margin-left:8px">基于 API 数据自动生成</el-tag>
            <el-tag v-if="dailyReport.error" type="danger" size="small" style="margin-left:auto">加载失败</el-tag>
          </div>
        </template>
        <DailyReport :data="dailyReport.data" :loading="dailyReport.loading" :error="dailyReport.error" @retry="loadDailyReport" />
      </el-card>
    </el-main>

    <el-footer class="footer">
      <span>数据来源：微博分析 API · 最后更新：{{ lastUpdate }}</span>
    </el-footer>
  </div>
  </el-config-provider>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
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

const refreshing = ref(false)
const lastUpdate = ref('—')

const stats = reactive({
  hotCount: 0,
  keywordCount: 0,
  positiveRate: 0,
  influencerCount: 0,
})

// 每个模块独立状态：loading / data / error
const hotWeibo = reactive({ loading: false, data: [], error: null })
const keywordTrend = reactive({ loading: false, data: {}, error: null })
const sentiment = reactive({ loading: false, data: null, error: null })
const influencers = reactive({ loading: false, data: { followers: [], engagement: [] }, error: null })
const dailyReport = reactive({ loading: false, data: '', error: null })

const KEYWORDS = ['豆包', '飞书', 'Agent', '大模型', 'AI办公', 'ChatGPT', '企业AI', '智能体']

// ============================================================
// 优先级1：热点微博（打开立即加载，最快展示）
// ============================================================
async function loadHotWeibo() {
  hotWeibo.loading = true
  hotWeibo.error = null
  try {
    const res = await getHotWeibo(20)
    hotWeibo.data = res.data || []
    stats.hotCount = res.total || 0
  } catch (e) {
    hotWeibo.error = e.message || '加载失败'
    console.error('热点微博加载失败:', e)
  } finally {
    hotWeibo.loading = false
  }
}

// ============================================================
// 优先级1：关键词趋势（前2个关键词先加载，其余后台加载）
// ============================================================
async function loadKeywordTrend() {
  keywordTrend.loading = true
  keywordTrend.error = null
  const results = {}
  let loadedCount = 0

  try {
    // 先加载前2个关键词，快速展示图表
    for (const kw of KEYWORDS.slice(0, 2)) {
      try {
        const res = await getKeywordTrend(kw, 30)
        results[kw] = res
        loadedCount++
      } catch (e) {
        console.warn(`关键词 ${kw} 加载失败:`, e.message)
      }
    }
    // 前2个加载完就更新数据，让图表先显示
    keywordTrend.data = { ...results }
    stats.keywordCount = loadedCount

    // 后台加载剩余关键词
    for (const kw of KEYWORDS.slice(2)) {
      try {
        const res = await getKeywordTrend(kw, 30)
        results[kw] = res
        loadedCount++
        keywordTrend.data = { ...results }
        stats.keywordCount = loadedCount
      } catch (e) {
        console.warn(`关键词 ${kw} 加载失败:`, e.message)
      }
    }
  } catch (e) {
    keywordTrend.error = e.message || '加载失败'
  } finally {
    keywordTrend.loading = false
  }
}

// ============================================================
// 优先级2：情感分析
// ============================================================
async function loadSentiment() {
  sentiment.loading = true
  sentiment.error = null
  try {
    const res = await getSentiment(1000)
    sentiment.data = res
    stats.positiveRate = res.positive_ratio || 0
  } catch (e) {
    sentiment.error = e.message || '加载失败'
    console.error('情感分析加载失败:', e)
  } finally {
    sentiment.loading = false
  }
}

// ============================================================
// 优先级2：影响力排行（粉丝+互动并行）
// ============================================================
async function loadInfluencers() {
  influencers.loading = true
  influencers.error = null
  try {
    const [followersRes, engagementRes] = await Promise.allSettled([
      getInfluencers('followers', 10),
      getInfluencers('engagement', 10),
    ])
    if (followersRes.status === 'fulfilled') {
      influencers.data.followers = followersRes.value.data || []
      stats.influencerCount = (followersRes.value.data || []).length
    }
    if (engagementRes.status === 'fulfilled') {
      influencers.data.engagement = engagementRes.value.data || []
    }
  } catch (e) {
    influencers.error = e.message || '加载失败'
  } finally {
    influencers.loading = false
  }
}

// ============================================================
// 优先级3：AI 日报（最慢，最后加载，不影响其他模块）
// ============================================================
async function loadDailyReport() {
  dailyReport.loading = true
  dailyReport.error = null
  try {
    const res = await getDailyReport()
    dailyReport.data = res.report || res.content || ''
  } catch (e) {
    dailyReport.error = e.message || '加载失败'
    console.error('日报加载失败:', e)
  } finally {
    dailyReport.loading = false
  }
}

// ============================================================
// 分优先级加载：不等待所有接口，数据回来立即展示
// ============================================================
async function loadAll() {
  refreshing.value = true

  // 优先级1：立即加载热点和关键词（用户最先看到）
  loadHotWeibo()
  loadKeywordTrend()

  // 优先级2：延迟 100ms 加载情感和影响力（避免同时发起太多请求）
  setTimeout(() => {
    loadSentiment()
    loadInfluencers()
  }, 100)

  // 优先级3：延迟 500ms 加载日报（最慢，最后加载）
  setTimeout(() => {
    loadDailyReport()
  }, 500)

  // 等待优先级1完成就更新时间（不等待全部）
  try {
    await Promise.race([
      hotWeibo.loading ? new Promise(r => { const check = setInterval(() => { if (!hotWeibo.loading) { clearInterval(check); r() } }, 100) }) : Promise.resolve(),
      new Promise(r => setTimeout(r, 5000)),
    ])
    lastUpdate.value = new Date().toLocaleString('zh-CN')
  } catch (e) {
    // ignore
  }

  refreshing.value = false
}

function refreshAll() {
  // 重置所有状态
  hotWeibo.data = []
  keywordTrend.data = {}
  sentiment.data = null
  influencers.data = { followers: [], engagement: [] }
  dailyReport.data = ''
  stats.hotCount = 0
  stats.keywordCount = 0
  stats.positiveRate = 0
  stats.influencerCount = 0
  loadAll()
  ElMessage.info('正在刷新数据...')
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
