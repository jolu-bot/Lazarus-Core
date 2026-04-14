import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Key, CheckCircle2, AlertCircle, Shield, Zap, Cpu, Building2 } from 'lucide-react';
import { useAppStore } from '../../stores/useAppStore';
import clsx from 'clsx';

const lzr = window.lazarus;

const PLANS = [
  {
    id:       'free',
    name:     'Free',
    price:    '$0',
    color:    'border-surface-border',
    textColor:'text-text-muted',
    icon:     Shield,
    features: ['Scan any drive', 'Find deleted files', 'View file list', 'File preview'],
    locked:   ['File recovery', 'AI Repair', 'Video recovery', 'Forensic tools'],
  },
  {
    id:       'pro',
    name:     'Pro',
    price:    '$49',
    period:   'one-time',
    color:    'border-primary/50',
    textColor:'text-primary',
    icon:     Zap,
    highlight: true,
    features: ['Everything in Free', 'Full file recovery', 'NTFS / EXT4 / APFS', 'Video recovery', 'Priority support'],
    locked:   ['AI Repair', 'Forensic tools'],
  },
  {
    id:       'proplus',
    name:     'Pro+',
    price:    '$79',
    period:   'one-time',
    color:    'border-purple-500/50',
    textColor:'text-purple-400',
    icon:     Cpu,
    features: ['Everything in Pro', 'AI image repair', 'AI-assisted reconstruction', 'Deep carving scan'],
    locked:   ['Forensic tools'],
  },
  {
    id:       'business',
    name:     'Business',
    price:    '$199',
    period:   'one-time',
    color:    'border-accent-green/50',
    textColor:'text-accent-green',
    icon:     Building2,
    features: ['Everything in Pro+', 'Forensic tools', '3 machine licenses', 'Priority support', 'Invoice billing'],
    locked:   [],
  },
];

export default function LicenseView() {
  const { license, setLicense } = useAppStore();
  const [key,      setKey]      = useState('');
  const [email,    setEmail]    = useState('');
  const [status,   setStatus]   = useState(null); // null | 'ok' | 'error'
  const [loading,  setLoading]  = useState(false);
  const [msg,      setMsg]      = useState('');

  const activate = async () => {
    if (!key.trim()) return;
    setLoading(true); setStatus(null);
    const result = await lzr?.invoke('license:activate', { key: key.trim(), email: email.trim() });
    setLoading(false);
    if (result?.success) {
      setStatus('ok');
      setMsg('License activated! Plan: ' + ['Free','Pro','Pro+','Business'][result.plan]);
      setLicense({ valid: true, plan: result.plan, features: result.features });
    } else {
      setStatus('error');
      setMsg(result?.message || 'Invalid license key');
    }
  };

  const purchase = async (planId) => {
    if (!email.trim()) { alert('Enter your email first'); return; }
    await lzr?.invoke('payment:createSession', { planId, email: email.trim() });
  };

  const currentPlanName = ['Free','Pro','Pro+','Business'][license.plan] || 'Free';

  return (
    <div className="flex flex-col h-full overflow-y-auto p-8 bg-bg">
      <div className="max-w-5xl mx-auto w-full">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-text mb-1 flex items-center gap-3">
            <Key size={24} className="text-primary" />
            License & Plans
          </h1>
          <p className="text-text-muted text-sm">
            Current plan: <span className="text-primary font-semibold">{currentPlanName}</span>
            {license.email && <span className="text-text-dim ml-2">· {license.email}</span>}
          </p>
        </div>

        {/* Plans grid */}
        <div className="grid grid-cols-4 gap-4 mb-8">
          {PLANS.map((plan) => {
            const Icon = plan.icon;
            const isCurrent = currentPlanName === plan.name;
            return (
              <motion.div
                key={plan.id}
                whileHover={{ y: -2 }}
                className={clsx(
                  'relative rounded-2xl bg-surface-2 border p-5 flex flex-col gap-4',
                  plan.color,
                  plan.highlight && 'shadow-glow',
                  isCurrent && 'ring-1 ring-primary'
                )}
              >
                {plan.highlight && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-primary
                                  text-white text-xs font-bold px-3 py-0.5 rounded-full shadow-glow">
                    POPULAR
                  </div>
                )}
                {isCurrent && (
                  <div className="absolute -top-3 right-4 bg-accent-green
                                  text-bg text-xs font-bold px-3 py-0.5 rounded-full">
                    ACTIVE
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <Icon size={18} className={plan.textColor} />
                  <span className={clsx('font-bold text-lg', plan.textColor)}>{plan.name}</span>
                </div>
                <div>
                  <span className="text-2xl font-bold text-text">{plan.price}</span>
                  {plan.period && <span className="text-xs text-text-dim ml-1">{plan.period}</span>}
                </div>
                <ul className="flex-1 space-y-1.5">
                  {plan.features.map((f) => (
                    <li key={f} className="flex items-start gap-1.5 text-xs text-text-muted">
                      <CheckCircle2 size={12} className="text-accent-green mt-0.5 flex-shrink-0" />
                      {f}
                    </li>
                  ))}
                  {plan.locked?.map((f) => (
                    <li key={f} className="flex items-start gap-1.5 text-xs text-text-dim line-through">
                      <span className="w-3 flex-shrink-0" />
                      {f}
                    </li>
                  ))}
                </ul>
                {plan.id !== 'free' && !isCurrent && (
                  <button
                    onClick={() => purchase(plan.id)}
                    className={clsx(
                      'w-full py-2 rounded-xl text-sm font-semibold transition-all duration-200',
                      plan.highlight
                        ? 'bg-primary text-white hover:bg-primary-hover shadow-glow-sm'
                        : 'bg-surface-border text-text hover:bg-surface-2 border border-surface-border'
                    )}
                  >
                    Get {plan.name}
                  </button>
                )}
              </motion.div>
            );
          })}
        </div>

        {/* Activation */}
        <div className="bg-surface-2 border border-surface-border rounded-2xl p-6">
          <h2 className="text-sm font-semibold text-text mb-4 flex items-center gap-2">
            <Key size={16} className="text-primary" />
            Activate License Key
          </h2>
          <div className="flex flex-col gap-3 max-w-lg">
            <input
              type="email"
              placeholder="Email address"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="bg-bg border border-surface-border rounded-lg px-4 py-2.5
                         text-sm text-text placeholder-text-dim outline-none
                         focus:border-primary/50 transition-colors"
            />
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="LZR1-XXXX-XXXX-XXXX-XXXX"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                className="flex-1 bg-bg border border-surface-border rounded-lg px-4 py-2.5
                           text-sm text-text placeholder-text-dim outline-none font-mono
                           focus:border-primary/50 transition-colors"
              />
              <button
                onClick={activate}
                disabled={loading || !key.trim()}
                className="px-5 py-2.5 bg-primary text-white rounded-lg text-sm font-semibold
                           hover:bg-primary-hover disabled:opacity-40 disabled:cursor-not-allowed
                           transition-colors"
              >
                {loading ? 'Checking…' : 'Activate'}
              </button>
            </div>
            {status && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                className={clsx(
                  'flex items-center gap-2 text-sm p-3 rounded-lg',
                  status === 'ok'
                    ? 'bg-accent-green/10 text-accent-green border border-accent-green/20'
                    : 'bg-accent/10 text-accent border border-accent/20'
                )}
              >
                {status === 'ok'
                  ? <CheckCircle2 size={16} />
                  : <AlertCircle size={16} />}
                {msg}
              </motion.div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
