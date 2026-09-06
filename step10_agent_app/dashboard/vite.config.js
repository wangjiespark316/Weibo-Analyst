import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    // Element Plus 按需自动导入
    AutoImport({
      resolvers: [ElementPlusResolver()],
      imports: ['vue'],
    }),
    Components({
      resolvers: [ElementPlusResolver()],
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'https://weibo-analyst-api.onrender.com',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        // 代码分割：核心库单独打包，Element Plus 由自动导入按需 tree-shake
        manualChunks: {
          'vue-vendor': ['vue'],
          'echarts-vendor': ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers'],
        },
      },
    },
    // 生产环境压缩（默认 esbuild，无需额外依赖）
    minify: 'esbuild',
  },
})
