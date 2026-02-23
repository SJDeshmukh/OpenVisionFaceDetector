import { spawn } from "node:child_process";
import net from "node:net";
import process from "node:process";
import readline from "node:readline";
import { setTimeout as delay } from "node:timers/promises";

const defaultPort = Number.parseInt(process.env.FRONTEND_PORT ?? "5173", 10);
const host = process.env.FRONTEND_HOST ?? "127.0.0.1";
const backendPort = Number.parseInt(process.env.BACKEND_PORT ?? "5001", 10);
const backendHost = process.env.BACKEND_HOST ?? "127.0.0.1";

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
    } catch {}
    await delay(350);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

function findNgrokUrl(line) {
  const match = line.match(/url=(https:\/\/[^\s]+)/);
  return match?.[1] ?? null;
}

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

async function findRunningNgrokApiPort() {
  for (let p = 4040; p <= 4050; p += 1) {
    if (await isHttpListening(`http://127.0.0.1:${p}/api/tunnels`)) return p;
  }
  return null;
}

async function getExistingNgrokPublicUrlForPort(frontendPort) {
  const apiPort = await findRunningNgrokApiPort();
  if (!apiPort) return null;
  try {
    const res = await fetchWithTimeout(`http://127.0.0.1:${apiPort}/api/tunnels`, { timeoutMs: 1500 });
    if (!res.ok) return null;
    const data = await res.json();
    const tunnels = Array.isArray(data?.tunnels) ? data.tunnels : [];
    for (const tunnel of tunnels) {
      const publicUrl = tunnel?.public_url;
      const addr = tunnel?.config?.addr ?? "";
      if (typeof publicUrl !== "string") continue;
      if (typeof addr === "string" && addr.includes(`:${frontendPort}`)) return publicUrl;
    }
  } catch {}
  return null;
}

async function isBackendReachable() {
  try {
    const res = await fetchWithTimeout(`http://${backendHost}:${backendPort}/api/config`, { method: "GET", timeoutMs: 3000 });
    return res.status === 200;
  } catch {
    return false;
  }
}

let backend = null;
let frontendNgrok = null;
let vite = null;
let shuttingDown = false;

async function startBackendIfNeeded() {
  const shouldStart = (process.env.START_BACKEND ?? "1") !== "0";
  if (!shouldStart) return;
  await selectStorageProviderForDev();
  process.stdout.write(`Starting backend (http://${backendHost}:${backendPort})...\n`);
  if (await isBackendReachable()) {
    process.stdout.write("Backend already running.\n");
    return;
  }

  backend = spawnProc("python3", ["../backend/app.py"], {
    name: "backend",
    stdio: "inherit",
    env: {
      ...process.env,
      DB_PATH: "../backend/face_db.sqlite",
    },
  });
  try {
    await waitForHttpReady(`http://${backendHost}:${backendPort}/api/config`, 60_000);
    process.stdout.write("Backend ready.\n");
  } catch (e) {
    process.stderr.write(`Backend did not become ready: ${String(e)}\n`);
  }
}

async function startFrontend() {
  const backendPromise = startBackendIfNeeded();

  const { port, alreadyRunning } = await findFrontendPort();

  if (!alreadyRunning) {
    process.stdout.write(`Starting frontend (http://${host}:${port})...\n`);
    vite = spawnProc(
      "vite",
      ["--host", host, "--port", String(port), "--strictPort"],
      {
        name: "vite",
        stdio: "inherit",
      }
    );
  } else {
    process.stdout.write(`Frontend already running (http://${host}:${port})...\n`);
  }

  try {
    await waitForHttpReady(`http://${host}:${port}/`);
  } catch (e) {
    process.stderr.write(`${String(e)}\n`);
  }

  try {
    const existing = await getExistingNgrokPublicUrlForPort(port);
    if (existing) {
      process.stdout.write(`\nPUBLIC URL (share this): ${existing}\n`);
      process.stdout.write(`WEBSITE: ${existing}\n`);
      process.stdout.write(`API (proxied): ${existing}/api\n`);
      process.stdout.write(`MOBILE SERVER URL: ${existing}/\n\n`);
      await backendPromise;
      await new Promise(() => {});
      return;
    }

    process.stdout.write("Starting ngrok tunnel...\n");
    const child = spawn("ngrok", ["http", String(port), "--log=stdout"], {
      stdio: ["inherit", "pipe", "pipe"],
      env: process.env,
    });
    frontendNgrok = child;
    child.stdout.on("data", (buf) => {
      const text = buf.toString("utf8");
      process.stdout.write(text);
      for (const line of text.split("\n")) {
        const url = findNgrokUrl(line);
        if (url) {
          process.stdout.write(`\nPUBLIC URL (share this): ${url}\n`);
          process.stdout.write(`WEBSITE: ${url}\n`);
          process.stdout.write(`API (proxied): ${url}/api\n`);
          process.stdout.write(`MOBILE SERVER URL: ${url}/\n\n`);
          break;
        }
      }
    });
    child.stderr.on("data", (buf) => {
      process.stderr.write(buf);
    });
  } catch {
    process.stderr.write("ngrok is not installed or not on PATH.\n");
    return;
  }

  await backendPromise;
  await new Promise(() => {});
}

await startFrontend();

function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  try {
    vite?.kill("SIGINT");
  } catch {}
  try {
    frontendNgrok?.kill("SIGINT");
  } catch {}
  try {
    backend?.kill("SIGINT");
  } catch {}
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
