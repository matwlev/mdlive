# mdlive

Preview Markdown as HTML in your browser, with live updates when files change.

Version **0.1.0**. Requires Python 3.11 or newer.

## Installation

Install from this checkout:

```sh
./install.sh
```

The installer finds Python 3.11+, creates a dedicated environment at `~/.local/share/mdlive/venv`, links the command into `~/.local/bin`, and adds that directory to your shell startup file. Open a new terminal afterward to run `mdlive` from any directory. No environment activation or `sudo` is needed. Run the installer again after updating the checkout.

Use `./install.sh --no-modify-path` to manage PATH yourself. Set `MDLIVE_PYTHON` to choose an interpreter; `MDLIVE_INSTALL_DIR`, `MDLIVE_BIN_DIR`, and `MDLIVE_PROFILE` override installation locations and the shell startup file. Run `./install.sh --help` for details.

Alternatively, install with pipx:

```sh
pipx install .
```

Or use a virtual environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
mdlive --help
mdlive --version
```

## Usage

```sh
# Serve the current directory, starting with README.md
mdlive

# Preview one file
mdlive notes.md

# Serve a directory, starting with its README.md
mdlive ./docs

# Choose a different entry document
mdlive ./docs --index getting-started.md

# Open the browser automatically
mdlive ./docs --open

# Choose the listening address and port
mdlive ./docs --host 127.0.0.1 --port 8080
```

mdlive always prints the preview URL and logs live reloads in the terminal. Opening the browser is opt-in through `--open`. Stop the server with Ctrl+C.

The default address is `http://127.0.0.1:8000`. If the port is occupied, mdlive reports an error.

### Files and directories

With a file argument, mdlive previews that file at `/` and serves supporting assets from its parent directory.

With a directory argument, mdlive serves Markdown files and supporting assets from that directory. `/` renders `README.md` by default. `--index PATH` selects another entry document relative to the served directory. A missing entry document produces a clear startup error. `--index` applies only to directory mode.

Documents are also accessible by their relative paths, such as `/guide/setup.md`. Relative Markdown links and image paths resolve within the served directory. Markdown extensions are `.md` and `.markdown`, matched case-insensitively.

There is no built-in sidebar or generated directory listing. Themes can use the file list to provide navigation.

## Options

| Option | Purpose | Default |
| --- | --- | --- |
| `[path]` | Markdown file or directory to serve | Current directory |
| `--index PATH` | Entry document in directory mode | `README.md` |
| `--open` | Open the preview in the default browser | Off |
| `--host ADDRESS` | Listening address | `127.0.0.1` |
| `--port PORT` | Listening port | `8000` |
| `--theme basic\|none` | Built-in theme; `none` uses browser styling | `basic` |
| `--config PATH` | Select a configuration file explicitly | See configuration lookup |
| `--style CSS` | Inject inline CSS in a `<style>` tag; repeatable | None |
| `--script JS` | Inject inline JavaScript in a `<script>` tag; repeatable | None |
| `--style-link PATH_OR_URL` | Add a stylesheet `<link>`; repeatable | None |
| `--script-link PATH_OR_URL` | Add a `<script src="…">`; repeatable | None |
| `-h`, `--help` | Show usage, options, defaults, and config lookup order | |
| `--version` | Print `mdlive 0.1.0` and exit | |

Help and version commands exit without loading configuration or starting the server.

## Configuration

mdlive selects one configuration file in this order:

1. The file passed with `--config`.
2. `./config.json` in the working directory.
3. `~/.mdlive/config.json`.

Configuration files are not merged. If neither default file exists, mdlive uses its built-in defaults. An explicitly selected file must exist. An invalid selected configuration produces an error.

CLI options override the selected configuration. For repeatable asset options, supplying one or more occurrences replaces the corresponding configuration array. Arrays for other asset categories remain in effect.

Relative paths in configuration resolve against the configuration file's directory. Relative CLI paths resolve against the working directory, except `--index`, which resolves against the served directory. The served path is chosen by the positional argument, not the configuration.

### Example config.json

```json
{
  "theme": "basic",
  "host": "127.0.0.1",
  "port": 8000,
  "open": false,
  "index": "README.md",
  "styles": [
    "body { max-width: 48rem; margin: 2rem auto; padding: 0 1rem; }"
  ],
  "scripts": [
    "document.documentElement.dataset.preview = 'true';"
  ],
  "style_links": [
    "./theme/theme.css"
  ],
  "script_links": [
    "./theme/theme.js"
  ]
}
```

## Rendering and themes

mdlive uses the bundled **basic** reading theme by default: light-only, system fonts, a comfortable reading column, and underlined blue links. It adds no navigation or theme JavaScript and makes no external requests. Authors provide navigation through Markdown links.

Use `mdlive --theme none` for browser-default styling, or set `"theme": "none"` in configuration. `--theme basic` explicitly selects the default. CLI selection overrides configuration; edits to the selected config reload the page. Unsupported theme names produce an error.

Embedded HTML is sanitized: safe formatting is retained, while scripts and unsafe attributes are removed. Syntax highlighting, GitHub-specific Markdown extensions, Mermaid, and math rendering are outside v1.

Custom themes are collections of injected CSS and optional JavaScript supplied through CLI options or configuration. There is no separate custom theme package format or full-page template interface in v1. Custom styles can extend basic or replace it by selecting `none`.

```sh
# Inline styles and scripts
mdlive notes.md --style 'body { font-family: sans-serif; }' --script 'console.log("Preview ready");'

# Local theme files
mdlive ./docs --style-link ./theme.css --script-link ./theme.js

# Reusable configuration
mdlive ./docs --config ./preview.json
```

`--style-link` and `--script-link` accept local filesystem paths or HTTP(S) URLs. mdlive serves explicitly configured local theme files even when they live outside the document root, without exposing their entire parent directory. Relative resources referenced by theme files must be available through the document root or a remote URL in v1.

Injection order is:

1. The selected built-in stylesheet, then custom stylesheet links, then inline styles, in the document head.
2. The rendered Markdown content in the body.
3. Inline scripts, then linked scripts, at the end of the body.

Order within each array follows configuration or CLI order. Theme scripts are explicitly trusted and execute in the preview page; sanitization applies to document content.

### Basic theme tokens

Basic uses two tiers of CSS custom properties, all prefixed `--mdl-`. **Options** name literal values; **intents** map directly to options and describe their purpose. Styling rules consume intents.

Color options include exact `--mdl-color-white` and `--mdl-color-black`, plus `gray`, `blue`, `red`, `orange`, `yellow`, `green`, and `purple` ramps numbered `10` through `90`. Higher numbers mean darker shades. Other options cover font families, sizes, weights, line heights, spacing, widths, borders, and radii. The bundled stylesheet is the complete token reference.

`--mdl-palette-primary` is the accent. Each semantic background has a matching `-contrast` foreground, such as `primary-contrast` or `surface-contrast`. The page uses the explicit pair `palette-background` and `palette-text`. Foreground-only tokens such as `palette-link` need no contrast partner. Default text/background pairs meet at least 4.5:1 contrast; preserve that contrast when overriding tokens.

Load overrides with `--style-link`, or use inline CSS:

```sh
mdlive --style ':root { --mdl-palette-primary: var(--mdl-color-purple-70); --mdl-palette-primary-contrast: var(--mdl-color-white); --mdl-palette-link: var(--mdl-color-purple-70); --mdl-layout-content-width: 65ch; }'
```

Links and primary are separate intents, so changing the accent alone does not change link color. Typography intents include `--mdl-type-body-size` and `--mdl-type-title-1-size`; spacing includes `--mdl-space-paragraph`. Basic stays light even when the system prefers dark mode. Dark mode is reserved for a future extension through semantic mappings.

### Theme interface

Markdown is rendered inside a stable content container:

```html
<main id="mdlive-content">
  <!-- Rendered Markdown -->
</main>
```

Before theme scripts execute, mdlive exposes document and navigation data:

```js
window.mdlive = {
  currentPath: "/guide/setup.md",
  files: ["/README.md", "/guide/setup.md"],
  headings: [
    { id: "installation", text: "Installation", level: 2 },
    { id: "install-on-macos", text: "Install on macOS", level: 3 }
  ]
};
```

`currentPath` identifies the displayed file using its root-relative URL, even when opened through `/`. `files` is the sorted, recursive list of Markdown document URLs within the served root. Unreadable files and directories are skipped when building this list so an unrelated filesystem error cannot break the preview.

`headings` contains the current document's headings in document order. Each entry includes its HTML `id`, plain-text `text`, and heading `level` from 1 through 6. Themes can use this data to build a table of contents.

### Heading IDs and section links

Every rendered heading receives an HTML `id`. The default generator:

- Lowercases the heading's plain text.
- Removes punctuation and special characters, retaining Unicode letters and numbers.
- Replaces whitespace runs with one hyphen and trims surrounding hyphens.
- Uses `section` if the result is empty.

For example, `Getting Started!` becomes `getting-started`.

mdlive enforces uniqueness after generation, adding `-1`, `-2`, and so on when needed. IDs must be unique within the document, including when a generated suffix matches another heading's text. The final ID is used in both the HTML heading and `window.mdlive.headings`.

Other documents can link directly to a section using a relative Markdown path and fragment:

```md
[Installation](guide/setup.md#installation)
[Install on macOS](guide/setup.md#install-on-macos)
```

Links within the same document can use just the fragment, such as `[Installation](#installation)`. On initial load, mdlive honors the URL fragment after rendering the document. Renaming a heading can change its generated ID and break existing section links.

Explicit custom IDs, such as `## Installation {#install}`, are not supported in 0.1.0.

### Custom heading ID generator

Set `heading_id_generator` in the selected configuration to use a Python callable instead of the default generator:

```json
{
  "heading_id_generator": "./heading_ids.py:generate"
}
```

The path resolves relative to the configuration file. The portion after `:` names the callable in that file:

```python
def generate(text: str, level: int) -> str:
    return text.lower().replace(" ", "_")
```

mdlive calls the generator during rendering with the heading's plain text and level (1–6). It returns a base ID; mdlive handles uniqueness afterward using the same numeric suffixes as the default generator. The result must be a nonempty string without whitespace. Invalid results or generator errors produce a clear rendering error.

Custom generators run in Python independently of theme JavaScript, so section links work without a theme. Loading a generator executes trusted local Python code. Restart mdlive after changing the generator's Python file.

### Theme events

mdlive dispatches these events on `window`:

| Event | When it fires |
| --- | --- |
| `mdlive:ready` | Initial rendering and theme script loading are complete |
| `mdlive:update` | Document content, headings, or file-list data has changed |

The global data, including `headings`, is updated before an event fires. Theme scripts can read `window.mdlive` and build navigation outside `#mdlive-content`:

```js
function updateNavigation() {
  const { currentPath, files, headings } = window.mdlive;
  // Build or update file navigation and a table of contents.
}

window.addEventListener("mdlive:ready", updateNavigation);
window.addEventListener("mdlive:update", updateNavigation);
```

Theme initialization runs once per page load. Content-update handlers should tolerate repeated events.

## Live updates

- Markdown changes replace the rendered content while preserving the browser's scroll position. Theme-created elements outside the content container remain in place.
- Adding or removing Markdown files updates the file list available to themes.
- If the active document disappears, the page shows a missing-document message and recovers when the file returns.
- Local asset, theme-file, or selected-config changes refresh the affected assets or reload the page. These full reloads may reset theme state.
- Browser connections automatically reconnect after interruption.

Changes are debounced and delivered over server-sent events. Remote theme assets are not watched. Config lookup happens at startup; restart mdlive to select a different configuration file through the lookup order.

Invalid config edits retain the last valid configuration and log an error. Changing `host`, `port`, or the heading generator requires a restart; `open` is only applied at startup. Rendering errors appear in the content area and recover after a successful edit. Internal preview endpoints use the reserved `/__mdlive/` URL prefix.

## Development and boundaries

mdlive is implemented in Python with CommonMark rendering, HTML sanitization, filesystem watching, and a threaded HTTP server. Theme assets have no build step.

```sh
python -m pip install -e '.[test]'
python -m playwright install chromium
python -m pytest
```

v1 is a local preview tool. It does not include editing, authentication, or publishing. Requests cannot read arbitrary filesystem paths: document and asset access stays within the served root, including symlink resolution, with explicitly configured theme files as the exception described above.

Tests cover CLI and config behavior, Markdown sanitization, heading generators, local links and assets, filesystem boundaries, theme injection and events, live updates, and file deletion/recovery. Chromium checks cover fragment navigation, theme navigation, scroll preservation, and connection recovery.

## License

MIT License. Copyright (c) 2026 Matt Levek. See [LICENSE](LICENSE).
