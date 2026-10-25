"""Named asset bundles shared by built-in and configured themes."""
from pathlib import Path
from urllib.parse import urlsplit

ASSETS = ('styles', 'scripts', 'style_links', 'script_links')
BUILTINS = {
    'basic': {'style_links': ['basic.css']},
    'basic-dark': {'extends': ['basic'], 'style_links': ['basic-dark.css']},
    'basic-dynamic': {'extends': ['basic'], 'style_links': ['basic-dynamic.css']},
    'none': {},
}
DIRECTORY = Path(__file__).with_name('themes')
BUNDLED_ASSETS = {str((DIRECTORY / name).resolve()): '/__mdlive/themes/' + name
                  for name in ('basic.css', 'basic-dark.css', 'basic-dynamic.css')}
# Explicit packaged CSS dependencies; custom CSS dependency discovery is out of scope.
BUNDLED_DEPENDENCIES = {
    str((DIRECTORY / 'basic-dynamic.css').resolve()): [str((DIRECTORY / 'basic-dark.css').resolve())]
}


def remote(value):
    return urlsplit(value).scheme.lower() in ('http', 'https')


def resolve(selected, custom, base):
    """Validate the registry and return selected layers in parent-first order."""
    if not isinstance(custom, dict):
        raise ValueError('themes must be an object of named theme definitions')
    definitions = dict(BUILTINS)
    for name, definition in custom.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Theme names must be nonempty strings')
        if name in BUILTINS:
            raise ValueError(f'Theme name is reserved: {name}')
        definitions[name] = definition
    for name, definition in definitions.items():
        if not isinstance(definition, dict) or set(definition) - {*ASSETS, 'extends'}:
            raise ValueError(f'Invalid theme definition: {name}')
        for key, value in definition.items():
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f'Theme {name}: {key} must be an array of strings')

    def order(name, active, seen, result):
        chain = ' -> '.join([*active, name])
        if name not in definitions:
            raise ValueError(f'Unknown theme: {chain}')
        if name in active:
            raise ValueError(f'Theme inheritance cycle: {chain}')
        if name in seen:
            return
        for parent in definitions[name].get('extends', []):
            order(parent, [*active, name], seen, result)
        seen.add(name)
        result.append(name)

    # Validate references even in definitions that are not currently selected.
    checked = set()
    for name in definitions:
        order(name, [], checked, [])
    names = []
    order(selected, [], set(), names)
    layers = []
    for name in names:
        definition = definitions[name]
        origin = DIRECTORY if name in BUILTINS else base
        layer = {key: list(definition.get(key, [])) for key in ASSETS}
        for key in ('style_links', 'script_links'):
            layer[key] = [item if remote(item) else str((origin / item).resolve()) for item in layer[key]]
            for item in layer[key]:
                if not remote(item) and not Path(item).is_file():
                    raise ValueError(f'Theme {name}: file does not exist: {item}')
        layers.append(layer)
    return layers
