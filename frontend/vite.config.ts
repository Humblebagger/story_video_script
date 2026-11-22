import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 开发期把 /api 代理到本地转换服务，避免跨源；生产用 VITE_API_BASE 直连
export default defineConfig(({ isSsrBuild }) => ({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    manifest: !isSsrBuild,     // 构建清单：dist/.vite/manifest.json，给首屏产物守卫（tests/vendor-bundle.check.mjs）解析静态与按需依赖
    // 文件名只含哈希：按需块不带组件名，不在文件名里暴露「后台」（设计 §9.3）；测试用的 SSR 构建不动
    rollupOptions: isSsrBuild ? {} : {
      output: {
        entryFileNames: 'assets/[hash].js',
        chunkFileNames: 'assets/[hash].js',
        assetFileNames: 'assets/[hash][extname]',
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
}))
