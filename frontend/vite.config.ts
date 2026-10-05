import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dev server proxies /api to FastAPI, so the browser sees one origin and no CORS setup is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
})
