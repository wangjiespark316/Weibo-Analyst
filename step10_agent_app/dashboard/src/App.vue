<template>
  <el-config-provider :locale="zhCn">
  <div class="app-layout">
    <!-- 左侧导航栏 -->
    <aside class="sidebar">
      <div class="sidebar-logo">
        <div class="logo-icon">
          <el-icon :size="22"><DataAnalysis /></el-icon>
        </div>
        <div class="logo-text">
          <div class="logo-title">微博舆情</div>
          <div class="logo-sub">Weibo Analyst</div>
        </div>
      </div>

      <nav class="sidebar-nav">
        <div
          v-for="item in menuItems"
          :key="item.key"
          class="nav-item"
          :class="{ active: activeMenu === item.key }"
          @click="activeMenu = item.key"
        >
          <el-icon :size="18"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
          <el-tag v-if="item.badge" :type="item.badgeType" size="small" effect="dark">{{ item.badge }}</el-tag>
        </div>
      </nav>

      <div class="sidebar-footer">
        <div class="footer-status">
          <span class="status-dot online"></span>
          <span>数据服务正常</span>
        </div>
        <div class="footer-version">v2.0.0 Enterprise</div>
      </div>
    </aside>

    <!-- 主内容区 -->
    <div class="main-wrapper">
      <!-- 顶部企业信息栏 -->
      <header class="topbar">
        <div class="topbar-left">
          <h2 class="page-title">{{ currentPageTitle }}</h2>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>舆情分析平台</el-breadcrumb-item>
            <el-breadcrumb-item>{{ currentPageTitle }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="topbar-right">
          <!-- 风险等级指示器 -->
          <div class="risk-indicator" :class="riskLevel.class">
            <el-icon :size="16"><Warning /></el-icon>
            <span>风险等级：{{ riskLevel.text }}</span>
          </div>
          <el-divider direction="vertical" />
          <el-tag type="success" effect="light" round>
            <el-icon style="margin-right:4px"><Connection /></el-icon>
            AI 行业数据集
          </el-tag>
          <div class="update-time">
            <el-icon :size="14"><Clock /></el-icon>
            <span>{{ lastUpdate }}</span>
          </div>
          <el-button type="primary" :icon="Refresh" :loading="refreshing" @click="refreshAll" plain>
            刷新数据
          </el-button>
        </div>
      </header>

      <!-- 内容区 -->
      <main class="content">
        <!-- 数据总览页 -->
        <div v-show="activeMenu === 'overview'">
          <!-- 核心指标卡片 -->
          <el-row :gutter="16" class="metrics-row">
            <el-col :xs="12" :sm="6" :md="6">
              <div class="metric-card">
                <div class="metric-icon blue">
                  <el-icon :size="24"><TrendCharts /></el-icon>
                </div>
                <div class="metric-content">
                  <div class="metric-value">{{ stats.hotCount || '—' }}</div>
                  <div class="metric-label">热点微博</div>
                  <div class="metric-trend up">
                    <el-icon><Top /></el-icon> 实时更新
                  </div>
                </div>
              </div>
            </el-col>
            <el-col :xs="12" :sm="6" :md="6">
              <div class="metric-card">
                <div class="metric-icon orange">
                  <el-icon :size="24"><Search /></el-icon>
                </div>
                <div class="metric-content">
                  <div class="metric-value">{{ stats.keywordCount || '—' }}</div>
                  <div class="metric-label">关键词监测</div>
                  <div class="metric-trend">
                    <el-icon><Coin /></el-icon> {{ KEYWORDS.length }} 个关键词
                  </div>
                </div>
              </div>
            </el-col>
            <el-col :xs="12" :sm="6" :md="6">
              <div class="metric-card">
                <div class="metric-icon green">
                  <el-icon :size="24"><CircleCheck /></el-icon>
                </div>
                <div class="metric-content">
                  <div class="metric-value">{{ stats.positiveRate ? stats.positiveRate + '%' : '—' }}</div>
                  <div class="metric-label">正面情绪占比</div>
                  <div class="metric-trend" :class="stats.positiveRate > 50 ? 'up' : 'down'">
                    <el-icon>{{ stats.positiveRate > 50 ? 'Top' : 'Bottom' }}</el-icon>
                    舆情{{ stats.positiveRate > 50 ? '向好' : '需关注' }}
                  </div>
                </div>
              </div>
            </el-col>
            <el-col :xs="12" :sm="6" :md="6">
              <div class="metric-card">
                <div class="metric-icon purple">
                  <el-icon :size="24"><User /></el-icon>
                </div>
                <div class="metric-content">
                  <div class="metric-value">{{ stats.influencerCount || '—' }}</div>
                  <div class="metric-label">影响力账号</div>
                  <div class="metric-trend">
                    <el-icon><Trophy /></el-icon> TOP 账号监测
                  </div>
                </div>
              </div>
            </el-col>
          </el-row>

          <!-- 核心洞察 + 风险预警 -->
          <el-row :gutter="16">
            <el-col :xs="24" :lg="16">
              <div class="panel-card">
                <div class="panel-header">
                  <el-icon color="#409EFF"><Lightning /></el-icon>
                  <span class="panel-title">AI 行业核心洞察</span>
                  <el-tag size="small" type="primary" effect="plain">AI 自动生成</el-tag>
                </div>
                <div class="insights-body">
                  <div v-if="insights.length" class="insight-list">
                    <div v-for="(insight, idx) in insights" :key="idx" class="insight-item" :class="insight.type">
                      <div class="insight-icon">
                        <el-icon><component :is="insight.icon" /></el-icon>
                      </div>
                      <div class="insight-text">{{ insight.text }}</div>
                    </div>
                  </div>
                  <el-skeleton v-else :rows="3" animated />
                </div>
              </div>
            </el-col>
            <el-col :xs="24" :lg="8">
              <div class="panel-card risk-panel" :class="riskLevel.class">
                <div class="panel-header">
                  <el-icon><Warning /></el-icon>
                  <span class="panel-title">今日风险评估</span>
                </div>
                <div class="risk-body">
                  <div class="risk-score">
                    <div class="risk-number" :class="riskLevel.class">{{ riskLevel.score }}</div>
                    <div class="risk-label">风险指数</div>
                  </div>
                  <div class="risk-details">
                    <div class="risk-row">
                      <span>负面情绪</span>
                      <span class="risk-value">{{ stats.negativeRate || 0 }}%</span>
                    </div>
                    <div class="risk-row">
                      <span>高风险话题</span>
                      <span class="risk-value">{{ riskTopics }} 个</span>
                    </div>
                    <div class="risk-row">
                      <span>建议动作</span>
                      <span class="risk-value">{{ riskLevel.action }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </el-col>
          </el-row>

          <!-- 热点微博 + 情绪分析 -->
          <el-row :gutter="16">
            <el-col :xs="24" :lg="16">
              <div class="panel-card">
                <div class="panel-header">
                  <el-icon color="#e6a23c"><HotWater /></el-icon>
                  <span class="panel-title">今日热点微博 TOP10</span>
                  <span class="panel-sub">按热度指数排序</span>
                </div>
                <HotWeibo :data="hotWeibo.data" :loading="hotWeibo.loading" :error="hotWeibo.error" @retry="loadHotWeibo" />
              </div>
            </el-col>
            <el-col :xs="24" :lg="8">
              <div class="panel-card">
                <div class="panel-header">
                  <el-icon color="#67c23a"><PieChart /></el-icon>
                  <span class="panel-title">用户情绪分布</span>
                </div>
                <Sentiment :data="sentiment.data" :loading="sentiment.loading" :error="sentiment.error" @retry="loadSentiment" />
              </div>
            </el-col>
          </el-row>

          <!-- 关键词趋势 -->
          <div class="panel-card">
            <div class="panel-header">
              <el-icon color="#409EFF"><TrendCharts /></el-icon>
              <span class="panel-title">AI 关键词趋势</span>
              <span class="panel-sub">近30天提及量变化</span>
            </div>
            <KeywordTrend :data="keywordTrend.data" :loading="keywordTrend.loading" :error="keywordTrend.error" @retry="loadKeywordTrend" />
          </div>
        </div>

        <!-- 热点微博页 -->
        <div v-show="activeMenu === 'hot'">
          <div class="panel-card">
            <div class="panel-header">
              <el-icon color="#e6a23c"><HotWater /></el-icon>
              <span class="panel-title">热点微博全览</span>
              <span class="panel-sub">TOP 20 热门微博</span>
            </div>
            <HotWeibo :data="hotWeibo.data" :loading="hotWeibo.loading" :error="hotWeibo.error" @retry="loadHotWeibo" />
          </div>
        </div>

        <!-- AI趋势页 -->
        <div v-show="activeMenu === 'trend'">
          <div class="panel-card">
            <div class="panel-header">
              <el-icon color="#409EFF"><TrendCharts /></el-icon>
              <span class="panel-title">关键词趋势分析</span>
              <span class="panel-sub">{{ KEYWORDS.length }} 个核心关键词</span>
            </div>
            <KeywordTrend :data="keywordTrend.data" :loading="keywordTrend.loading" :error="keywordTrend.error" @retry="loadKeywordTrend" />
          </div>
        </div>

        <!-- 情绪分析页 -->
        <div v-show="activeMenu === 'sentiment'">
          <el-row :gutter="16">
            <el-col :xs="24" :lg="12">
              <div class="panel-card">
                <div class="panel-header">
                  <el-icon color="#67c23a"><PieChart /></el-icon>
                  <span class="panel-title">情绪分布</span>
                </div>
                <Sentiment :data="sentiment.data" :loading="sentiment.loading" :error="sentiment.error" @retry="loadSentiment" />
              </div>
            </el-col>
            <el-col :xs="24" :lg="12">
              <div class="panel-card risk-panel" :class="riskLevel.class">
                <div class="panel-header">
                  <el-icon><Warning /></el-icon>
                  <span class="panel-title">风险评估详情</span>
                </div>
                <div class="risk-body">
                  <div class="risk-score">
                    <div class="risk-number" :class="riskLevel.class">{{ riskLevel.score }}</div>
                    <div class="risk-label">综合风险指数</div>
                  </div>
                  <div class="risk-details">
                    <div class="risk-row"><span>正面情绪</span><span class="risk-value">{{ stats.positiveRate || 0 }}%</span></div>
                    <div class="risk-row"><span>中性情绪</span><span class="risk-value">{{ stats.neutralRate || 0 }}%</span></div>
                    <div class="risk-row"><span>负面情绪</span><span class="risk-value danger">{{ stats.negativeRate || 0 }}%</span></div>
                    <div class="risk-row"><span>分析样本</span><span class="risk-value">{{ stats.sentimentCount || 0 }} 条</span></div>
                    <div class="risk-row"><span>风险等级</span><span class="risk-value" :class="riskLevel.class">{{ riskLevel.text }}</span></div>
                  </div>
                </div>
              </div>
            </el-col>
          </el-row>
        </div>

        <!-- 影响力页 -->
        <div v-show="activeMenu === 'influencer'">
          <div class="panel-card">
            <div class="panel-header">
              <el-icon color="#f56c6c"><Trophy /></el-icon>
              <span class="panel-title">影响力账号排行</span>
              <span class="panel-sub">粉丝量 + 互动量双维度</span>
            </div>
            <Influencers :data="influencers.data" :loading="influencers.loading" :error="influencers.error" @retry="loadInfluencers" />
          </div>
        </div>

        <!-- AI日报页 -->
        <div v-show="activeMenu === 'report'">
          <div class="panel-card report-panel">
            <div class="panel-header">
              <el-icon color="#909399"><Document /></el-icon>
              <span class="panel-title">AI 舆情日报</span>
              <el-tag size="small" type="info" effect="plain">基于 API 数据自动生成</el-tag>
              <el-button size="small" :icon="Download" plain style="margin-left:auto">导出 Markdown</el-button>
            </div>
            <DailyReport :data="dailyReport.data" :loading="dailyReport.loading" :error="dailyReport.error" @retry="loadDailyReport" />
          </div>
        </div>
      </main>
    </div>
  </div>
  </el-config-provider>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import {
  DataAnalysis, Refresh, TrendCharts, Search, CircleCheck,
  User, HotWater, PieChart, Trophy, Document, Warning,
  Connection, Clock, Lightning, Top, Bottom, Coin, Download,
  Odometer, ChatDotRound, UserFilled, DataLine,
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

const activeMenu = ref('overview')
const refreshing = ref(false)
const lastUpdate = ref('加载中...')

const menuItems = [
  { key: 'overview', label: '数据总览', icon: Odometer },
  { key: 'hot', label: '热点微博', icon: HotWater },
  { key: 'trend', label: 'AI 趋势', icon: TrendCharts },
  { key: 'sentiment', label: '情绪分析', icon: PieChart },
  { key: 'influencer', label: '影响力', icon: Trophy },
  { key: 'report', label: 'AI 日报', icon: Document, badge: 'AI' },
]

const currentPageTitle = computed(() => {
  const item = menuItems.find(m => m.key === activeMenu.value)
  return item ? item.label : '数据总览'
})

const stats = reactive({
  hotCount: 0,
  keywordCount: 0,
  positiveRate: 0,
  neutralRate: 0,
  negativeRate: 0,
  influencerCount: 0,
  sentimentCount: 0,
})

const KEYWORDS = ['豆包', '飞书', 'Agent', '大模型', 'AI办公', 'ChatGPT', '企业AI', '智能体']

// 每个模块独立状态
const hotWeibo = reactive({ loading: false, data: [], error: null })
const keywordTrend = reactive({ loading: false, data: {}, error: null })
const sentiment = reactive({ loading: false, data: null, error: null })
const influencers = reactive({ loading: false, data: { followers: [], engagement: [] }, error: null })
const dailyReport = reactive({ loading: false, data: '', error: null })

// 风险等级计算
const riskLevel = computed(() => {
  const neg = stats.negativeRate || 0
  if (neg < 5) return { class: 'low', text: '低风险', score: '低', action: '正常监测', color: '#67c23a' }
  if (neg < 15) return { class: 'medium', text: '中风险', score: '中', action: '持续关注', color: '#e6a23c' }
  if (neg < 30) return { class: 'high', text: '高风险', score: '高', action: '及时响应', color: '#f56c6c' }
  return { class: 'critical', text: '严重', score: '危', action: '紧急处理', color: '#f56c6c' }
})

const riskTopics = computed(() => {
  return Math.max(0, Math.floor((stats.negativeRate || 0) / 5))
})

// 核心洞察（基于数据自动生成）
const insights = computed(() => {
  const list = []
  if (keywordTrend.data && Object.keys(keywordTrend.data).length > 0) {
    const entries = Object.entries(keywordTrend.data)
      .map(([kw, d]) => ({ kw, count: d?.total_mentions || 0 }))
      .sort((a, b) => b.count - a.count)
    if (entries.length > 0) {
      list.push({
        type: 'info',
        icon: DataLine,
        text: `「${entries[0].kw}」以 ${entries[0].count} 次提及量位居榜首，是当前 AI 行业最受关注的话题。`,
      })
    }
    if (entries.length > 1) {
      list.push({
        type: 'success',
        icon: TrendCharts,
        text: `「${entries[1].kw}」和「${entries[2]?.kw || '其他'}」紧随其后，AI 产品竞争格局日趋激烈。`,
      })
    }
  }
  if (stats.positiveRate > 0) {
    if (stats.positiveRate > 50) {
      list.push({
        type: 'success',
        icon: CircleCheck,
        text: `用户正面情绪占比达 ${stats.positiveRate}%，整体舆情向好，品牌口碑良好。`,
      })
    } else {
      list.push({
        type: 'warning',
        icon: Warning,
        text: `正面情绪占比 ${stats.positiveRate}%，负面情绪 ${stats.negativeRate}%，建议关注用户反馈中的问题点。`,
      })
    }
  }
  if (hotWeibo.data && hotWeibo.data.length > 0) {
    const top = hotWeibo.data[0]
    list.push({
      type: 'info',
      icon: ChatDotRound,
      text: `最热微博来自「${top.username || '未知用户'}」，热度指数 ${top.heat_score || top.hot_score || '—'}，互动量超 ${(top.like_count || 0) + (top.comment_count || 0)}。`,
    })
  }
  return list
})

// ============================================================
// API 调用（保持原有逻辑不变）
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
  } finally {
    hotWeibo.loading = false
  }
}

async function loadKeywordTrend() {
  keywordTrend.loading = true
  keywordTrend.error = null
  const results = {}
  let loadedCount = 0
  try {
    for (const kw of KEYWORDS.slice(0, 2)) {
      try {
        const res = await getKeywordTrend(kw, 30)
        results[kw] = res
        loadedCount++
      } catch (e) { console.warn(`关键词 ${kw} 加载失败`) }
    }
    keywordTrend.data = { ...results }
    stats.keywordCount = loadedCount
    for (const kw of KEYWORDS.slice(2)) {
      try {
        const res = await getKeywordTrend(kw, 30)
        results[kw] = res
        loadedCount++
        keywordTrend.data = { ...results }
        stats.keywordCount = loadedCount
      } catch (e) { console.warn(`关键词 ${kw} 加载失败`) }
    }
  } catch (e) {
    keywordTrend.error = e.message || '加载失败'
  } finally {
    keywordTrend.loading = false
  }
}

async function loadSentiment() {
  sentiment.loading = true
  sentiment.error = null
  try {
    const res = await getSentiment(1000)
    sentiment.data = res
    stats.positiveRate = res.positive_ratio || 0
    stats.neutralRate = res.neutral_ratio || 0
    stats.negativeRate = res.negative_ratio || 0
    stats.sentimentCount = res.total_analyzed || 0
  } catch (e) {
    sentiment.error = e.message || '加载失败'
  } finally {
    sentiment.loading = false
  }
}

async function loadInfluencers() {
  influencers.loading = true
  influencers.error = null
  try {
    const [fRes, eRes] = await Promise.allSettled([
      getInfluencers('followers', 10),
      getInfluencers('engagement', 10),
    ])
    if (fRes.status === 'fulfilled') {
      influencers.data.followers = fRes.value.data || []
      stats.influencerCount = (fRes.value.data || []).length
    }
    if (eRes.status === 'fulfilled') {
      influencers.data.engagement = eRes.value.data || []
    }
  } catch (e) {
    influencers.error = e.message || '加载失败'
  } finally {
    influencers.loading = false
  }
}

async function loadDailyReport() {
  dailyReport.loading = true
  dailyReport.error = null
  try {
    const res = await getDailyReport()
    dailyReport.data = res.report || res.content || ''
  } catch (e) {
    dailyReport.error = e.message || '加载失败'
  } finally {
    dailyReport.loading = false
  }
}

async function loadAll() {
  refreshing.value = true
  loadHotWeibo()
  loadKeywordTrend()
  setTimeout(() => { loadSentiment(); loadInfluencers() }, 100)
  setTimeout(() => { loadDailyReport() }, 500)
  try {
    await Promise.race([
      hotWeibo.loading ? new Promise(r => { const c = setInterval(() => { if (!hotWeibo.loading) { clearInterval(c); r() } }, 100) }) : Promise.resolve(),
      new Promise(r => setTimeout(r, 5000)),
    ])
    lastUpdate.value = new Date().toLocaleString('zh-CN')
  } catch (e) { /* ignore */ }
  refreshing.value = false
}

function refreshAll() {
  hotWeibo.data = []
  keywordTrend.data = {}
  sentiment.data = null
  influencers.data = { followers: [], engagement: [] }
  dailyReport.data = ''
  Object.assign(stats, { hotCount: 0, keywordCount: 0, positiveRate: 0, neutralRate: 0, negativeRate: 0, influencerCount: 0, sentimentCount: 0 })
  loadAll()
  ElMessage.info('正在刷新数据...')
}

onMounted(() => { loadAll() })
</script>

<style scoped>
.app-layout {
  display: flex;
  min-height: 100vh;
  background: #f0f2f5;
}

/* 左侧导航 */
.sidebar {
  width: 220px;
  background: linear-gradient(180deg, #001529 0%, #002140 100%);
  display: flex;
  flex-direction: column;
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  z-index: 100;
}
.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
.logo-icon {
  width: 40px;
  height: 40px;
  background: linear-gradient(135deg, #409EFF, #36cfc9);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}
.logo-title {
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.2;
}
.logo-sub {
  color: rgba(255,255,255,0.45);
  font-size: 11px;
  margin-top: 2px;
}
.sidebar-nav {
  flex: 1;
  padding: 12px 8px;
  overflow-y: auto;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  border-radius: 8px;
  color: rgba(255,255,255,0.65);
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 4px;
  font-size: 14px;
}
.nav-item:hover {
  background: rgba(255,255,255,0.08);
  color: #fff;
}
.nav-item.active {
  background: linear-gradient(90deg, #409EFF, #36cfc9);
  color: #fff;
  font-weight: 600;
  box-shadow: 0 4px 12px rgba(64,158,255,0.3);
}
.sidebar-footer {
  padding: 16px;
  border-top: 1px solid rgba(255,255,255,0.08);
}
.footer-status {
  display: flex;
  align-items: center;
  gap: 8px;
  color: rgba(255,255,255,0.65);
  font-size: 12px;
  margin-bottom: 6px;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #52c41a;
  box-shadow: 0 0 8px #52c41a;
}
.footer-version {
  color: rgba(255,255,255,0.3);
  font-size: 11px;
}

/* 主内容区 */
.main-wrapper {
  flex: 1;
  margin-left: 220px;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.topbar {
  background: #fff;
  padding: 14px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e8e8e8;
  position: sticky;
  top: 0;
  z-index: 50;
}
.topbar-left { display: flex; flex-direction: column; gap: 4px; }
.page-title { margin: 0; font-size: 18px; font-weight: 700; color: #1a1a1a; }
.topbar-right {
  display: flex;
  align-items: center;
  gap: 14px;
}
.risk-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
}
.risk-indicator.low { background: #f6ffed; color: #52c41a; border: 1px solid #b7eb8f; }
.risk-indicator.medium { background: #fffbe6; color: #faad14; border: 1px solid #ffe58f; }
.risk-indicator.high, .risk-indicator.critical { background: #fff2f0; color: #f5222d; border: 1px solid #ffccc7; }
.update-time {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #8c8c8c;
  font-size: 13px;
}

/* 内容区 */
.content {
  padding: 20px 24px;
  flex: 1;
}

/* 指标卡片 */
.metrics-row { margin-bottom: 16px; }
.metric-card {
  background: #fff;
  border-radius: 10px;
  padding: 18px;
  display: flex;
  align-items: center;
  gap: 14px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  transition: transform 0.2s, box-shadow 0.2s;
  margin-bottom: 16px;
}
.metric-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0,0,0,0.1);
}
.metric-icon {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: #fff;
}
.metric-icon.blue { background: linear-gradient(135deg, #409EFF, #1890ff); }
.metric-icon.orange { background: linear-gradient(135deg, #faad14, #fa8c16); }
.metric-icon.green { background: linear-gradient(135deg, #52c41a, #389e0d); }
.metric-icon.purple { background: linear-gradient(135deg, #722ed1, #531dab); }
.metric-content { flex: 1; min-width: 0; }
.metric-value {
  font-size: 26px;
  font-weight: 700;
  color: #1a1a1a;
  line-height: 1.1;
}
.metric-label {
  font-size: 13px;
  color: #8c8c8c;
  margin-top: 3px;
}
.metric-trend {
  font-size: 12px;
  color: #8c8c8c;
  margin-top: 5px;
  display: flex;
  align-items: center;
  gap: 3px;
}
.metric-trend.up { color: #52c41a; }
.metric-trend.down { color: #f5222d; }

/* 面板卡片 */
.panel-card {
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  margin-bottom: 16px;
  overflow: hidden;
}
.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
  font-weight: 600;
  font-size: 15px;
  color: #1a1a1a;
}
.panel-sub {
  font-size: 12px;
  color: #8c8c8c;
  font-weight: 400;
  margin-left: 4px;
}

/* 核心洞察 */
.insights-body { padding: 16px 20px; }
.insight-list { display: flex; flex-direction: column; gap: 12px; }
.insight-item {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 8px;
  background: #fafafa;
  border-left: 3px solid #d9d9d9;
}
.insight-item.info { border-left-color: #409EFF; background: #f0f7ff; }
.insight-item.success { border-left-color: #52c41a; background: #f6ffed; }
.insight-item.warning { border-left-color: #faad14; background: #fffbe6; }
.insight-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: #409EFF;
}
.insight-item.success .insight-icon { color: #52c41a; }
.insight-item.warning .insight-icon { color: #faad14; }
.insight-text {
  font-size: 13.5px;
  color: #434343;
  line-height: 1.6;
}

/* 风险面板 */
.risk-panel { border-top: 3px solid #52c41a; }
.risk-panel.medium { border-top-color: #faad14; }
.risk-panel.high, .risk-panel.critical { border-top-color: #f5222d; }
.risk-body { padding: 20px; }
.risk-score {
  text-align: center;
  padding-bottom: 16px;
  border-bottom: 1px dashed #f0f0f0;
  margin-bottom: 16px;
}
.risk-number {
  font-size: 48px;
  font-weight: 800;
  line-height: 1;
  color: #52c41a;
}
.risk-number.medium { color: #faad14; }
.risk-number.high, .risk-number.critical { color: #f5222d; }
.risk-label {
  font-size: 13px;
  color: #8c8c8c;
  margin-top: 6px;
}
.risk-details { display: flex; flex-direction: column; gap: 10px; }
.risk-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #595959;
}
.risk-value { font-weight: 600; color: #1a1a1a; }
.risk-value.danger { color: #f5222d; }

/* 日报面板 */
.report-panel { min-height: 600px; }

/* 响应式 */
@media (max-width: 992px) {
  .sidebar { width: 64px; }
  .sidebar-logo .logo-text, .nav-item span, .sidebar-footer { display: none; }
  .main-wrapper { margin-left: 64px; }
}
@media (max-width: 768px) {
  .topbar { flex-direction: column; align-items: flex-start; gap: 10px; }
  .topbar-right { flex-wrap: wrap; }
  .content { padding: 12px; }
  .metric-value { font-size: 20px; }
}
</style>
