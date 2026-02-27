import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { Buffer } from 'node:buffer'

// https://vite.dev/config/
const basicAuthPlugin = () => ({
  name: 'basic-auth',
  configureServer(server) {
    const user = process.env.DEV_BASIC_USER
    const pass = process.env.DEV_BASIC_PASS
    if (!user || !pass) return
    const expected = 'Basic ' + Buffer.from(`${user}:${pass}`).toString('base64')
    server.middlewares.use((req, res, next) => {
      const auth = req.headers['authorization']
      if (auth === expected) return next()
      res.statusCode = 401
      res.setHeader('WWW-Authenticate', 'Basic realm="dev"')
      res.end('Authentication required')
    })
  }
})

export default defineConfig({
  plugins: [react(), basicAuthPlugin()],
  server: {
    allowedHosts: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:5001",
        changeOrigin: true,
        secure: false,
      },
      "/socket.io": {
        target: "http://127.0.0.1:5001",
        ws: true,
        changeOrigin: true,
        secure: false,
      },
    },
  },
})
