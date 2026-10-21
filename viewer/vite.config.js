import { defineConfig } from 'vite';

// `npm run dev` proxies the websocket to the Python service (python -m service.server, port 8080).
export default defineConfig({
  server: { proxy: { '/ws': { target: 'ws://127.0.0.1:8080', ws: true }, '/api': 'http://127.0.0.1:8080' } },
  build: { outDir: 'dist', chunkSizeWarningLimit: 900 },
  test: { include: ['tests/**/*.test.js'], environment: 'node' },
});
