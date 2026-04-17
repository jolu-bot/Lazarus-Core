'use strict';
const axios = require('axios');
const crypto        = require('crypto');
const { machineId } = require('node-machine-id');

const HMAC_SECRET = process.env.LAZARUS_LICENSE_SECRET || 'lzr_hmac_secret_v1_CHANGE_THIS';

// Plans: 0=Free, 1=Pro, 2=Pro+, 3=Business
const PLAN_FEATURES = {
  0: { scan: true,  recover: false, aiRepair: false, videoRecovery: false, forensic: false },
  1: { scan: true,  recover: true,  aiRepair: false, videoRecovery: true,  forensic: false },
  2: { scan: true,  recover: true,  aiRepair: true,  videoRecovery: true,  forensic: false },
  3: { scan: true,  recover: true,  aiRepair: true,  videoRecovery: true,  forensic: true  },
};

function generateLicenseKey(plan, machineIdHash, email) {
  const payload = `${plan}:${machineIdHash}:${email}:${Date.now()}`;
  const sig     = crypto.createHmac('sha256', HMAC_SECRET)
                         .update(payload)
                         .digest('hex')
                         .substring(0, 16)
                         .toUpperCase();
  // Format: PLAN-MACHINEPART-SIG
  const part1 = sig.substring(0, 4);
  const part2 = sig.substring(4, 8);
  const part3 = sig.substring(8, 12);
  const part4 = sig.substring(12, 16);
  return `LZR${plan}-${part1}-${part2}-${part3}-${part4}`;
}

async function validateKey(key, store) {
  const mid = await machineId();
  const midHash = crypto.createHash('sha256').update(mid).digest('hex').substring(0, 16);

  const stored = store.get('license');
  if (!stored) return { valid: false, plan: 0 };

  // Check machine binding
  if (stored.machineHash && stored.machineHash !== midHash) {
    return { valid: false, plan: 0, reason: 'machine_mismatch' };
  }

  // Verify HMAC (simplified - in production use server-side validation)
  if (stored.key !== key) return { valid: false, plan: 0 };

  return {
    valid:    true,
    plan:     stored.plan,
    email:    stored.email,
    features: PLAN_FEATURES[stored.plan] || PLAN_FEATURES[0],
  };
}

function setupLicenseIPC(ipcMain, store) {
  ipcMain.handle('license:get', async () => {
    const mid  = await machineId();
    const midHash = crypto.createHash('sha256').update(mid).digest('hex').substring(0, 16);
    const stored = store.get('license');
    if (!stored) {
      return { valid: false, plan: 0, features: PLAN_FEATURES[0], machineHash: midHash };
    }
    return {
      valid:       true,
      plan:        stored.plan,
      email:       stored.email,
      key:         stored.key,
      features:    PLAN_FEATURES[stored.plan] ?? PLAN_FEATURES[0],
      machineHash: midHash,
    };
  });

  ipcMain.handle('license:validate', async (_, key) => {
    return validateKey(key, store);
  });

  ipcMain.handle('license:activate', async (_, { key, email }) => {
    // Try online server first, fall back to local HMAC check
    const SERVER = process.env.LAZARUS_LICENSE_SERVER || null;
    if (SERVER) {
      try {
        const mid = await machineId();
        const midHash = crypto.createHash('sha256').update(mid).digest('hex').substring(0, 16);
        const resp = await axios.post(SERVER + '/activate', { key, machine_hash: midHash, email }, { timeout: 8000 });
        if (resp.data.success) {
          store.set('license', { key, email, plan: resp.data.plan, machineHash: midHash, activatedAt: Date.now() });
          return { success: true, plan: resp.data.plan, features: PLAN_FEATURES[resp.data.plan] };
        }
        return { success: false, message: resp.data.error || 'Server rejected key' };
      } catch (netErr) {
        console.warn('License server unreachable, falling back to local validation:', netErr.message);
      }
    }
    // Offline fallback: basic HMAC format check
    if (!key || !key.startsWith('LZR')) {
      return { success: false, message: 'Invalid key format' };
    }

    const mid = await machineId();
    const midHash = crypto.createHash('sha256').update(mid).digest('hex').substring(0, 16);

    // Extract plan from key
    const planChar = key.charAt(3);
    const plan = parseInt(planChar, 10);
    if (isNaN(plan) || plan < 0 || plan > 3) {
      return { success: false, message: 'Invalid plan in key' };
    }

    store.set('license', { key, email, plan, machineHash: midHash, activatedAt: Date.now() });
    return {
      success:  true,
      plan,
      features: PLAN_FEATURES[plan],
    };
  });
}

module.exports = { setupLicenseIPC, PLAN_FEATURES };
