<template>
  <el-config-provider :locale="zhCn">
  <div class="app-layout">
    <!-- 左侧导航 -->
    <aside class="sidebar">
      <div class="sidebar-brand">
        <div class="brand-mark">微</div>
        <div class="brand-name">微博舆情</div>
      </div>

      <nav class="sidebar-nav">
        <div class="nav-section">工作台</div>
        <div
          v-for="item in menuItems"
          :key="item.key"
          class="nav-item"
          :class="{ active: activeMenu === item.key }"
          @click="activeMenu = item.key"
        >
          <el-icon :size="16"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </div>
      </nav>

      <div class="sidebar-bottom">
        <div class="env-tag">
          <span class="env-dot"></span>
          生产环境
        </div>
      </div>
    </aside>

    <!-- 主区域 -->
    <div class="main">
      <!-- 顶部栏 -->
      <header class="topbar">
        <div class="topbar-left">
          <h1 class="page-title">{{ currentPageTitle }}</h1>
          <span class="page-date">{{ todayStr }}</span>
        </div>
        <div class="topbar-right">
          <div class="risk-chip" :class="riskLevel.class">
            <span class="risk-dot"></span>
            {{ riskLevel.text }}
          </div>
          <span class="divider-v"></span>
          <span class="dataset-label">AI 行业</span>
          <span class="update-time">{{ lastUpdate }}</span>
          <el-button size="small" :icon="Refresh" :loading="refreshing" @click="refreshAll">
            刷新
          </el-button>
        </div>
      </header>

      <!-- 内容 -->
      <main class="content">
        <!-- ========== 总览页 ========== -->
        <div v-show="activeMenu === 'overview'">
          <!-- 今日舆情概览：3个核心指标 -->
          <div class="overview-row">
            <div class="overview-card">
              <div class="ov-label">舆情热度</div>
              <div class="ov-value">
                {{ stats.hotCount || '—' }}
                <span class="ov-unit">条热议</span>
              </div>
              <div class="ov-hint">{{ hotHint }}</div>
            </div>
            <div class="overview-card">
              <div class="ov-label">关注话题</div>
              <div class="ov-value">
                {{ topKeyword || '—' }}
                <span class="ov-unit">{{ topKeywordCount ? topKeywordCount + ' 次提及' : '' }}</span>
              </div>
              <div class="ov-hint">{{ keywordHint }}</div>
            </div>
            <div class="overview-card">
              <div class="ov-label">风险状态</div>
              <div class="ov-value" :class="riskLevel.class">
                {{ riskLevel.text }}
                <span class="ov-unit">负面 {{ stats.negativeRate || 0 }}%</span>
              </div>
              <div class="ov-hint">{{ riskHint }}</div>
            </div>
          </div>

          <!-- 今日观察 + 风险 -->
          <div class="two-col">
            <div class="panel">
              <div class="panel-head">
                <span class="panel-title">今日观察</span>
                <span class="panel-sub">基于今日数据整理</span>
              </div>
              <div class="panel-body">
                <div v-if="insights.length" class="observe-list">
                  <div v-for="(item, idx) in insights" :key="idx" class="observe-item">
                    <span class="observe-num">{{ idx + 1 }}</span>
                    <span class="observe-text">{{ item.text }}</span>
                  </div>
                </div>
                <el-skeleton v-else :rows="3" animated />
              </div>
            </div>

            <div class="panel risk-panel">
              <div class="panel-head">
                <span class="panel-title">情绪分布</span>
              </div>
              <div class="panel-body">
                <Sentiment :data="sentiment.data" :loading="sentiment.loading" :error="sentiment.error" @retry="loadSentiment" />
              </div>
            </div>
          </div>

          <!-- 今日热搜担当 -->
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title">今日热搜担当</span>
              <span class="panel-sub">按互动量排序</span>
            </div>
            <div class="panel-body">
              <HotWeibo :data="hotWeibo.data" :loading="hotWeibo.loading" :error="hotWeibo.error" @retry="loadHotWeibo" />
            </div>
          </div>

          <!-- 话题走势 -->
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title">话题走势</span>
              <span class="panel-sub">近 30 天</span>
            </div>
            <div class="panel-body">
              <KeywordTrend :data="keywordTrend.data" :loading="keywordTrend.loading" :error="keywordTrend.error" @retry="loadKeywordTrend" />
            </div>
          </div>
        </div>

        <!-- ========== 热点页 ========== -->
        <div v-show="activeMenu === 'hot'">
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title">热点微博</span>
              <span class="panel-sub">TOP 20</span>
            </div>
            <div class="panel-body">
              <HotWeibo :data="hotWeibo.data" :loading="hotWeibo.loading" :error="hotWeibo.error" @retry="loadHotWeibo" />
            </div>
          </div>
        </div>

        <!-- ========== 趋势页 ========== -->
        <div v-show="activeMenu === 'trend'">
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title">话题走势</span>
              <span class="panel-sub">{{ KEYWORDS.length }} 个关键词 · 近 30 天</span>
            </div>
            <div class="panel-body">
              <KeywordTrend :data="keywordTrend.data" :loading="keywordTrend.loading" :error="keywordTrend.error" @retry="loadKeywordTrend" />
            </div>
          </div>
        </div>

        <!-- ========== 情绪页 ========== -->
        <div v-show="activeMenu === 'sentiment'">
          <div class="two-col">
            <div class="panel">
              <div class="panel-head">
                <span class="panel-title">情绪分布</span>
              </div>
              <div class="panel-body">
                <Sentiment :data="sentiment.data" :loading="sentiment.loading" :error="sentiment.error" @retry="loadSentiment" />
              </div>
            </div>
            <div class="panel">
              <div class="panel-head">
                <span class="panel-title">数据说明</span>
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

        <!-- ========== 影响力页 ========== -->
        <div v-show="activeMenu === 'influencer'">
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title">影响力账号</span>
              <span class="panel-sub">粉丝量 + 互动量</span>
            </div>
            <div class="panel-body">
              <Influencers :data="influencers.data" :loading="influencers.loading" :error="influencers.error" @retry="loadInfluencers" />
            </div>
          </div>
        </div>

        <!-- ========== 日报页 ========== -->
        <div v-show="activeMenu === 'report'">
          <div class="panel">
            <div class="panel-head">
              <span class="panel-title">每日简报</span>
              <span class="panel-sub">{{ todayStr }}</span>
              <el-button size="small" :icon="Download" plain style="margin-left:auto">导出</el-button>
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
  Refresh, Odometer, HotWater, TrendCharts, PieChart,
  Trophy, Document, Download,
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
const lastUpdate = ref('—')

const todayStr = computed(() => {
  const d = new Date()
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
})

const menuItems = [
  { key: 'overview', label: '总览', icon: Odometer },
  { key: 'hot', label: '热点', icon: HotWater },
  { key: 'trend', label: '趋势', icon: TrendCharts },
  { key: 'sentiment', label: '情绪', icon: PieChart },
  { key: 'influencer', label: '账号', icon: Trophy },
  { key: 'report', label: '简报', icon: Document },
]

const currentPageTitle = computed(() => {
  const m = menuItems.find(i => i.key === activeMenu.value)
  return m ? m.label : '总览'
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

const hotWeibo = reactive({ loading: false, data: [], error: null })
const keywordTrend = reactive({ loading: false, data: {}, error: null })
const sentiment = reactive({ loading: false, data: null, error: null })
const influencers = reactive({ loading: false, data: { followers: [], engagement: [] }, error: null })
const dailyReport = reactive({ loading: false, data: '', error: null })

// 风险等级
const riskLevel = computed(() => {
  const neg = stats.negativeRate || 0
  if (neg < 5) return { class: 'low', text: '平稳' }
  if (neg < 15) return { class: 'medium', text: '需关注' }
  if (neg < 30) return { class: 'high', text: '有波动' }
  return { class: 'critical', text: '需响应' }
})

// 最热关键词
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

// 有温度的文案
const hotHint = computed(() => {
  if (!hotWeibo.data || hotWeibo.data.length === 0) return '数据加载中…'
  const top = hotWeibo.data[0]
  if (top && top.username) {
    return `@${top.username} 今天最出圈`
  }
  return '今天讨论热度正常'
})

const keywordHint = computed(() => {
  if (!keywordTrend.data || Object.keys(keywordTrend.data).length < 2) return '话题数据收集中…'
  const entries = Object.entries(keywordTrend.data)
    .map(([kw, d]) => ({ kw, count: d?.total_mentions || 0 }))
    .sort((a, b) => b.count - a.count)
  if (entries.length >= 2) {
    return `${entries[1].kw}、${entries[2]?.kw || '其他'} 紧随其后`
  }
  return '大家都在聊 AI'
})

const riskHint = computed(() => {
  const neg = stats.negativeRate || 0
  if (neg < 5) return '评论区没有明显开战迹象'
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

// 今日观察（自然文案）
const insights = computed(() => {
  const list = []
  if (keywordTrend.data && Object.keys(keywordTrend.data).length > 0) {
    const entries = Object.entries(keywordTrend.data)
      .map(([kw, d]) => ({ kw, count: d?.total_mentions || 0 }))
      .sort((a, b) => b.count - a.count)
    if (entries.length > 0 && entries[0].count > 0) {
      list.push({ text: `今天 AI 圈聊得最多的是「${entries[0].kw}」，被提到 ${entries[0].count} 次。` })
    }
    if (entries.length > 2) {
      list.push({ text: `「${entries[1].kw}」和「${entries[2].kw}」也有不少讨论，产品话题热度集中。` })
    }
  }
  if (hotWeibo.data && hotWeibo.data.length > 0) {
    const top = hotWeibo.data[0]
    if (top && top.username) {
      list.push({ text: `今日热搜担当是 @${top.username}，一条内容收获 ${(top.like_count || 0).toLocaleString()} 个赞。` })
    }
  }
  if (stats.positiveRate > 0) {
    if (stats.negativeRate < 5) {
      list.push({ text: '评论区氛围平稳，没有明显负面情绪聚集。' })
    } else if (stats.negativeRate < 15) {
      list.push({ text: `有 ${stats.negativeRate}% 的负面声音，多为产品体验吐槽，建议留意。` })
    } else {
      list.push({ text: `负面讨论占 ${stats.negativeRate}%，建议看看具体评论在说什么。` })
    }
  }
  return list
})

// ============================================================
// API 调用（保持不变）
// ============================================================
async function loadHotWeibo() {
  hotWeibo.loading = true
  hotWeibo.error = null
  try {
    const res = await getHotWeibo(20)
    hotWeibo.data = res.data || []
    stats.hotCount = res.total || 0
  } catch (e) { hotWeibo.error = e.message || '加载失败' }
  finally { hotWeibo.loading = false }
}

async function loadKeywordTrend() {
  keywordTrend.loading = true
  keywordTrend.error = null
  const results = {}
  let loadedCount = 0
  try {
    for (const kw of KEYWORDS.slice(0, 2)) {
      try { results[kw] = await getKeywordTrend(kw, 30); loadedCount++ }
      catch (e) { console.warn(`关键词 ${kw} 加载失败`) }
    }
    keywordTrend.data = { ...results }
    stats.keywordCount = loadedCount
    for (const kw of KEYWORDS.slice(2)) {
      try { results[kw] = await getKeywordTrend(kw, 30); loadedCount++; keywordTrend.data = { ...results }; stats.keywordCount = loadedCount }
      catch (e) { console.warn(`关键词 ${kw} 加载失败`) }
    }
  } catch (e) { keywordTrend.error = e.message || '加载失败' }
  finally { keywordTrend.loading = false }
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
  } catch (e) { sentiment.error = e.message || '加载失败' }
  finally { sentiment.loading = false }
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
  } catch (e) { influencers.error = e.message || '加载失败' }
  finally { influencers.loading = false }
}

async function loadDailyReport() {
  dailyReport.loading = true
  dailyReport.error = null
  try {
    const res = await getDailyReport()
    dailyReport.data = res.report || res.content || ''
  } catch (e) { dailyReport.error = e.message || '加载失败' }
  finally { dailyReport.loading = false }
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
    lastUpdate.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
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
}

onMounted(() => { loadAll() })
</script>

<style scoped>
/* ===== 基础布局 ===== */
.app-layout {
  display: flex;
  min-height: 100vh;
  background: #f7f8fa;
}

/* ===== 侧边栏 ===== */
.sidebar {
  width: 200px;
  background: #fff;
  border-right: 1px solid #e8e8e8;
  display: flex;
  flex-direction: column;
  position: fixed;
  top: 0; left: 0; bottom: 0;
  z-index: 100;
}
.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px;
  border-bottom: 1px solid #f0f0f0;
}
.brand-mark {
  width: 30px; height: 30px;
  background: #2563eb;
  border-radius: 7px;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 700; font-size: 15px;
}
.brand-name {
  font-size: 15px;
  font-weight: 600;
  color: #1a1a1a;
}
.sidebar-nav {
  flex: 1;
  padding: 12px 10px;
}
.nav-section {
  font-size: 11px;
  color: #999;
  padding: 6px 10px 8px;
  letter-spacing: 0.5px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  color: #595959;
  cursor: pointer;
  font-size: 13.5px;
  transition: background 0.15s;
  margin-bottom: 2px;
}
.nav-item:hover { background: #f5f5f5; color: #1a1a1a; }
.nav-item.active {
  background: #eff4ff;
  color: #2563eb;
  font-weight: 500;
}
.sidebar-bottom {
  padding: 14px 16px;
  border-top: 1px solid #f0f0f0;
}
.env-tag {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: #8c8c8c;
}
.env-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: #52c41a;
}

/* ===== 主区域 ===== */
.main {
  flex: 1;
  margin-left: 200px;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

/* ===== 顶部栏 ===== */
.topbar {
  background: #fff;
  padding: 14px 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e8e8e8;
  position: sticky;
  top: 0;
  z-index: 50;
}
.topbar-left { display: flex; align-items: baseline; gap: 12px; }
.page-title {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: #1a1a1a;
}
.page-date {
  font-size: 13px;
  color: #999;
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.risk-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 12.5px;
  font-weight: 500;
  background: #f6ffed;
  color: #389e0d;
  border: 1px solid #b7eb8f;
}
.risk-chip.medium { background: #fffbe6; color: #d48806; border-color: #ffe58f; }
.risk-chip.high, .risk-chip.critical { background: #fff2f0; color: #cf1322; border-color: #ffccc7; }
.risk-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.divider-v {
  width: 1px;
  height: 16px;
  background: #e8e8e8;
}
.dataset-label {
  font-size: 13px;
  color: #595959;
}
.update-time {
  font-size: 12.5px;
  color: #999;
}

/* ===== 内容区 ===== */
.content {
  padding: 24px 28px;
  flex: 1;
}

/* ===== 今日概览三卡片 ===== */
.overview-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.overview-card {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 18px 20px;
}
.ov-label {
  font-size: 12.5px;
  color: #999;
  margin-bottom: 8px;
}
.ov-value {
  font-size: 24px;
  font-weight: 600;
  color: #1a1a1a;
  line-height: 1.2;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.ov-value.low { color: #389e0d; }
.ov-value.medium { color: #d48806; }
.ov-value.high, .ov-value.critical { color: #cf1322; }
.ov-unit {
  font-size: 13px;
  font-weight: 400;
  color: #999;
}
.ov-hint {
  font-size: 12.5px;
  color: #8c8c8c;
  margin-top: 8px;
}

/* ===== 通用面板 ===== */
.panel {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  margin-bottom: 16px;
  overflow: hidden;
}
.panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 20px;
  border-bottom: 1px solid #f0f0f0;
}
.panel-title {
  font-size: 14.5px;
  font-weight: 600;
  color: #1a1a1a;
}
.panel-sub {
  font-size: 12.5px;
  color: #999;
}
.panel-body {
  padding: 16px 20px;
}

/* ===== 两列布局 ===== */
.two-col {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}

/* ===== 今日观察 ===== */
.observe-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.observe-item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.observe-num {
  width: 22px; height: 22px;
  border-radius: 50%;
  background: #f0f0f0;
  color: #8c8c8c;
  font-size: 12px;
  font-weight: 600;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}
.observe-text {
  font-size: 13.5px;
  color: #434343;
  line-height: 1.65;
}

/* ===== 情绪说明 ===== */
.sentiment-note { padding: 8px 0; }
.note-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  font-size: 13.5px;
  color: #595959;
  border-bottom: 1px solid #f5f5f5;
}
.note-row .danger { color: #cf1322; font-weight: 500; }
.note-divider { height: 16px; }
.note-text {
  font-size: 13px;
  color: #8c8c8c;
  line-height: 1.7;
  margin: 0;
}

/* ===== 响应式 ===== */
@media (max-width: 1024px) {
  .overview-row { grid-template-columns: 1fr; }
  .two-col { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .sidebar { width: 56px; }
  .sidebar-brand .brand-name, .nav-item span, .nav-section, .sidebar-bottom { display: none; }
  .main { margin-left: 56px; }
  .topbar { padding: 12px 16px; flex-wrap: wrap; gap: 8px; }
  .content { padding: 16px; }
  .page-date { display: none; }
}
</style>
