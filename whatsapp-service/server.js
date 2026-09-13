const express = require('express');
const qrcode = require('qrcode');
const pino = require('pino');
const fs = require('fs');
const path = require('path');

const baileys = require('@whiskeysockets/baileys');
const makeWASocket = baileys.default || baileys;
const { useMultiFileAuthState, DisconnectReason } = baileys;

const app = express();
app.use(express.json());

const PORT = parseInt(process.env.SERVER_PORT || '8080', 10);
const API_KEY = process.env.AUTHENTICATION_API_KEY || 'tapinx_evolution_secret_key';
const SESSIONS_DIR = path.join(__dirname, 'sessions');

if (!fs.existsSync(SESSIONS_DIR)) {
  fs.mkdirSync(SESSIONS_DIR, { recursive: true });
}

// In-memory instance registry
const instances = {};

// Auth middleware
app.use((req, res, next) => {
  if (req.path === '/' || req.path === '/health') return next();
  const key = req.headers['apikey'] || req.query.apikey;
  if (API_KEY && key !== API_KEY) {
    return res.status(401).json({ error: 'Unauthorized: invalid apikey' });
  }
  next();
});

async function getOrCreateInstance(instanceName) {
  if (instances[instanceName]) {
    return instances[instanceName];
  }

  const sessionPath = path.join(SESSIONS_DIR, instanceName);
  if (!fs.existsSync(sessionPath)) {
    fs.mkdirSync(sessionPath, { recursive: true });
  }

  const inst = {
    name: instanceName,
    state: 'close',
    qrBase64: null,
    qrRaw: null,
    ownerJid: null,
    sock: null,
    sessionPath: sessionPath
  };
  instances[instanceName] = inst;

  await connectSocket(instanceName);
  return inst;
}

async function connectSocket(instanceName) {
  const inst = instances[instanceName];
  if (!inst) return;

  try {
    const { state, saveCreds } = await useMultiFileAuthState(inst.sessionPath);

    const sock = makeWASocket({
      auth: state,
      printQRInTerminal: false,
      logger: pino({ level: 'silent' }),
      browser: ['TapInX Gateway', 'Chrome', '120.0.0.0']
    });

    inst.sock = sock;
    inst.state = 'connecting';

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        inst.qrRaw = qr;
        try {
          inst.qrBase64 = await qrcode.toDataURL(qr);
        } catch (e) {
          console.error(`[${instanceName}] QR generation error:`, e);
        }
        inst.state = 'connecting';
        console.log(`[${instanceName}] Fresh pairing QR code generated`);
      }

      if (connection === 'open') {
        inst.state = 'open';
        inst.qrBase64 = null;
        inst.qrRaw = null;
        const jid = sock.user?.id || sock.user?.jid || '';
        inst.ownerJid = jid ? jid.split(':')[0] + '@s.whatsapp.net' : null;
        console.log(`[${instanceName}] Connected successfully! Owner JID: ${inst.ownerJid}`);
      }

      if (connection === 'close') {
        const statusCode = (lastDisconnect?.error)?.output?.statusCode;
        const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
        inst.state = 'close';
        inst.qrBase64 = null;
        inst.qrRaw = null;
        console.log(`[${instanceName}] Connection closed (statusCode: ${statusCode}). Reconnect: ${shouldReconnect}`);

        if (statusCode === DisconnectReason.loggedOut) {
          try {
            fs.rmSync(inst.sessionPath, { recursive: true, force: true });
          } catch (e) {}
          inst.ownerJid = null;
        } else if (shouldReconnect) {
          setTimeout(() => connectSocket(instanceName), 4000);
        }
      }
    });
  } catch (err) {
    console.error(`[${instanceName}] Error initializing Baileys socket:`, err);
    inst.state = 'close';
  }
}

// Routes matching Evolution API v2 contract

app.get('/', (req, res) => {
  res.json({ status: 200, message: 'Welcome to TapInX WhatsApp Gateway' });
});

app.get('/health', (req, res) => {
  res.json({ status: 'ok', instancesCount: Object.keys(instances).length });
});

// 1. Create or ensure instance exists
app.post('/instance/create', async (req, res) => {
  const instanceName = req.body.instanceName || req.body.name;
  if (!instanceName) {
    return res.status(400).json({ error: 'instanceName is required' });
  }
  const inst = await getOrCreateInstance(instanceName);
  res.json({
    instance: {
      instanceName: inst.name,
      status: 'created'
    }
  });
});

// 2. Connect / fetch QR code
app.get('/instance/connect/:instanceName', async (req, res) => {
  const { instanceName } = req.params;
  const inst = await getOrCreateInstance(instanceName);

  // If disconnected or socket dead, restart connection
  if (inst.state === 'close' || !inst.sock) {
    connectSocket(instanceName);
  }

  // If already open, return connected status
  if (inst.state === 'open') {
    return res.json({
      instance: { state: 'open' },
      base64: null,
      message: 'Already connected'
    });
  }

  // If QR is already available, return it immediately
  if (inst.qrBase64) {
    return res.json({
      base64: inst.qrBase64,
      code: inst.qrRaw,
      pairingCode: null
    });
  }

  // Otherwise wait up to 7 seconds for QR event
  let elapsed = 0;
  const interval = setInterval(() => {
    elapsed += 250;
    if (inst.qrBase64 || inst.state === 'open' || elapsed >= 7000) {
      clearInterval(interval);
      if (!res.headersSent) {
        return res.json({
          base64: inst.qrBase64,
          code: inst.qrRaw,
          pairingCode: null
        });
      }
    }
  }, 250);
});

// 3. Connection state
app.get('/instance/connectionState/:instanceName', async (req, res) => {
  const { instanceName } = req.params;
  const inst = instances[instanceName];
  res.json({
    instance: {
      state: inst ? inst.state : 'close'
    }
  });
});

// 4. Fetch instances (used by sync_connection_state to auto-detect owner phone number)
app.get('/instance/fetchInstances', async (req, res) => {
  const target = req.query.instanceName;
  const list = [];

  for (const name of Object.keys(instances)) {
    if (!target || name === target) {
      const inst = instances[name];
      list.push({
        name: inst.name,
        connectionStatus: inst.state,
        ownerJid: inst.ownerJid
      });
    }
  }

  res.json(list);
});

// 5. Send Text Message
app.post('/message/sendText/:instanceName', async (req, res) => {
  const { instanceName } = req.params;
  const { number, text } = req.body;

  if (!number || !text) {
    return res.status(400).json({ error: 'number and text are required' });
  }

  const inst = instances[instanceName];
  if (!inst || inst.state !== 'open' || !inst.sock) {
    return res.status(400).json({ error: 'Instance is not connected' });
  }

  const cleanNum = String(number).replace(/\D/g, '');
  const jid = `${cleanNum}@s.whatsapp.net`;

  try {
    const result = await inst.sock.sendMessage(jid, { text });
    console.log(`[${instanceName}] Sent WhatsApp text to ${cleanNum}`);
    res.json({
      status: 'SUCCESS',
      messageId: result?.key?.id || null
    });
  } catch (err) {
    console.error(`[${instanceName}] Failed to send WhatsApp message:`, err);
    res.status(500).json({ error: err.message });
  }
});

// 6. Logout / Disconnect
app.delete('/instance/logout/:instanceName', async (req, res) => {
  const { instanceName } = req.params;
  const inst = instances[instanceName];

  if (inst) {
    try {
      if (inst.sock) {
        await inst.sock.logout();
      }
    } catch (e) {}
    try {
      fs.rmSync(inst.sessionPath, { recursive: true, force: true });
    } catch (e) {}
    delete instances[instanceName];
  }

  res.json({ status: 'SUCCESS' });
});

// Auto-restore any existing sessions on boot
fs.readdir(SESSIONS_DIR, (err, files) => {
  if (!err && files) {
    for (const file of files) {
      const p = path.join(SESSIONS_DIR, file);
      if (fs.statSync(p).isDirectory()) {
        console.log(`[Startup] Restoring session for instance: ${file}`);
        getOrCreateInstance(file);
      }
    }
  }
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`=============================================`);
  console.log(`  TapInX WhatsApp Baileys Gateway Running   `);
  console.log(`  Port: ${PORT}                             `);
  console.log(`  No Docker, No DB, Native Node.js & PM2    `);
  console.log(`=============================================`);
});
