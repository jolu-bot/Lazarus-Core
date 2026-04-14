'use strict';
const { shell } = require('electron');

// Stripe secret key from env (never hardcode)
let stripe = null;
function getStripe() {
  if (!stripe) {
    const key = process.env.STRIPE_SECRET_KEY;
    if (!key) throw new Error('STRIPE_SECRET_KEY not set');
    stripe = require('stripe')(key);
  }
  return stripe;
}

const PLANS = {
  pro:      { price_id: process.env.STRIPE_PRICE_PRO       || 'price_pro_id',      amount: 4900 },
  proplus:  { price_id: process.env.STRIPE_PRICE_PROPLUS   || 'price_proplus_id',  amount: 7900 },
  business: { price_id: process.env.STRIPE_PRICE_BUSINESS  || 'price_business_id', amount: 19900 },
};

function setupPaymentIPC(ipcMain, store) {
  ipcMain.handle('payment:createSession', async (_, { planId, email }) => {
    try {
      const s = getStripe();
      const plan = PLANS[planId];
      if (!plan) throw new Error('Unknown plan: ' + planId);

      const session = await s.checkout.sessions.create({
        payment_method_types: ['card'],
        mode:                 'payment',
        customer_email:       email,
        line_items: [{
          price_data: {
            currency:     'usd',
            unit_amount:  plan.amount,
            product_data: {
              name: `Lazarus Core ${planId.toUpperCase()}`,
              description: 'Data Recovery Software License',
            },
          },
          quantity: 1,
        }],
        success_url: `https://lazaruscore.com/success?session={CHECKOUT_SESSION_ID}&plan=${planId}`,
        cancel_url:  'https://lazaruscore.com/cancel',
        metadata:    { planId, email },
      });

      shell.openExternal(session.url);
      return { success: true, sessionId: session.id };
    } catch (e) {
      return { success: false, message: e.message };
    }
  });

  ipcMain.handle('payment:checkStatus', async (_, sessionId) => {
    try {
      const s       = getStripe();
      const session = await s.checkout.sessions.retrieve(sessionId);
      return {
        paid:    session.payment_status === 'paid',
        planId:  session.metadata?.planId,
        email:   session.customer_email,
      };
    } catch (e) {
      return { paid: false, error: e.message };
    }
  });
}

module.exports = { setupPaymentIPC };
