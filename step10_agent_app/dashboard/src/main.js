import { createApp } from 'vue'
import App from './App.vue'
import './assets/global.css'

// Element Plus 组件由 unplugin-vue-components 按需自动导入
// locale 通过 App.vue 中的 ElConfigProvider 配置
const app = createApp(App)
app.mount('#app')
