/* A reusable color-mode control for themes using mdlive's palette intents. */
(() => {
  const modes = ['light', 'dark', 'dynamic'];
  const storageKey = 'mdlive.color-mode';
  let mode = 'dynamic';
  try {
    const saved = localStorage.getItem(storageKey);
    if (modes.includes(saved)) mode = saved;
  } catch { /* Storage may be unavailable; the control still works for this page. */ }

  const button = document.createElement('button');
  button.type = 'button';
  button.id = 'mdlive-mode-toggle';
  const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  icon.setAttribute('viewBox', '0 0 24 24');
  icon.setAttribute('aria-hidden', 'true');
  icon.setAttribute('fill', 'none');
  icon.setAttribute('stroke', 'currentColor');
  icon.setAttribute('stroke-width', '1.5');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  icon.append(path);
  const text = document.createElement('span');
  button.append(icon, text);
  const paths = {
    light: 'M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
    dark: 'M20 15.3A8.5 8.5 0 0 1 8.7 4a8.5 8.5 0 1 0 11.3 11.3Z',
    dynamic: 'M4 4h16v12H4ZM8 20h8m-4-4v4',
  };
  function apply() {
    document.documentElement.dataset.mdliveMode = mode;
    const title = mode.charAt(0).toUpperCase() + mode.slice(1);
    const next = modes[(modes.indexOf(mode) + 1) % modes.length];
    text.textContent = title;
    path.setAttribute('d', paths[mode]);
    button.setAttribute('aria-label', `Color mode: ${title}. Switch to ${next}.`);
    button.title = button.getAttribute('aria-label');
  }
  button.addEventListener('click', () => {
    mode = modes[(modes.indexOf(mode) + 1) % modes.length];
    apply();
    try { localStorage.setItem(storageKey, mode); } catch { /* Optional persistence. */ }
  });
  window.addEventListener('storage', event => {
    if (event.key === storageKey || event.key === null) {
      mode = modes.includes(event.newValue) ? event.newValue : 'dynamic';
      apply();
    }
  });
  apply();
  document.body.append(button);
})();
