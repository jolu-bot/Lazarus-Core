'use strict';
const axios        = require('axios');
const crypto       = require('crypto');
const { machineId } = require('node-machine-id');

// ─── FREE LOCAL MODE ─────────────────────────────────────────────
// true  = toutes fonctions débloquées, aucun serveur requis
// false = mode commercial (Stripe + serveur de licences)
const FREE_LOCAL_MODE = true;

const PLAN_FEATURES = {
  0: { scan:true, recover:false, aiRepair:false, videoRecovery:false, forensic:false },
  1: { scan:true, recover:true,  aiRepair:false, videoRecovery:true,  forensic:false },
  2: { scan:true, recover:true,  aiRepair:true,  videoRecovery:true,  forensic:false },
  3: { scan:true, recover:true,  aiRepair:true,  videoRecovery:true,  forensic:true  },
};

const FREE_LOCAL_LICENSE = {
  valid: true, plan: 3, email: 'local@lazaruscore.app',
  features: PLAN_FEATURES[3],
  tier: 'Business — Local Edition',
  freeMode: true,
};

const HMAC_SECRET = process.env.LAZARUS_LICENSE_SECRET || 'lzr_hmac_v1_change_in_prod';

function setupLicenseIPC(ipcMain, store) {
  ipcMain.handle('license:get', async () => {
    if (FREE_LOCAL_MODE) return FREE_LOCAL_LICENSE;
    const mid = await machineId();
    const midHash = crypto.createHash('sha256').update(mid).digest('hex').substring(0,16);
    const stored = store.get('license');
    if (!stored) return { valid:false, plan:0, features:PLAN_FEATURES[0], machineHash:midHash };
    return { valid:true, plan:stored.plan, email:stored.email, key:stored.key,
             features:PLAN_FEATURES[stored.plan] ?? PLAN_FEATURES[0], machineHash:midHash };
  });

  ipcMain.handle('license:validate', async (_, key) => {
    if (FREE_LOCAL_MODE) return { ...FREE_LOCAL_LICENSE };
    const mid = await machineId();
    const midHash = crypto.createHash('sha256').update(mid).digest('hex').substring(0,16);
    const stored = store.get('license');
    if (!stored || stored.key !== key) return { valid:false, plan:0 };
    if (stored.machineHash && stored.machineHash !== midHash) return { valid:false, plan:0, reason:'machine_mismatch' };
    return { valid:true, plan:stored.plan, features:PLAN_FEATURES[stored.plan] };
  });

  ipcMain.handle('license:activate', async (_, { key, email }) => {
    if (FREE_LOCAL_MODE) return { success:true, ...FREE_LOCAL_LICENSE };
    const SERVER = process.env.LAZARUS_LICENSE_SERVER || null;
    const mid = await machineId();
    const midHash = crypto.createHash('sha256').update(mid).digest('hex').substring(0,16);
    if (SERVER) {
      try {
        const resp = await axios.post(SERVER + '/activate', { key, machine_hash:midHash, email }, { timeout:8000 });
        if (resp.data.success) {
          store.set('license', { key, email, plan:resp.data.plan, machineHash:midHash, activatedAt:Date.now() });
          return { success:true, plan:resp.data.plan, features:PLAN_FEATURES[resp.data.plan] };
        }
        return { success:false, message: resp.data.error || 'Server rejected key' };
      } catch (e) { console.warn('License server unreachable:', e.message); }
    }
    if (!key || !key.startsWith('LZR')) return { success:false, message:'Invalid key format' };
    const plan = parseInt(key.charAt(3), 10);
    if (isNaN(plan) || plan < 0 || plan > 3) return { success:false, message:'Invalid plan in key' };
    store.set('license', { key, email, plan, machineHash:midHash, activatedAt:Date.now() });
    return { success:true, plan, features:PLAN_FEATURES[plan] };
  });
}

module.exports = { setupLicenseIPC, PLAN_FEATURES, FREE_LOCAL_MODE };
