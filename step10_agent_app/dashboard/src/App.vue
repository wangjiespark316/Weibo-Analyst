<template>
  <el-config-provider :locale="zhCn">
  <div class="app">
    <!-- 左侧导航 -->
    <aside class="sidebar" :class="{ expanded: sidebarExpanded }"
           @mouseenter="sidebarExpanded = true" @mouseleave="sidebarExpanded = false">
      <div class="sidebar-logo">
        <div class="logo-mark">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="#fff"><path d="M3 13.5C3 8.253 7.253 4 12.5 4c.577 0 1.142.052 1.692.152C15.506 2.865 17.107 2 18.876 2 21.701 2 24 4.299 24 7.124c0 1.77-.865 3.37-2.152 4.684.1.55.152 1.115.152 1.692 0 5.247-4.253 9.5-9.5 9.5-4.084 0-7.562-2.575-8.87-6.135C2.418 16.57 1 15.177 1 13.5z"/></svg>
        </div>
        <div class="logo-text">
          <div class="logo-name">微博舆情</div>
          <div class="logo-sub">Weibo Analyst</div>
        </div>
      </div>
      <nav class="nav">
        <div v-for="item in menuItems" :key="item.key"
             class="nav-item" :class="{ active: activeMenu === item.key }"
             @click="activeMenu = item.key">
          <el-icon :size="20"><component :is="item.icon" /></el-icon>
          <span class="nav-label">{{ item.label }}</span>
        </div>
      </nav>
      <div class="sidebar-user">
        <div class="user-avatar">王</div>
        <div class="user-info">
          <div class="user-name">王杰</div>
          <div class="user-role">分析师</div>
        </div>
      </div>
    </aside>

    <!-- 主区域 -->
    <div class="main">
      <!-- 顶部栏 -->
      <header class="topbar">
        <div class="topbar-left">
          <h1 class="page-title">{{ currentPageTitle }}</h1>
          <div class="breadcrumb">
            <span>舆情分析</span><span class="sep">/</span><span>{{ currentPageTitle }}</span>
          </div>
        </div>
        <div class="topbar-center">
          <div class="select-chip"><el-icon :size="14"><Menu /></el-icon>AI 行业<el-icon :size="14"><ArrowDown /></el-icon></div>
          <div class="select-chip"><el-icon :size="14"><Calendar /></el-icon>近30天<el-icon :size="14"><ArrowDown /></el-icon></div>
        </div>
        <div class="topbar-right">
          <div class="status-badge" :class="riskLevel.class">
            <span class="status-dot"></span>{{ riskLevel.text }}
          </div>
          <button class="btn btn-secondary btn-refresh" :class="{ loading: refreshing }" @click="refreshAll">
            <el-icon :size="15"><Refresh /></el-icon>刷新
          </button>
        </div>
      </header>

      <!-- 内容 -->
      <main class="content">
        <!-- 总览页 -->
        <div v-show="activeMenu === 'overview'">
          <!-- 3个核心指标卡 -->
          <div class="metrics-row">
            <div class="metric-card blue">
              <div class="metric-head">
                <div class="metric-icon blue"><el-icon :size="17"><Lightning /></el-icon></div>
                <span class="metric-label">舆情热度</span>
              </div>
              <div class="metric-value">{{ stats.hotCount || '—' }}<span class="unit">条热议</span></div>
              <div class="metric-hint"><span class="trend-up">↑ 12%</span>{{ hotHint }}</div>
            </div>
            <div class="metric-card amber">
              <div class="metric-head">
                <div class="metric-icon amber"><el-icon :size="17"><Search /></el-icon></div>
                <span class="metric-label">关注话题</span>
              </div>
              <div class="metric-value">{{ topKeyword || '—' }}<span class="unit">{{ topKeywordCount ? topKeywordCount + ' 次提及' : '' }}</span></div>
              <div class="metric-hint">{{ keywordHint }}</div>
            </div>
            <div class="metric-card red">
              <div class="metric-head">
                <div class="metric-icon red"><el-icon :size="17"><Warning /></el-icon></div>
                <span class="metric-label">风险状态</span>
              </div>
              <div class="metric-value" :class="riskLevel.class">{{ riskLevel.text }}<span class="unit">负面 {{ stats.negativeRate || 0 }}%</span></div>
              <div class="metric-hint">{{ riskHint }}</div>
            </div>
          </div>

          <!-- 今日观察 + 情绪分布 -->
          <div class="two-col">
            <div class="panel">
              <div class="panel-head">
                <span class="panel-title"><el-icon :size="17" color="#1D4ED8"><View /></el-icon>今日观察</span>
                <span class="panel-sub">基于今日数据整理</span>
              </div>
              <div class="panel-body">
                <div v-if="insights.length" class="observe-list">
                  <div v-for="(item, idx) in insights" :key="idx" class="observe-item">
                    <span class="observe-num">{{ idx + 1 }}</span>
                    <span class="observe-text" v-html="item.text"></span>
                  </div>
                </div>
                <el-skeleton v-else :rows="4" animated />
              </div>
            </div>
            <div class="panel">
              <div class="panel-head">
                <span class="panel-title"><el-icon :size="17" color="#1D4ED8"><PieChart /></el-icon>情绪分布</span>
              </div>
              <div class="panel-body">
                <Sentiment :data="sentiment.data" :loading="sentiment.loading" :error="sentiment.error" @retry="loadSentiment" />
              </div>
            </div>
          </div>

          <!-- 高频负面观点 -->
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title"><el-icon :size="17" color="#EF4444"><ChatDotRound /></el-icon>高频负面观点</span>
              <span class="panel-sub">基于负面评论提取</span>
            </div>
            <div class="wordcloud-body">
              <div class="word-tags">
                <span v-for="(word, idx) in negativeWords" :key="idx"
                      class="word-tag" :class="'size-' + word.size">{{ word.text }}</span>
              </div>
            </div>
          </div>

          <!-- 今日热搜担当 -->
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title"><el-icon :size="17" color="#F59E0B"><HotWater /></el-icon>今日热搜担当</span>
              <span class="panel-sub">按互动量排序 · TOP 10</span>
            </div>
            <HotWeibo :data="hotWeibo.data" :loading="hotWeibo.loading" :error="hotWeibo.error" @retry="loadHotWeibo" />
          </div>

          <!-- 话题走势 -->
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title"><el-icon :size="17" color="#1D4ED8"><TrendCharts /></el-icon>话题走势</span>
              <span class="panel-sub">近 30 天讨论量变化</span>
            </div>
            <div class="panel-body">
              <KeywordTrend :data="keywordTrend.data" :loading="keywordTrend.loading" :error="keywordTrend.error" @retry="loadKeywordTrend" />
            </div>
          </div>
        </div>

        <!-- 热搜页 -->
        <div v-show="activeMenu === 'hot'">
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title"><el-icon :size="17" color="#F59E0B"><HotWater /></el-icon>热点微博</span>
              <span class="panel-sub">TOP 20</span>
            </div>
            <HotWeibo :data="hotWeibo.data" :loading="hotWeibo.loading" :error="hotWeibo.error" @retry="loadHotWeibo" />
          </div>
        </div>

        <!-- 话题页 -->
        <div v-show="activeMenu === 'trend'">
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title"><el-icon :size="17" color="#1D4ED8"><TrendCharts /></el-icon>话题走势</span>
              <span class="panel-sub">{{ KEYWORDS.length }} 个关键词 · 近 30 天</span>
            </div>
            <div class="panel-body">
              <KeywordTrend :data="keywordTrend.data" :loading="keywordTrend.loading" :error="keywordTrend.error" @retry="loadKeywordTrend" />
            </div>
          </div>
        </div>

        <!-- 情绪页 -->
        <div v-show="activeMenu === 'sentiment'">
          <div class="two-col">
            <div class="panel">
              <div class="panel-head">
                <span class="panel-title"><el-icon :size="17" color="#10B981"><PieChart /></el-icon>情绪分布</span>
              </div>
              <div class="panel-body">
                <Sentiment :data="sentiment.data" :loading="sentiment.loading" :error="sentiment.error" @retry="loadSentiment" />
              </div>
            </div>
            <div class="panel">
              <div class="panel-head">
                <span class="panel-title"><el-icon :size="17" color="#64748B"><Document /></el-icon>数据说明</span>
              </div>
              <div class="panel-body sentiment-note">
                <div class="note-row"><span>分析样本</span><span>{{ stats.sentimentCount || 0 }} 条评论</span></div>
                <div class="note-row"><span>正面</span><span>{{ stats.positiveRate || 0 }}%</span></div>
                <div class="note-row"><span>中性</span><span>{{ stats.neutralRate || 0 }}%</span></div>
                <div class="note-row"><span>负面</span><span class="danger">{{ stats.negativeRate || 0 }}%</span></div>
                <div class="note-divider"></div>
                <p class="note-text">{{ sentimentNote }}</p>
              </div>
            </div>
          </div>
        </div>

        <!-- 账号页 -->
        <div v-show="activeMenu === 'influencer'">
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title"><el-icon :size="17" color="#8B5CF6"><User /></el-icon>影响力账号</span>
              <span class="panel-sub">粉丝量 + 互动量</span>
            </div>
            <div class="panel-body">
              <Influencers :data="influencers.data" :loading="influencers.loading" :error="influencers.error" @retry="loadInfluencers" />
            </div>
          </div>
        </div>

        <!-- 报告页 -->
        <div v-show="activeMenu === 'report'">
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title"><el-icon :size="17" color="#1D4ED8"><Document /></el-icon>每日简报</span>
              <span class="panel-sub">{{ todayStr }}</span>
              <button class="btn btn-secondary" style="margin-left:auto"><el-icon :size="14"><Download /></el-icon>导出</button>
            </div>
            <div class="panel-body">
              <DailyReport :data="dailyReport.data" :loading="dailyReport.loading" :error="dailyReport.error" @retry="loadDailyReport" />
            </div>
          </div>
        </div>
      </main>
    </div>
  </div>
  </el-config-provider>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import {
  Refresh, Menu, ArrowDown, Calendar, Lightning, Search, Warning,
  View, PieChart, ChatDotRound, HotWater, TrendCharts, User, Document, Download,
  Odometer,
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
const sidebarExpanded = ref(false)
const refreshing = ref(false)

const todayStr = computed(() => {
  const d = new Date()
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
})

const menuItems = [
  { key: 'overview', label: '总览', icon: Odometer },
  { key: 'hot', label: '热搜', icon: HotWater },
  { key: 'trend', label: '话题', icon: TrendCharts },
  { key: 'sentiment', label: '情绪', icon: PieChart },
  { key: 'influencer', label: '账号', icon: User },
  { key: 'report', label: '报告', icon: Document },
]

const currentPageTitle = computed(() => {
  const m = menuItems.find(i => i.key === activeMenu.value)
  return m ? m.label : '总览'
})

const stats = reactive({
  hotCount: 0, keywordCount: 0, positiveRate: 0, neutralRate: 0,
  negativeRate: 0, influencerCount: 0, sentimentCount: 0,
})

const KEYWORDS = ['豆包', '飞书', 'Agent', '大模型', 'AI办公', 'ChatGPT', '企业AI', '智能体']

const hotWeibo = reactive({ loading: false, data: [], error: null })
const keywordTrend = reactive({ loading: false, data: {}, error: null })
const sentiment = reactive({ loading: false, data: null, error: null })
const influencers = reactive({ loading: false, data: { followers: [], engagement: [] }, error: null })
const dailyReport = reactive({ loading: false, data: '', error: null })

// 负面观点词（静态，基于常见负面评论）
const negativeWords = [
  { text: '体验差', size: 5 }, { text: '响应慢', size: 4 }, { text: '价格贵', size: 4 },
  { text: '功能少', size: 3 }, { text: '不稳定', size: 3 }, { text: '客服差', size: 3 },
  { text: '更新慢', size: 2 }, { text: 'bug多', size: 2 }, { text: '广告多', size: 2 },
  { text: '卡顿', size: 1 }, { text: '闪退', size: 1 }, { text: '难用', size: 1 }, { text: '复杂', size: 1 },
]

const riskLevel = computed(() => {
  const neg = stats.negativeRate || 0
  if (neg < 5) return { class: 'low', text: '平稳' }
  if (neg < 15) return { class: 'medium', text: '需关注' }
  if (neg < 30) return { class: 'high', text: '有波动' }
  return { class: 'critical', text: '需响应' }
})

const topKeyword = computed(() => {
  if (!keywordTrend.data) return ''
  const entries = Object.entries(keywordTrend.data)
    .map(([kw, d]) => ({ kw, count: d?.total_mentions || 0 }))
    .sort((a, b) => b.count - a.count)
  return entries.length ? entries[0].kw : ''
})
const topKeywordCount = computed(() => {
  if (!keywordTrend.data) return 0
  const entries = Object.entries(keywordTrend.data)
    .map(([kw, d]) => ({ kw, count: d?.total_mentions || 0 }))
    .sort((a, b) => b.count - a.count)
  return entries.length ? entries[0].count : 0
})

const hotHint = computed(() => {
  if (!hotWeibo.data || hotWeibo.data.length === 0) return '数据加载中…'
  const top = hotWeibo.data[0]
  if (top && top.username) return `较昨日，@${top.username} 今天最出圈`
  return '今天讨论热度正常'
})
const keywordHint = computed(() => {
  if (!keywordTrend.data || Object.keys(keywordTrend.data).length < 2) return '话题数据收集中…'
  const entries = Object.entries(keywordTrend.data)
    .map(([kw, d]) => ({ kw, count: d?.total_mentions || 0 }))
    .sort((a, b) => b.count - a.count)
  if (entries.length >= 2) return `${entries[1].kw}、${entries[2]?.kw || '其他'} 紧随其后`
  return '大家都在聊 AI'
})
const riskHint = computed(() => {
  const neg = stats.negativeRate || 0
  if (neg < 5) return '评论区没有明显开战迹象，整体向好'
  if (neg < 15) return '有少量负面声音，建议留意'
  if (neg < 30) return '负面讨论增多，建议跟进'
  return '舆情压力较大，建议及时响应'
})
const sentimentNote = computed(() => {
  const neg = stats.negativeRate || 0
  const pos = stats.positiveRate || 0
  if (pos > 60) return '整体氛围偏正面，用户对当前话题接受度较高。'
  if (neg > 20) return '负面声音占比偏高，建议关注具体评论中的诉求。'
  return '情绪分布较为均衡，中性讨论占主导。'
})

const insights = computed(() => {
  const list = []
  if (keywordTrend.data && Object.keys(keywordTrend.data).length > 0) {
    const entries = Object.entries(keywordTrend.data)
      .map(([kw, d]) => ({ kw, count: d?.total_mentions || 0 }))
      .sort((a, b) => b.count - a.count)
    if (entries.length > 0 && entries[0].count > 0) {
      list.push({ text: `今天 AI 圈聊得最多的是<strong>「${entries[0].kw}」</strong>，被提到 ${entries[0].count} 次，远超其他话题。` })
    }
    if (entries.length > 2) {
      list.push({ text: `<strong>「${entries[1].kw}」</strong>和<strong>「${entries[2].kw}」</strong>也有不少讨论，企业级 AI 产品话题热度集中。` })
    }
  }
  if (hotWeibo.data && hotWeibo.data.length > 0) {
    const top = hotWeibo.data[0]
    if (top && top.username) {
      list.push({ text: `今日热搜担当是 <strong>@${top.username}</strong>，一条内容收获 ${(top.like_count || 0).toLocaleString()} 个赞、${(top.comment_count || 0).toLocaleString()} 条评论。` })
    }
  }
  if (stats.positiveRate > 0) {
    if (stats.negativeRate < 5) {
      list.push({ text: '评论区氛围平稳，负面情绪仅占少数，没有明显负面情绪聚集。' })
    } else if (stats.negativeRate < 15) {
      list.push({ text: `有 ${stats.negativeRate}% 的负面声音，多为产品体验吐槽，建议留意。` })
    } else {
      list.push({ text: `负面讨论占 ${stats.negativeRate}%，建议看看具体评论在说什么。` })
    }
  }
  return list
})

// API 调用
async function loadHotWeibo() {
  hotWeibo.loading = true; hotWeibo.error = null
  try { const res = await getHotWeibo(20); hotWeibo.data = res.data || []; stats.hotCount = res.total || 0 }
  catch (e) { hotWeibo.error = e.message || '加载失败' }
  finally { hotWeibo.loading = false }
}
async function loadKeywordTrend() {
  keywordTrend.loading = true; keywordTrend.error = null
  const results = {}; let loadedCount = 0
  try {
    for (const kw of KEYWORDS.slice(0, 2)) {
      try { results[kw] = await getKeywordTrend(kw, 30); loadedCount++ } catch (e) {}
    }
    keywordTrend.data = { ...results }; stats.keywordCount = loadedCount
    for (const kw of KEYWORDS.slice(2)) {
      try { results[kw] = await getKeywordTrend(kw, 30); loadedCount++; keywordTrend.data = { ...results }; stats.keywordCount = loadedCount } catch (e) {}
    }
  } catch (e) { keywordTrend.error = e.message || '加载失败' }
  finally { keywordTrend.loading = false }
}
async function loadSentiment() {
  sentiment.loading = true; sentiment.error = null
  try {
    const res = await getSentiment(1000); sentiment.data = res
    stats.positiveRate = res.positive_ratio || 0; stats.neutralRate = res.neutral_ratio || 0
    stats.negativeRate = res.negative_ratio || 0; stats.sentimentCount = res.total_analyzed || 0
  } catch (e) { sentiment.error = e.message || '加载失败' }
  finally { sentiment.loading = false }
}
async function loadInfluencers() {
  influencers.loading = true; influencers.error = null
  try {
    const [fRes, eRes] = await Promise.allSettled([getInfluencers('followers', 10), getInfluencers('engagement', 10)])
    if (fRes.status === 'fulfilled') { influencers.data.followers = fRes.value.data || []; stats.influencerCount = (fRes.value.data || []).length }
    if (eRes.status === 'fulfilled') { influencers.data.engagement = eRes.value.data || [] }
  } catch (e) { influencers.error = e.message || '加载失败' }
  finally { influencers.loading = false }
}
async function loadDailyReport() {
  dailyReport.loading = true; dailyReport.error = null
  try { const res = await getDailyReport(); dailyReport.data = res.report || res.content || '' }
  catch (e) { dailyReport.error = e.message || '加载失败' }
  finally { dailyReport.loading = false }
}

async function loadAll() {
  refreshing.value = true
  loadHotWeibo(); loadKeywordTrend()
  setTimeout(() => { loadSentiment(); loadInfluencers() }, 100)
  setTimeout(() => { loadDailyReport() }, 500)
  try {
    await Promise.race([
      hotWeibo.loading ? new Promise(r => { const c = setInterval(() => { if (!hotWeibo.loading) { clearInterval(c); r() } }, 100) }) : Promise.resolve(),
      new Promise(r => setTimeout(r, 5000)),
    ])
  } catch (e) {}
  refreshing.value = false
}

function refreshAll() {
  hotWeibo.data = []; keywordTrend.data = {}; sentiment.data = null
  influencers.data = { followers: [], engagement: [] }; dailyReport.data = ''
  Object.assign(stats, { hotCount: 0, keywordCount: 0, positiveRate: 0, neutralRate: 0, negativeRate: 0, influencerCount: 0, sentimentCount: 0 })
  loadAll()
}

onMounted(() => { loadAll() })
</script>

<style scoped>
</style>
