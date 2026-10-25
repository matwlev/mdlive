(() => {
  let revision = window.__mdliveRevision;
  let running = false;
  let pending = false;
  let retry;
  async function update() {
    if (running) { pending = true; return; }
    running = true;
    clearTimeout(retry);
    try {
      const response = await fetch('/__mdlive/document?path=' + encodeURIComponent(location.pathname), {cache: 'no-store'});
      if (!response.ok) throw new Error('Preview update failed');
      const state = await response.json();
      if (state.reloadRevision !== window.__mdliveRevision.reloadRevision) {
        location.reload(); return;
      }
      if (state.revision !== revision.revision) {
        const x = scrollX, y = scrollY;
        document.getElementById('mdlive-content').innerHTML = state.html;
        Object.assign(window.mdlive, state.data);
        revision = state;
        scrollTo(x, y);
        window.dispatchEvent(new Event('mdlive:update'));
      }
    } catch (error) {
      console.error(error);
      retry = setTimeout(update, 1000);
    }
    finally { running = false; if (pending) { pending = false; update(); } }
  }
  function start() {
    window.dispatchEvent(new Event('mdlive:ready'));
    if (location.hash) {
      try { document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView(); }
      catch (error) { console.error(error); }
    }
    const events = new EventSource('/__mdlive/events');
    events.onopen = update;
    events.onmessage = update;
    window.addEventListener('online', update);
    window.addEventListener('beforeunload', () => events.close());
  }
  if (document.readyState === 'complete') start();
  else window.addEventListener('load', start, {once: true});
})();
