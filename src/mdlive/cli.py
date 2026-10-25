import threading
import webbrowser

from .config import load, parser
from .server import App, make_server


def main():
    p = parser()
    args = p.parse_args()
    try:
        config = load(args)
        app = App(config)
        server = make_server(app, config.values['host'], config.values['port'])
    except Exception as exc:
        p.exit(2, f'mdlive: {exc}\n')
    worker = threading.Thread(target=app.watch_loop, daemon=True)
    worker.start()
    host = config.values['host']
    display_host = '127.0.0.1' if host == '0.0.0.0' else host
    url = f'http://{display_host}:{server.server_address[1]}/'
    print(f'mdlive: {url}', flush=True)
    try:
        if config.values['open']:
            try:
                if not webbrowser.open(url):
                    print('Unable to open browser; use the printed URL.', flush=True)
            except Exception as exc:
                print(f'Unable to open browser: {exc}; use the printed URL.', flush=True)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        server.server_close()
        worker.join(timeout=3)
