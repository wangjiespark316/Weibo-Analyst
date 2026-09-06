import axios from 'axios'

// API 基础地址（生产环境直接调用公网 API，开发环境走 Vite proxy）
const API_BASE = import.meta.env.DEV
  ? '/api'
  : 'https://weibo-analyst-api.onrender.com/api'

// 默认 API Key（AI 行业客户）
const DEFAULT_API_KEY = 'wk_test_ai_001'

const http = axios.create({
  baseURL: API_BASE,
  timeout: 60000,
  headers: {
    'Authorization': `Bearer ${DEFAULT_API_KEY}`,
  },
})

// 响应拦截器：处理错误
http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    console.error('API 请求失败:', error.message)
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
export function getSentiment(sampleSize = 2000) {
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
