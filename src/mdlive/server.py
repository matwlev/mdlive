import html
import json
import mimetypes
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from watchfiles import watch

from .config import load, remote
from .theme import BUNDLED_ASSETS, BUNDLED_DEPENDENCIES
from .render import page, render, url_path


class App:
    def __init__(self, config):
        self.config = config
        self.stop = threading.Event()
        self.condition = threading.Condition(threading.RLock())
        self.revision = 0
        self.reload_revision = uuid.uuid4().hex
        self.mapping = {}
        self.remap()

    def remap(self):
        assets = dict.fromkeys(item for layer in self.config.layers
                               for key in ('style_links', 'script_links') for item in layer[key]
                               if not remote(item))
        for item in list(assets):
            assets.update(dict.fromkeys(BUNDLED_DEPENDENCIES.get(item, [])))
        self.mapping = {}
        custom_index = 0
        for item in assets:
            if item in BUNDLED_ASSETS:
                self.mapping[item] = BUNDLED_ASSETS[item]
            else:
                self.mapping[item] = f'/__mdlive/assets/{custom_index}'
                custom_index += 1

    def path(self, request_path):
        decoded = unquote(request_path)
        if '\x00' in decoded or '\\' in decoded:
            raise ValueError('Invalid path')
        p = (self.config.root / decoded.lstrip('/')).resolve()
        if not p.is_relative_to(self.config.root):
            raise ValueError('Path outside served root')
        return p

    def files(self):
        files = []
        # os.walk skips directory errors, including errors raised while iterating
        # cloud-backed directories. An unrelated unreadable item must not make
        # the requested document fail to render.
        for directory, _, names in os.walk(self.config.root, followlinks=False):
            for name in names:
                p = Path(directory) / name
                if p.suffix.lower() not in ('.md', '.markdown'):
                    continue
                try:
                    if p.is_file() and p.resolve().is_relative_to(self.config.root):
                        files.append(url_path(p, self.config.root))
                except (OSError, RuntimeError):
                    # Files can disappear, become inaccessible, or form a
                    # symlink loop between enumeration and stat/resolve.
                    continue
        return sorted(files)

    def snapshot(self, request_path):
        with self.condition:
            path = self.config.entry if request_path == '/' else self.path(request_path)
            if not path.resolve().is_relative_to(self.config.root):
                raise ValueError('Path outside served root')
            data = dict(currentPath=url_path(path, self.config.root), files=self.files(), headings=[])
            try:
                if path.suffix.lower() not in ('.md', '.markdown'):
                    raise ValueError('Not a Markdown document')
                content, data['headings'] = render(path.read_text(encoding='utf-8'), self.config.generator)
            except FileNotFoundError:
                content = '<p>Document not found. Waiting for the file to return.</p>'
            except Exception as exc:
                print(f'Rendering error: {exc}', flush=True)
                content = f'<p>Rendering error: {html.escape(str(exc))}</p>'
            return dict(html=content, data=data, revision=self.revision, reloadRevision=self.reload_revision)

    def changed(self, paths):
        with self.condition:
            paths = {Path(p).resolve() for p in paths}
            config = self.config
            reload_page = False
            if config.source in paths:
                try:
                    new = load(config.args, source=config.source, rediscover=False,
                               generator=config.generator)
                    if new.values['heading_id_generator'] != config.values['heading_id_generator']:
                        print('Heading generator changes require restart.', flush=True)
                        new.values['heading_id_generator'] = config.values['heading_id_generator']
                    for key in ('host', 'port'):
                        if new.values[key] != config.values[key]:
                            print(f'{key} changes require restart.', flush=True)
                            new.values[key] = config.values[key]
                    self.config = new
                    self.remap()
                    reload_page = True
                except Exception as exc:
                    print(f'Config reload failed; retaining last valid config: {exc}', flush=True)
                paths.discard(config.source)
            generator_path = config.values['heading_id_generator']
            if generator_path:
                paths.discard(Path(generator_path.rpartition(':')[0]))
            theme_paths = {Path(p) for p in self.mapping}
            if any(p in theme_paths or (not p.is_dir() and p.suffix.lower() not in ('.md', '.markdown'))
                   for p in paths):
                reload_page = True
            if not paths and not reload_page:
                return
            self.revision += 1
            if reload_page:
                self.reload_revision = uuid.uuid4().hex
            print('Reload: ' + ', '.join(str(p) for p in paths or [config.source]), flush=True)
            self.condition.notify_all()

    def watch_loop(self):
        while not self.stop.is_set():
            watched = {self.config.root}
            watched.update(Path(p).parent for p in self.mapping)
            if self.config.source:
                watched.add(self.config.source.parent)
            try:
                for changes in watch(*watched, stop_event=self.stop, debounce=150, step=150,
                                     watch_filter=None, yield_on_timeout=True, rust_timeout=500):
                    if changes:
                        relevant = []
                        for _, name in changes:
                            p = Path(name).resolve()
                            if p.is_relative_to(self.config.root) or p == self.config.source or str(p) in self.mapping:
                                # Ignore development/cache directories, not document names.
                                relparts = p.relative_to(self.config.root).parts if p.is_relative_to(self.config.root) else ()
                                if not any(x in ('.git', '.venv', '__pycache__', '.pytest_cache') for x in relparts):
                                    relevant.append(p)
                        if relevant:
                            self.changed(relevant)
                        if watched != ({self.config.root} | {Path(p).parent for p in self.mapping}
                                       | ({self.config.source.parent} if self.config.source else set())):
                            break
            except Exception as exc:
                print(f'Watcher error: {exc}', flush=True)
                self.stop.wait(1)

    def close(self):
        self.stop.set()
        with self.condition:
            self.condition.notify_all()


def make_server(app, host, port):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def send(self, body, kind='text/html; charset=utf-8', status=200):
            body = body.encode() if isinstance(body, str) else body
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            try:
                request = urlsplit(self.path)
                route = request.path
                if route == '/__mdlive/events':
                    if self.command == 'HEAD':
                        self.send('', 'text/event-stream')
                        return
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.connection.settimeout(2)
                    seen = -1
                    while not app.stop.is_set():
                        with app.condition:
                            if seen == app.revision:
                                app.condition.wait(timeout=1)
                            changed = seen != app.revision
                            seen = app.revision
                            payload = json.dumps(dict(revision=seen, reloadRevision=app.reload_revision))
                        self.wfile.write((f'data: {payload}\n\n' if changed else ': keepalive\n\n').encode())
                        self.wfile.flush()
                    self.close_connection = True
                    return
                if route.startswith('/__mdlive/themes/'):
                    path = next((Path(p) for p, url in BUNDLED_ASSETS.items() if url == route), None)
                    if path is None:
                        self.send('Not found', status=404)
                    else:
                        self.send(path.read_bytes(), 'text/css; charset=utf-8')
                    return
                if route == '/__mdlive/client.js':
                    self.send(Path(__file__).with_name('client.js').read_bytes(), 'text/javascript; charset=utf-8')
                    return
                if route == '/__mdlive/document':
                    target = parse_qs(request.query).get('path', ['/'])[0]
                    self.send(json.dumps(app.snapshot(target)), 'application/json')
                    return
                if route.startswith('/__mdlive/assets/'):
                    with app.condition:
                        path = next((Path(p) for p, url in app.mapping.items() if url == route), None)
                    if path is None:
                        self.send('Not found', status=404)
                        return
                else:
                    path = app.config.entry if route == '/' else app.path(route)
                    if not path.resolve().is_relative_to(app.config.root):
                        raise ValueError('Path outside served root')
                    if path.suffix.lower() in ('.md', '.markdown'):
                        with app.condition:
                            state = app.snapshot(route)
                            self.send(page(state['html'], state['data'], app.config, app.mapping,
                                           {k: state[k] for k in ('revision', 'reloadRevision')}))
                        return
                if not path.is_file():
                    self.send('Not found', status=404)
                    return
                self.send(path.read_bytes(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
            except (ValueError, PermissionError):
                self.send('Forbidden', status=403)
            except FileNotFoundError:
                self.send('Not found', status=404)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            except Exception as exc:
                print(f'Request error: {exc}', flush=True)
                self.send('Internal server error', status=500)
    return ThreadingHTTPServer((host, port), Handler)
