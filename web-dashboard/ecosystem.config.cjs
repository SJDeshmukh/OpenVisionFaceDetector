module.exports = {
  apps: [
    {
      name: "face-web-dev",
      cwd: __dirname,
      script: "npm",
      args: "run dev",
      env: {
        NODE_ENV: "development",
        FRONTEND_PORT: process.env.FRONTEND_PORT || "5173",
        FRONTEND_HOST: process.env.FRONTEND_HOST || "127.0.0.1",
        BACKEND_PORT: process.env.BACKEND_PORT || "5001",
        BACKEND_HOST: process.env.BACKEND_HOST || "127.0.0.1",
        START_BACKEND: process.env.START_BACKEND || "1",
        TUNNEL_PROVIDER: process.env.TUNNEL_PROVIDER || "ngrok"
      },
      autorestart: true,
      max_restarts: 10,
      watch: false,
      time: true
    },
    {
      name: "face-backend",
      cwd: "../backend",
      script: "app.py",
      interpreter: "python3",
      env: {
        NODE_ENV: "development",
        BACKEND_URL: process.env.BACKEND_URL || "http://127.0.0.1:5001",
        DB_PATH: process.env.DB_PATH || "face_db.sqlite"
      },
      autorestart: true,
      max_restarts: 10,
      watch: false,
      time: true
    },
    {
      name: "face-web-preview",
      cwd: __dirname,
      script: "npm",
      args: "run preview",
      env: {
        NODE_ENV: "production",
        VITE_API_URL: process.env.VITE_API_URL || "",
        PORT: process.env.FRONTEND_PORT || "5173",
        HOST: process.env.FRONTEND_HOST || "0.0.0.0"
      },
      autorestart: true,
      max_restarts: 10,
      watch: false,
      time: true
    }
  ]
};
