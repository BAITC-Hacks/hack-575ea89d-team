(() => {
  'use strict';
  const key = 'network-dashboard:appearance:v1';
  let mode = 'light';
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '{}');
    if (saved && ['light','dark'].includes(saved.mode)) mode = saved.mode;
  } catch { /* Appearance remains usable when storage is blocked. */ }
  function apply(save = false) {
    document.documentElement.dataset.theme = mode;
    document.querySelectorAll('[data-theme-mode]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.themeMode === mode)));
    const status = document.getElementById('appearance-status');
    if (status) status.textContent = `${mode === 'dark' ? 'Тёмная' : 'Светлая'} тема`;
    if (save) { try { localStorage.setItem(key,JSON.stringify({mode})); } catch { /* Keep the session choice. */ } }
  }
  apply();
  document.addEventListener('DOMContentLoaded',() => {
    document.querySelectorAll('[data-theme-mode]').forEach(button => button.addEventListener('click',() => { mode = button.dataset.themeMode; apply(true); }));
    apply(true);
  });
})();
