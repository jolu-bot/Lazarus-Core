import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/globals.css';

function renderFatal(message) {
  const root = document.getElementById('root');
  if (!root) return;
  root.innerHTML = '<div style="padding:20px;font-family:Segoe UI,sans-serif;background:#0A0A0F;color:#E8E8E8;height:100vh">'
    + '<h2>Lazarus Core - Renderer Error</h2>'
    + '<pre style="white-space:pre-wrap">' + String(message || 'Unknown error') + '</pre>'
    + '</div>';
}

window.addEventListener('error', (e) => {
  renderFatal(e?.error?.stack || e?.message || 'window error');
});

window.addEventListener('unhandledrejection', (e) => {
  renderFatal(e?.reason?.stack || e?.reason || 'unhandled rejection');
});

try {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
} catch (e) {
  renderFatal(e?.stack || e?.message || e);
}
