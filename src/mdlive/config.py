import argparse
import importlib.util
import json
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from .theme import ASSETS, remote, resolve

DEFAULTS = dict(theme='basic', themes={}, host='127.0.0.1', port=8000, open=False, index='README.md',
                styles=[], scripts=[], style_links=[], script_links=[], heading_id_generator=None)


def parser():
    p = argparse.ArgumentParser(description='Preview Markdown with live updates.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Config lookup: --config, ./config.json, ~/.mdlive/config.json (first available).\n'
               'Defaults: path=., host=127.0.0.1, port=8000, index=README.md, open=off.\n'
               'CLI values override config; repeatable asset flags replace that config array.')
    p.add_argument('--version', action='version', version=f'mdlive {version("mdlive")}')
    p.add_argument('path', nargs='?', default='.', help='Markdown file or directory (default: .)')
    p.add_argument('--config', type=Path, help='Explicit JSON configuration')
    p.add_argument('--theme', metavar='NAME', default=None,
                   help='Named theme (built-in or configured; default: basic; none for browser styling)')
    p.add_argument('--host', default=None, help='Listening address (default: 127.0.0.1)')
    p.add_argument('--index', default=None, help='Directory entry document (default: README.md)')
    p.add_argument('--port', type=int, default=None, help='Listening port (default: 8000)')
    p.add_argument('--open', action='store_true', default=None, help='Open the default browser (default: off)')
    for flag, dest in [('style', 'styles'), ('script', 'scripts'),
                       ('style-link', 'style_links'), ('script-link', 'script_links')]:
        p.add_argument('--' + flag, dest=dest, action='append', help='Repeatable; replaces config array')
    return p


def load_generator(value):
    if value is None:
        return None
    path, sep, name = value.rpartition(':')
    if not sep or not name.isidentifier():
        raise ValueError('heading_id_generator must be path.py:function')
    spec = importlib.util.spec_from_file_location('_mdlive_heading_ids', path)
    if spec is None or spec.loader is None:
        raise ValueError('Cannot load heading generator')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, name)
    if not callable(fn):
        raise ValueError('Heading generator must be callable')
    return fn


@dataclass
class Config:
    values: dict
    source: Path | None
    args: argparse.Namespace
    root: Path
    entry: Path
    generator: object
    layers: list[dict]


def load(args, source=None, rediscover=True, generator=None):
    if rediscover:
        source = args.config
        if source is None:
            source = next((p for p in (Path.cwd() / 'config.json', Path.home() / '.mdlive/config.json')
                           if p.is_file()), None)
    source = source.resolve() if source else None
    raw = json.loads(source.read_text()) if source else {}
    if not isinstance(raw, dict) or set(raw) - DEFAULTS.keys():
        raise ValueError('Config must be an object with supported option names')
    values = DEFAULTS.copy()
    values.update(raw)
    for key, val in values.items():
        if key in ASSETS:
            valid = isinstance(val, list) and all(isinstance(x, str) for x in val)
        elif key == 'theme':
            valid = isinstance(val, str) and bool(val)
        elif key == 'themes':
            valid = isinstance(val, dict)
        elif key == 'port':
            valid = type(val) is int and 1 <= val <= 65535
        elif key == 'open':
            valid = type(val) is bool
        elif key == 'heading_id_generator':
            valid = val is None or isinstance(val, str)
        else:
            valid = isinstance(val, str) and bool(val)
        if not valid:
            raise ValueError(f'Invalid configuration value: {key}')
    base = source.parent if source else Path.cwd()
    for key in ('style_links', 'script_links'):
        values[key] = [x if remote(x) else str((base / x).resolve()) for x in values[key]]
    gen = values['heading_id_generator']
    if gen:
        path, sep, name = gen.rpartition(':')
        if not sep:
            raise ValueError('heading_id_generator must be path.py:function')
        values['heading_id_generator'] = f'{(base / path).resolve()}:{name}'
    for key in DEFAULTS:
        override = getattr(args, key, None)
        if override is not None:
            values[key] = override
            if key in ('style_links', 'script_links'):
                values[key] = [x if remote(x) else str(Path(x).resolve()) for x in override]
    if not 1 <= values['port'] <= 65535:
        raise ValueError('Port must be between 1 and 65535')
    target = Path(args.path).resolve()
    if not target.exists():
        raise ValueError(f'Path does not exist: {target}')
    root = target if target.is_dir() else target.parent
    if target.is_file() and args.index is not None:
        raise ValueError('--index applies only to directory mode')
    entry = (root / values['index']).resolve() if target.is_dir() else target
    if not entry.is_relative_to(root) or entry.suffix.lower() not in ('.md', '.markdown'):
        raise ValueError('Entry must be a Markdown file within the served root')
    if rediscover and not entry.is_file():
        raise ValueError(f'Entry document does not exist: {entry}')
    for key in ('style_links', 'script_links'):
        for item in values[key]:
            if not remote(item) and not Path(item).is_file():
                raise ValueError(f'Theme file does not exist: {item}')
    layers = resolve(values['theme'], values['themes'], base)
    layers.append({key: values[key] for key in ASSETS})
    fn = load_generator(values['heading_id_generator']) if rediscover else generator
    return Config(values, source, args, root, entry, fn, layers)
