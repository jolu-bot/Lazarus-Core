'use strict';
/**
 * LAZARUS CORE – License Validation Server
 * POST /validate  – check key+machineId
 * POST /activate  – issue license record
 * POST /deactivate – unbind machine
 * GET  /health    – liveness probe
 */
const express   = require('express');
const cors      = require('cors');
const helmet    = require('helmet');
const rateLimit = require('express-rate-limit');
const crypto    = require('crypto');
const { v4: uuidv4 } = require('uuid');
const Database  = require('better-sqlite3');
require('dotenv').config();

const SECRET = process.env.LAZARUS_LICENSE_SECRET || 'lzr_server_secret_CHANGE_THIS';
const PORT   = parseInt(process.env.PORT || '3001', 10);
const MAX_ACTIVATIONS = { 0:1, 1:3, 2:5, 3:10 };


// ─── SQLite DB ────────────────────────────────────────────────────
const db = new Database(process.env.DB_PATH || './licenses.db');
db.exec(  CREATE TABLE IF NOT EXISTS licenses (
    key TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    plan INTEGER NOT NULL DEFAULT 0,
    activations INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    expires_at INTEGER
  );
  CREATE TABLE IF NOT EXISTS activations (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    machine_hash TEXT NOT NULL,
    activated_at INTEGER NOT NULL,
    FOREIGN KEY(key) REFERENCES licenses(key)
  );
\);

// ─── Express setup ────────────────────────────────────────────────
const app = express();
app.use(helmet());
app.use(cors({ origin: process.env.ALLOWED_ORIGIN || false }));
app.use(express.json({ limit: '10kb' }));
const limiter = rateLimit({ windowMs: 15*60*1000, max: 60, standardHeaders: true, legacyHeaders: false });
app.use(limiter);

// ─── Helpers ──────────────────────────────────────────────────────
function signKey(plan, email, ts) {
  return crypto.createHmac('sha256', SECRET).update(\:\:\).digest('hex').slice(0,24).toUpperCase();
}

function getPlan(key) {
  if (!key || !key.startsWith('LZR')) return -1;
  const p = parseInt(key.charAt(3), 10);
  return isNaN(p) ? -1 : p;
}

// ─── Routes ───────────────────────────────────────────────────────
app.get('/health', (_req, res) => res.json({ status: 'ok', version: '1.0.0' }));

// Generate a license key (admin use / post-purchase webhook)
app.post('/generate', (req, res) => {
  const adminKey = req.headers['x-admin-key'];
  if (adminKey !== process.env.ADMIN_KEY) return res.status(403).json({ error: 'Forbidden' });
  const { email, plan } = req.body;
  if (!email || plan === undefined) return res.status(400).json({ error: 'email and plan required' });
  const ts = Date.now();
  const sig = signKey(plan, email, ts);
  const key = \LZR\-\-\-\-\;
  try {
    db.prepare('INSERT INTO licenses(key,email,plan,activations,created_at) VALUES(?,?,?,0,?)').run(key,email,plan,ts);
    res.json({ key, plan, email, ts });
  } catch (e) {
    res.status(409).json({ error: 'Key already exists' });
  }
});

// Validate + activate a license key
app.post('/activate', (req, res) => {
  const { key, machine_hash, email } = req.body;
  if (!key || !machine_hash) return res.status(400).json({ error: 'key and machine_hash required' });
  const license = db.prepare('SELECT * FROM licenses WHERE key=?').get(key);
  if (!license) return res.status(404).json({ error: 'Invalid key' });
  if (license.plan !== getPlan(key)) return res.status(403).json({ error: 'Key corrupted' });
  // Check max activations
  const maxAct = MAX_ACTIVATIONS[license.plan] || 1;
  const existing = db.prepare('SELECT * FROM activations WHERE key=? AND machine_hash=?').get(key, machine_hash);
  if (existing) return res.json({ success: true, plan: license.plan, email: license.email, reactivated: true });
  if (license.activations >= maxAct) return res.status(403).json({ error: \Max activations (\) reached\ });
  const id = uuidv4();
  db.prepare('INSERT INTO activations(id,key,machine_hash,activated_at) VALUES(?,?,?,?)').run(id,key,machine_hash,Date.now());
  db.prepare('UPDATE licenses SET activations=activations+1 WHERE key=?').run(key);
  res.json({ success: true, plan: license.plan, email: license.email, activation_id: id });
});

// Validate without re-activating
app.post('/validate', (req, res) => {
  const { key, machine_hash } = req.body;
  if (!key || !machine_hash) return res.status(400).json({ valid: false });
  const lic = db.prepare('SELECT * FROM licenses WHERE key=?').get(key);
  if (!lic) return res.json({ valid: false, reason: 'unknown_key' });
  const act = db.prepare('SELECT * FROM activations WHERE key=? AND machine_hash=?').get(key, machine_hash);
  if (!act) return res.json({ valid: false, reason: 'not_activated_on_this_machine' });
  res.json({ valid: true, plan: lic.plan, email: lic.email });
});

// Deactivate a machine
app.post('/deactivate', (req, res) => {
  const { key, machine_hash } = req.body;
  if (!key || !machine_hash) return res.status(400).json({ error: 'key and machine_hash required' });
  const r = db.prepare('DELETE FROM activations WHERE key=? AND machine_hash=?').run(key, machine_hash);
  if (r.changes > 0) {
    db.prepare('UPDATE licenses SET activations=MAX(0,activations-1) WHERE key=?').run(key);
    res.json({ success: true });
  } else {
    res.status(404).json({ error: 'Activation not found' });
  }
});

// Stripe webhook: generate license after successful payment
app.post('/webhook/stripe', express.raw({ type: 'application/json' }), (req, res) => {
  const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY || '');
  const sig = req.headers['stripe-signature'];
  let event;
  try {
    event = stripe.webhooks.constructEvent(req.body, sig, process.env.STRIPE_WEBHOOK_SECRET || '');
  } catch (err) {
    return res.status(400).json({ error: err.message });
  }
  if (event.type === 'checkout.session.completed') {
    const session = event.data.object;
    const { planId, email: metaEmail } = session.metadata || {};
    const email = metaEmail || session.customer_email || 'unknown';
    const planMap = { pro: 1, proplus: 2, business: 3 };
    const plan = planMap[planId] || 1;
    const ts = Date.now();
    const sig2 = signKey(plan, email, ts);
    const key = \LZR\-\-\-\-\;
    try {
      db.prepare('INSERT OR IGNORE INTO licenses(key,email,plan,activations,created_at) VALUES(?,?,?,0,?)').run(key,email,plan,ts);
      console.log(\License created: \ for \ (plan \)\);
    } catch(e) { console.error('DB error:', e.message); }
  }
  res.json({ received: true });
});

app.listen(PORT, () => console.log(\Lazarus License Server on port \));
