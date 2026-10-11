import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App.jsx';

// Always start at the top after reload — do not restore prior scroll position.
if (typeof history !== 'undefined' && 'scrollRestoration' in history) {
  history.scrollRestoration = 'manual';
}
window.scrollTo(0, 0);

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
