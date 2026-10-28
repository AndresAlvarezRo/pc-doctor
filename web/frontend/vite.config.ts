import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Solo para desarrollo: `npm run dev` sirve la interfaz en 5173 y reenvía /api al servidor de pc-doctor.
// En producción no corre Node: FastAPI sirve los archivos compilados de dist/.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      // changeOrigin cambia el encabezado Host al del servidor: la API solo acepta 127.0.0.1:8787 o localhost:8787
      '/api': { target: 'http://127.0.0.1:8787', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 900 },
})
