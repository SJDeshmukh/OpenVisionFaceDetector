import { spawn, execSync } from "node:child_process";
import net from "node:net";
import process from "node:process";
import readline from "node:readline";
import { setTimeout as delay } from "node:timers/promises";
import fs from "node:fs";
import path from "node:path";

const defaultPort = Number.parseInt(process.env.FRONTEND_PORT ?? "5173", 10);
const host = process.env.FRONTEND_HOST ?? "0.0.0.0";
const backendPort = Number.parseInt(process.env.BACKEND_PORT ?? "5001", 10);
const backendHost = process.env.BACKEND_HOST ?? "0.0.0.0";

async function cleanupPorts() {
  const ports = [6379, backendPort, defaultPort];
  process.stdout.write(`Cleaning up ports: ${ports.join(", ")}...\n`);
  for (const port of ports) {
    try {
      // macOS/Linux approach to kill process on port
      const pidOutput = execSync(`lsof -t -i:${port}`).toString().trim();
      if (pidOutput) {
        const pids = pidOutput.split(/\s+/).filter(Boolean);
        process.stdout.write(`Killing processes ${pids.join(", ")} on port ${port}...\n`);
        for (const pid of pids) {
          try {
            execSync(`kill -9 ${pid}`);
          } catch (e) {
            // Might have already exited
          }
        }
      }
    } catch {
      // Port is already free or command failed
    }
  }
  // Short delay to ensure OS releases ports
  await delay(1000);
}

async function performAudit() {
  const pythonPath = process.platform === "win32" ? "../backend/.venv/Scripts/python.exe" : "../backend/.venv/bin/python3";
  const pipPath = process.platform === "win32" ? "../backend/.venv/Scripts/pip.exe" : "../backend/.venv/bin/pip";
  const pythonCmd = fs.existsSync(path.resolve(process.cwd(), pythonPath)) ? pythonPath : "python3";
  const pipCmd = fs.existsSync(path.resolve(process.cwd(), pipPath)) ? pipPath : "pip3";

  process.stdout.write("--- Step 1: Auditing Dependencies ---\n");
  try {
    execSync(`${pipCmd} install -r ../backend/requirements.txt`, { stdio: "inherit" });
    process.stdout.write("Dependencies up to date.\n");
  } catch (e) {
    process.stderr.write(`Warning: Dependency audit failed: ${e.message}\n`);
  }

  process.stdout.write("\n--- Step 2: Auditing AI Models ---\n");
  try {
    execSync(`${pythonCmd} ../backend/download_models.py`, { stdio: "inherit" });
    process.stdout.write("Model audit complete.\n");
  } catch (e) {
    process.stderr.write(`Warning: Model audit failed: ${e.message}\n`);
  }

  process.stdout.write("\n--- Step 3: AI Environment Health Check ---\n");
  try {
    const isLowRam = process.env.LOW_RAM_MODE === "1";
    if (isLowRam) {
      process.stdout.write("LOW_RAM_MODE=1 detected. Skipping heavy AI health check.\n\n");
    } else {
      const checkScript = "import torch; import tensorflow; print(f'Torch {torch.__version__} OK, TF {tensorflow.__version__} OK')";
      execSync(`${pythonCmd} -c "${checkScript}"`, { stdio: "inherit" });
      process.stdout.write("Health check passed.\n\n");
    }
  } catch (e) {
    process.stderr.write(`Warning: AI environment health check failed! ${e.message}\n`);
    process.stderr.write("Please ensure torch and tensorflow are correctly installed in the venv if you need AI features.\n");
  }
}

function spawnProc(command, args, { name, env, cwd, stdio } = {}) {
  const child = spawn(command, args, {
    stdio: stdio ?? ["inherit", "pipe", "pipe"],
    env: env ?? process.env,
    cwd: cwd ?? process.cwd(),
  });

  child.on("error", (err) => {
    process.stderr.write(`${name} failed to start: ${err?.message ?? String(err)}\n`);
  });

  child.stdout?.on("data", (buf) => {
    process.stdout.write(buf);
  });
  child.stderr?.on("data", (buf) => {
    process.stderr.write(buf);
  });

  child.on("exit", (code, signal) => {
    if (signal) {
      process.stderr.write(`${name} exited (signal ${signal})\n`);
      return;
    }
    if (code !== 0) {
      process.stderr.write(`${name} exited (code ${code})\n`);
    }
  });

  return child;
}

async function fetchWithTimeout(url, { method = "GET", timeoutMs = 5000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { method, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function waitForHttpReady(url, timeoutMs = 25_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetchWithTimeout(url, { method: "GET", timeoutMs: 5000 });
      if (res.status >= 200 && res.status < 500) return;
    } catch { }
    await delay(350);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

// Remove ngrok/localtunnel helpers to reduce external dependencies

function isAddressInUse(err) {
  return err?.code === "EADDRINUSE";
}

async function isHttpListening(url) {
  try {
    const res = await fetchWithTimeout(url, { method: "GET", timeoutMs: 1200 });
    return res.status >= 200 && res.status < 500;
  } catch {
    return false;
  }
}

function canBindPort(port, host) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.listen(port, host, () => {
      server.close(() => resolve(true));
    });
  });
}

let selectedStorageProvider = null;

async function selectStorageProviderForDev() {
  if (selectedStorageProvider) return selectedStorageProvider;
  const envValue = (process.env.STORAGE_PROVIDER ?? process.env.OBJECT_STORAGE_PROVIDER ?? "").toLowerCase();
  if (envValue === "aws") {
    selectedStorageProvider = envValue;
    process.env.STORAGE_PROVIDER = selectedStorageProvider;
    return selectedStorageProvider;
  }
  selectedStorageProvider = "none";
  process.env.STORAGE_PROVIDER = selectedStorageProvider;
  return selectedStorageProvider;
}

async function findFrontendPort() {
  for (let offset = 0; offset < 20; offset += 1) {
    const port = defaultPort + offset;
    const url = `http://${host}:${port}/`;
    if (await isHttpListening(url)) return { port, alreadyRunning: true };
    if (await canBindPort(port, host)) return { port, alreadyRunning: false };
  }
  return { port: defaultPort, alreadyRunning: false };
}

// Removed ngrok API usage

async function isBackendReachable() {
  try {
    const res = await fetchWithTimeout(`http://${backendHost}:${backendPort}/api/config`, { method: "GET", timeoutMs: 3000 });
    return res.status === 200;
  } catch {
    return false;
  }
}

let backend = null;
let frontendTunnel = null;
let tmProc = null;
let vite = null;
let redisProc = null;
let celeryProcs = [];
let shuttingDown = false;

const REDIS_URL = "redis://127.0.0.1:6379/0";

async function startRedis() {
  process.stdout.write("Starting Redis server...\n");
  try {
    // Try to find redis-server in standard paths or the system PATH
    const redisPath = fs.existsSync("/opt/homebrew/opt/redis/bin/redis-server")
      ? "/opt/homebrew/opt/redis/bin/redis-server"
      : "redis-server";

    redisProc = spawnProc(redisPath, ["--daemonize", "no", "--port", "6379"], {
      name: "redis",
      stdio: "pipe",
    });
    // Give Redis a moment to start
    await delay(500);
    process.stdout.write("Redis started.\n");
  } catch (e) {
    process.stderr.write(`Failed to start Redis: ${String(e)}\n`);
    process.stderr.write("Falling back to thread-based processing (no Celery).\n");
  }
}

async function startCeleryWorker() {
  if (!redisProc) {
    process.stdout.write("Skipping Celery worker (Redis not available).\n");
    return;
  }
  process.stdout.write("Starting Celery workers (multi-tenant concurrency)...\n");
  try {
    const numWorkers = parseInt(process.env.CELERY_CONCURRENCY || "1", 10);
    const celeryPath = process.platform === "win32" ? "../backend/.venv/Scripts/celery.exe" : "../backend/.venv/bin/celery";
    const celeryCmd = fs.existsSync(path.resolve(process.cwd(), celeryPath)) ? celeryPath : "celery";

    for (let i = 1; i <= numWorkers; i++) {
      const proc = spawnProc(celeryCmd, [
        "-A", "celery_app",
        "worker",
        "--loglevel=info",
        "--concurrency=1",
        "--pool=solo",
        "-n", `worker${i}@%h`,
        "-Q", "celery,default",
        "--include", "tasks",
      ], {
        name: `celery${i}`,
        stdio: "pipe",
        cwd: process.cwd() + "/../backend",
        env: {
          ...process.env,
          CELERY_BROKER_URL: REDIS_URL,
          CELERY_RESULT_BACKEND: REDIS_URL,
          DB_PATH: "../backend/face_db.sqlite",
          KMP_DUPLICATE_LIB_OK: "TRUE",
          OMP_NUM_THREADS: "1",
          OPENCV_NUM_THREADS: "1",
          PRELOAD_AI_MODELS: "1",
        },
      });
      celeryProcs.push(proc);
    }
    // Give Celery a moment to connect
    await delay(2000);
    process.stdout.write(`Celery workers started (${numWorkers} concurrent workers).\n`);
  } catch (e) {
    process.stderr.write(`Failed to start Celery workers: ${String(e)}\n`);
  }
}

async function startBackendIfNeeded() {
  const shouldStart = (process.env.START_BACKEND ?? "1") !== "0";
  if (!shouldStart) return;
  await selectStorageProviderForDev();

  // Start Redis first
  await startRedis();

  process.stdout.write(`Starting backend (http://${backendHost}:${backendPort})...\n`);

  const pythonPath = process.platform === "win32" ? "../backend/.venv/Scripts/python.exe" : "../backend/.venv/bin/python3";
  const pythonCmd = fs.existsSync(path.resolve(process.cwd(), pythonPath)) ? pythonPath : "python3";

  backend = spawnProc(pythonCmd, ["../backend/app.py"], {
    name: "backend",
    stdio: "inherit",
    env: {
      ...process.env,
      DB_PATH: "../backend/face_db.sqlite",
      CELERY_BROKER_URL: redisProc ? REDIS_URL : "",
      CELERY_RESULT_BACKEND: redisProc ? REDIS_URL : "",
      REDIS_URL: redisProc ? REDIS_URL : "",
      KMP_DUPLICATE_LIB_OK: "TRUE",
      OMP_NUM_THREADS: "1",
      OPENCV_NUM_THREADS: "1",
      PRELOAD_AI_MODELS: "1",
    },
  });
  try {
    await waitForHttpReady(`http://${backendHost}:${backendPort}/api/config`, 60_000);
    process.stdout.write("Backend ready.\n");
  } catch (e) {
    process.stderr.write(`Backend did not become ready: ${String(e)}\n`);
  }

  // Start Celery worker after backend is ready
  await startCeleryWorker();
}

async function startFrontend() {
  await cleanupPorts();
  await performAudit();
  const backendPromise = startBackendIfNeeded();

  const { port } = await findFrontendPort();

  process.stdout.write(`Starting frontend (http://${host}:${port})...\n`);
  vite = spawnProc(
    "vite",
    ["--host", host, "--port", String(port), "--strictPort"],
    {
      name: "vite",
      stdio: "inherit",
    }
  );

  try {
    await waitForHttpReady(`http://${host}:${port}/`);
  } catch (e) {
    process.stderr.write(`${String(e)}\n`);
  }

  process.stdout.write(`\nLOCAL WEBSITE: http://${host}:${port}\n`);
  process.stdout.write(`LOCAL API: http://${backendHost}:${backendPort}/api\n\n`);

  const provider = "none";
  if (provider === "custom") {
    const url = process.env.TUNNEL_URL || "";
    if (!url) {
      process.stderr.write("TUNNEL_PROVIDER=custom but TUNNEL_URL is not set.\n");
    } else {
      process.stdout.write(`\nPUBLIC URL (share this): ${url}\n`);
      process.stdout.write(`WEBSITE: ${url}\n`);
      process.stdout.write(`API (proxied): ${url}/api\n`);
      process.stdout.write(`MOBILE SERVER URL: ${url}/\n\n`);
    }
  } else if (provider === "tm") {
    try {
      process.stdout.write("Starting Tunnelmole via npx...\n");
      // Use npx with -y to skip prompts, pass port only
      const args = ["-y", "tunnelmole", String(port)];
      // Allow extra args via TM_ARGS (space-separated)
      if (process.env.TM_ARGS) {
        args.push(...process.env.TM_ARGS.split(" ").filter(Boolean));
      }
      tmProc = spawnProc("npx", args, { name: "tunnelmole", stdio: "pipe" });
      let announced = false;
      const onData = (buf) => {
        const text = buf.toString("utf8");
        process.stdout.write(text);
        // Find first URL in output
        const urlMatch = text.match(/https?:\/\/[^\s]+/g);
        if (!announced && urlMatch && urlMatch.length > 0) {
          const url = urlMatch.find(u => /^https?:\/\//.test(u));
          if (url) {
            announced = true;
            process.stdout.write(`\nPUBLIC URL (share this): ${url}\n`);
            process.stdout.write(`WEBSITE: ${url}\n`);
            process.stdout.write(`API (proxied): ${url}/api\n`);
            process.stdout.write(`MOBILE SERVER URL: ${url}/\n\n`);
          }
        }
      };
      tmProc.stdout?.on("data", onData);
      tmProc.stderr?.on("data", onData);
    } catch (e) {
      process.stderr.write(`Failed to start Tunnelmole: ${String(e?.message || e)}\n`);
      process.stderr.write("Try installing it globally: npm i -g tunnelmole\n");
    }
  } else if (provider === "ngrok") {
    try {
      process.stdout.write("Starting ngrok tunnel...\n");
      const ng = spawnProc("ngrok", ["http", String(port), "--log=stdout"], { name: "ngrok", stdio: "pipe" });
      let announced = false;
      const onData = (buf) => {
        const text = buf.toString("utf8");
        process.stdout.write(text);
        for (const line of text.split("\n")) {
          const url = findNgrokUrl(line);
          if (!announced && url) {
            announced = true;
            process.stdout.write(`\nPUBLIC URL (share this): ${url}\n`);
            process.stdout.write(`WEBSITE: ${url}\n`);
            process.stdout.write(`API (proxied): ${url}/api\n`);
            process.stdout.write(`MOBILE SERVER URL: ${url}/\n\n`);
            break;
          }
        }
      };
      ng.stdout?.on("data", onData);
      ng.stderr?.on("data", onData);
    } catch (e) {
      process.stderr.write(`Failed to start ngrok: ${String(e?.message || e)}\n`);
      process.stderr.write("Install from https://ngrok.com/download and set authtoken if required\n");
    }
  } else if (provider === "cf") {
    try {
      process.stdout.write("Starting Cloudflare Tunnel (cloudflared)...\n");
      const extra = (process.env.CF_ARGS || "").split(" ").filter(Boolean);
      const args = ["tunnel", "--no-autoupdate", "--url", `http://${host}:${port}`, ...extra];
      const cf = spawnProc("cloudflared", args, { name: "cloudflared", stdio: "pipe" });
      let announced = false;
      const onData = (buf) => {
        const text = buf.toString("utf8");
        process.stdout.write(text);
        const matches = text.match(/https?:\/\/[^\s]+/g);
        if (!announced && matches && matches.length) {
          const url = matches.find(u => u.includes("trycloudflare.com")) || matches[0];
          if (url) {
            announced = true;
            process.stdout.write(`\nPUBLIC URL (share this): ${url}\n`);
            process.stdout.write(`WEBSITE: ${url}\n`);
            process.stdout.write(`API (proxied): ${url}/api\n`);
            process.stdout.write(`MOBILE SERVER URL: ${url}/\n\n`);
          }
        }
      };
      cf.stdout?.on("data", onData);
      cf.stderr?.on("data", onData);
    } catch (e) {
      process.stderr.write(`Failed to start cloudflared: ${String(e?.message || e)}\n`);
      process.stderr.write("Install it first. macOS: brew install cloudflare/cloudflare/cloudflared\n");
      // Fallback to LocalTunnel for convenience
      try {
        const subdomain = process.env.LT_SUBDOMAIN || undefined;
        const hostOverride = process.env.LT_HOST || undefined;
        process.stdout.write("Falling back to LocalTunnel...\n");
        const lt = ltModule?.default ?? ltModule;
        const tunnel = await lt({
          port,
          subdomain,
          host: hostOverride,
        });
        frontendTunnel = tunnel;
        const url = tunnel.url;
        process.stdout.write(`\nPUBLIC URL (share this): ${url}\n`);
        process.stdout.write(`WEBSITE: ${url}\n`);
        process.stdout.write(`API (proxied): ${url}/api\n`);
        process.stdout.write(`MOBILE SERVER URL: ${url}/\n\n`);
        tunnel.on("close", () => {
          process.stdout.write("LocalTunnel closed.\n");
        });
      } catch (e2) {
        process.stderr.write(`LocalTunnel fallback failed: ${String(e2?.message || e2)}\n`);
      }
    }
  } else if (provider === "none") {
    process.stdout.write("Public tunnel disabled. Use LOCAL WEBSITE/LOCAL API above.\n");
  } else {
    try {
      const subdomain = process.env.LT_SUBDOMAIN || undefined;
      const hostOverride = process.env.LT_HOST || undefined;
      process.stdout.write("Starting LocalTunnel...\n");
      const lt = ltModule?.default ?? ltModule;
      const tunnel = await lt({
        port,
        subdomain,
        host: hostOverride,
      });
      frontendTunnel = tunnel;
      const url = tunnel.url;
      process.stdout.write(`\nPUBLIC URL (share this): ${url}\n`);
      process.stdout.write(`WEBSITE: ${url}\n`);
      process.stdout.write(`API (proxied): ${url}/api\n`);
      process.stdout.write(`MOBILE SERVER URL: ${url}/\n\n`);
      try {
        const ipRes = await fetch("https://api.ipify.org?format=text").catch(() => null);
        const ipText = (await ipRes?.text())?.trim();
        if (ipText) {
          process.stdout.write(`If loca.lt asks for a tunnel password, enter your PUBLIC IP: ${ipText}\n`);
          process.stdout.write(`(This page appears once per viewer IP every few days as abuse protection.)\n\n`);
        }
      } catch { }
      tunnel.on("close", () => {
        process.stdout.write("LocalTunnel closed.\n");
      });
    } catch (e) {
      process.stderr.write(`Failed to start LocalTunnel: ${String(e?.message || e)}\n`);
      process.stderr.write("Install it with: npm i -D localtunnel\n");
    }
  }

  await backendPromise;

  // Keep the process alive without triggering an unsettled top-level await warning
  setInterval(() => { }, 3600000);
}

await startFrontend();

function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  try {
    vite?.kill("SIGINT");
  } catch { }
  try {
    if (frontendTunnel?.close) frontendTunnel.close();
    tmProc?.kill("SIGINT");
  } catch { }
  try {
    for (const p of celeryProcs) {
      p?.kill("SIGINT");
    }
  } catch { }
  try {
    backend?.kill("SIGINT");
  } catch { }
  try {
    redisProc?.kill("SIGINT");
  } catch { }
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
