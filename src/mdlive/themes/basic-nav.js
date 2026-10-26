/* Folder navigation uses only mdlive's public document data and events. */
(() => {
  let navigation;
  let signature;
  const collator = new Intl.Collator('en', {numeric: true, sensitivity: 'base'});
  const comparePath = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  const decode = value => {
    try { return decodeURIComponent(value); } catch { return value; }
  };
  const label = value => {
    const text = decode(value).replace(/[-_]+/g, ' ').trim() || decode(value);
    return text.charAt(0).toUpperCase() + text.slice(1);
  };
  const isReadme = file => /^readme\.(md|markdown)$/i.test(decode(file.name));
  const compare = (a, b) => collator.compare(label(a.name), label(b.name)) || comparePath(a.path, b.path);

  function tree(files) {
    const root = {folders: new Map(), files: []};
    for (const path of files) {
      const parts = path.split('/').filter(Boolean);
      const name = parts.pop();
      if (!name || !/\.(md|markdown)$/i.test(decode(name))) continue;
      let node = root;
      let prefix = '';
      for (const part of parts) {
        prefix += '/' + part;
        if (!node.folders.has(part)) {
          node.folders.set(part, {name: part, path: prefix, folders: new Map(), files: []});
        }
        node = node.folders.get(part);
      }
      node.files.push({name, path});
    }
    return root;
  }

  function readme(node) {
    return node.files.filter(isReadme).sort((a, b) => comparePath(a.path, b.path))[0];
  }

  function item(text, path) {
    const li = document.createElement('li');
    const entry = document.createElement(path ? 'a' : 'span');
    entry.textContent = text;
    if (path) entry.setAttribute('href', path);
    else entry.className = 'mdlive-nav-folder';
    li.append(entry);
    return li;
  }

  function list(node, root = false) {
    const ul = document.createElement('ul');
    const index = readme(node);
    if (root && index) ul.append(item('Home', index.path));
    for (const folder of [...node.folders.values()].sort(compare)) {
      const li = item(label(folder.name), readme(folder)?.path);
      li.append(list(folder));
      ul.append(li);
    }
    for (const file of node.files.filter(file => file !== index).sort(compare)) {
      ul.append(item(label(file.name.replace(/\.(md|markdown)$/i, '')), file.path));
    }
    return ul;
  }

  function update() {
    const content = document.getElementById('mdlive-content');
    if (!content || !window.mdlive) return;
    if (!navigation) {
      navigation = document.createElement('nav');
      navigation.id = 'mdlive-site-nav';
      navigation.setAttribute('aria-label', 'Site navigation');
      const layout = document.createElement('div');
      layout.className = 'mdlive-nav-layout';
      content.before(layout);
      layout.append(navigation, content);
    }
    const files = [...new Set(window.mdlive.files)].sort(comparePath);
    const nextSignature = JSON.stringify(files);
    if (signature !== nextSignature) {
      const focusedPath = navigation.contains(document.activeElement)
        ? document.activeElement.getAttribute('href') : null;
      const scroll = navigation.scrollTop;
      navigation.replaceChildren(list(tree(files), true));
      if (focusedPath) {
        [...navigation.querySelectorAll('a')].find(link => link.getAttribute('href') === focusedPath)
          ?.focus({preventScroll: true});
      }
      navigation.scrollTop = scroll;
      signature = nextSignature;
    }
    for (const link of navigation.querySelectorAll('a')) {
      if (link.getAttribute('href') === window.mdlive.currentPath) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    }
  }

  window.addEventListener('mdlive:ready', update);
  window.addEventListener('mdlive:update', update);
})();
