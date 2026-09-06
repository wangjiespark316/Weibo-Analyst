import axios from 'axios'

// API 基础地址（生产环境直接调用公网 API，开发环境走 Vite proxy）
const API_BASE = import.meta.env.DEV
  ? '/api'
  : 'https://weibo-analyst-api.onrender.com/api'

// 默认 API Key（AI 行业客户）
const DEFAULT_API_KEY = 'wk_test_ai_001'

const http = axios.create({
  baseURL: API_BASE,
  timeout: 15000,
  headers: {
    'Authorization': `Bearer ${DEFAULT_API_KEY}`,
  },
})

// 请求拦截器：记录开始时间
http.interceptors.request.use(
  (config) => {
    config.metadata = { startTime: Date.now() }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器：统一处理错误
http.interceptors.response.use(
  (response) => {
    const elapsed = Date.now() - response.config.metadata?.startTime || 0
    if (elapsed > 3000) {
      console.warn(`[API] 慢请求: ${response.config.url} - ${elapsed}ms`)
    }
    return response.data
  },
  (error) => {
    // 统一错误处理，不白屏
    if (error.code === 'ECONNABORTED') {
      console.error('[API] 请求超时:', error.config?.url)
      error.message = '请求超时，请稍后重试'
    } else if (error.response?.status === 401) {
      console.error('[API] 未授权:', error.config?.url)
      error.message = '未授权访问，请检查 API Key'
    } else if (error.response?.status === 502) {
      console.error('[API] 服务暂不可用 (502):', error.config?.url)
      error.message = '服务暂不可用，请稍后刷新'
    } else if (error.response?.status >= 500) {
      console.error('[API] 服务器错误:', error.config?.url, error.response?.status)
      error.message = '服务器错误，请稍后重试'
    } else {
      console.error('[API] 请求失败:', error.config?.url, error.message)
    }
    return Promise.reject(error)
  }
)

/**
 * 获取热点微博
 * @param {number} limit - 返回数量
 * @param {string} datasetType - 数据集类型
 */
export function getHotWeibo(limit = 20, datasetType = null) {
  const params = { limit }
  if (datasetType) params.dataset_type = datasetType
  return http.get('/hot-weibo', { params })
}

/**
 * 获取关键词趋势
 * @param {string} keyword - 关键词
 * @param {number} days - 天数
 */
export function getKeywordTrend(keyword, days = 30) {
  return http.get('/keyword-trend', { params: { keyword, days } })
}

/**
 * 获取情感分析
 * @param {number} sampleSize - 采样数量
 */
export function getSentiment(sampleSize = 1000) {
  return http.get('/sentiment', { params: { sample_size: sampleSize } })
}

/**
 * 获取用户影响力排行
 * @param {string} type - followers / engagement
 * @param {number} limit - 返回数量
 */
export function getInfluencers(type = 'followers', limit = 10) {
  return http.get('/influencers', { params: { type, limit } })
}

/**
 * 获取日报
 */
export function getDailyReport() {
  return http.get('/daily-report')
}

export default http
