'use strict';
/**
 * LAZARUS CORE – License Validation Server
 * POST /generate   – (admin) émet une clé
 * POST /activate   – lie une clé à une machine
 * POST /validate   – vérifie clé + machine
 * POST /deactivate – délie une machine
 * POST /webhook/stripe – émission automatique après paiement
 * GET  /health     – sonde de vie
 */
const express   = require('express');
const cors      = require('cors');
const helmet    = require('helmet');
const rateLimit = require('express-rate-limit');
const crypto    = require('crypto');
const { v4: uuidv4 } = require('uuid');
const Database  = require('better-sqlite3');
require('dotenv').config();

const DEFAULT_SECRET = 'lzr_server_secret_CHANGE_THIS';
const SECRET = process.env.LAZARUS_LICENSE_SECRET || DEFAULT_SECRET;
const PORT   = parseInt(process.env.PORT || '3001', 10);
const MAX_ACTIVATIONS = { 0: 1, 1: 3, 2: 5, 3: 10 };

if (process.env.NODE_ENV === 'production' && SECRET === DEFAULT_SECRET) {
  console.error('LAZARUS_LICENSE_SECRET doit être défini en production.');
  process.exit(1);
}

// ─── SQLite DB ────────────────────────────────────────────────────
const db = new Database(process.env.DB_PATH || './licenses.db');
db.exec(`
  CREATE TABLE IF NOT EXISTS licenses (
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
`);

// ─── Express setup ────────────────────────────────────────────────
const app = express();
app.use(helmet());
app.use(cors({ origin: process.env.ALLOWED_ORIGIN || false }));
const limiter = rateLimit({ windowMs: 15 * 60 * 1000, max: 60, standardHeaders: true, legacyHeaders: false });
app.use(limiter);

// Le webhook Stripe exige le corps BRUT pour vérifier la signature : il doit être déclaré AVANT express.json().
app.post('/webhook/stripe', express.raw({ type: 'application/json' }), (req, res) => {
  if (!process.env.STRIPE_SECRET_KEY || !process.env.STRIPE_WEBHOOK_SECRET) {
    return res.status(503).json({ error: 'Stripe non configuré' });
  }
  const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
  let event;
  try {
    event = stripe.webhooks.constructEvent(req.body, req.headers['stripe-signature'], process.env.STRIPE_WEBHOOK_SECRET);
  } catch (err) {
    return res.status(400).json({ error: err.message });
  }
  if (event.type === 'checkout.session.completed') {
    const session = event.data.object;
    const { planId, email: metaEmail } = session.metadata || {};
    const email = metaEmail || session.customer_email || 'unknown';
    const planMap = { pro: 1, proplus: 2, business: 3 };
    const plan = planMap[planId] || 1;
    const key = makeKey(plan, email, Date.now());
    try {
      db.prepare('INSERT OR IGNORE INTO licenses(key,email,plan,activations,created_at) VALUES(?,?,?,0,?)').run(key, email, plan, Date.now());
      console.log(`License created: ${key} for ${email} (plan ${plan})`);
    } catch (e) { console.error('DB error:', e.message); }
  }
  res.json({ received: true });
});

app.use(express.json({ limit: '10kb' }));

// ─── Helpers ──────────────────────────────────────────────────────
function signKey(plan, email, ts) {
  return crypto.createHmac('sha256', SECRET).update(`${plan}:${email}:${ts}`).digest('hex').slice(0, 24).toUpperCase();
}

function makeKey(plan, email, ts) {
  const sig = signKey(plan, email, ts);
  return `LZR${plan}-${sig.slice(0, 6)}-${sig.slice(6, 12)}-${sig.slice(12, 18)}-${sig.slice(18, 24)}`;
}

function getPlan(key) {
  if (!key || typeof key !== 'string' || !key.startsWith('LZR')) return -1;
  const p = parseInt(key.charAt(3), 10);
  return isNaN(p) ? -1 : p;
}

function safeEqual(a, b) {
  const x = Buffer.from(String(a || ''));
  const y = Buffer.from(String(b || ''));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}

// ─── Routes ───────────────────────────────────────────────────────
app.get('/health', (_req, res) => res.json({ status: 'ok', version: '1.0.0' }));

// Génère une clé (usage administrateur / webhook post-achat)
app.post('/generate', (req, res) => {
  const adminKey = process.env.ADMIN_KEY;
  // sans ADMIN_KEY configurée, l'endpoint est fermé (avant : undefined === undefined laissait tout passer)
  if (!adminKey || !safeEqual(req.headers['x-admin-key'], adminKey)) return res.status(403).json({ error: 'Forbidden' });
  const { email, plan } = req.body;
  if (!email || plan === undefined || ![0, 1, 2, 3].includes(Number(plan))) return res.status(400).json({ error: 'email and valid plan required' });
  const ts = Date.now();
  const key = makeKey(Number(plan), email, ts);
  try {
    db.prepare('INSERT INTO licenses(key,email,plan,activations,created_at) VALUES(?,?,?,0,?)').run(key, email, Number(plan), ts);
    res.json({ key, plan: Number(plan), email, ts });
  } catch (e) {
    res.status(409).json({ error: 'Key already exists' });
  }
});

// Valide + active une clé
app.post('/activate', (req, res) => {
  const { key, machine_hash } = req.body;
  if (!key || !machine_hash) return res.status(400).json({ error: 'key and machine_hash required' });
  const license = db.prepare('SELECT * FROM licenses WHERE key=?').get(key);
  if (!license) return res.status(404).json({ error: 'Invalid key' });
  if (license.plan !== getPlan(key)) return res.status(403).json({ error: 'Key corrupted' });
  const maxAct = MAX_ACTIVATIONS[license.plan] || 1;
  const existing = db.prepare('SELECT * FROM activations WHERE key=? AND machine_hash=?').get(key, machine_hash);
  if (existing) return res.json({ success: true, plan: license.plan, email: license.email, reactivated: true });
  if (license.activations >= maxAct) return res.status(403).json({ error: `Max activations (${maxAct}) reached` });
  const id = uuidv4();
  db.prepare('INSERT INTO activations(id,key,machine_hash,activated_at) VALUES(?,?,?,?)').run(id, key, machine_hash, Date.now());
  db.prepare('UPDATE licenses SET activations=activations+1 WHERE key=?').run(key);
  res.json({ success: true, plan: license.plan, email: license.email, activation_id: id });
});

// Valide sans réactiver
app.post('/validate', (req, res) => {
  const { key, machine_hash } = req.body;
  if (!key || !machine_hash) return res.status(400).json({ valid: false });
  const lic = db.prepare('SELECT * FROM licenses WHERE key=?').get(key);
  if (!lic) return res.json({ valid: false, reason: 'unknown_key' });
  const act = db.prepare('SELECT * FROM activations WHERE key=? AND machine_hash=?').get(key, machine_hash);
  if (!act) return res.json({ valid: false, reason: 'not_activated_on_this_machine' });
  res.json({ valid: true, plan: lic.plan, email: lic.email });
});

// Désactive une machine
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

if (require.main === module) {
  app.listen(PORT, () => console.log(`Lazarus License Server on port ${PORT}`));
}

module.exports = { app, makeKey, getPlan };
