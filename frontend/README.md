# tls-reputation.com — frontend

Vue 3 + Vite single-page app for the TLS fingerprint reputation service. No state
library, no UI kit, no CSS framework — plain scoped CSS over the design tokens in
`src/assets/base.css`.

## Setup

```sh
npm install
npm run dev      # dev server on http://localhost:5173
npm run build    # production bundle into dist/
npm run preview  # serve the built bundle locally
```

Requires Node 18+.

## Talking to the API

The API base URL comes from `VITE_API_BASE` and defaults to `/api/v1`.

| Environment | Value | How requests reach the backend |
| --- | --- | --- |
| dev (default) | `/api/v1` | Vite proxies `/api` to `http://localhost:8000` (see `vite.config.js`) |
| dev, remote API | `VITE_API_BASE=https://tls-reputation.com/api/v1` | direct; the backend must send CORS headers |
| production | `/api/v1` | same origin, no proxy needed |

To point the dev server at something other than `localhost:8000`, either edit the
proxy target in `vite.config.js` or set an absolute `VITE_API_BASE`. Create a
`.env.local` (git-ignored) for local overrides:

```sh
VITE_API_BASE=http://localhost:9000/api/v1
```

Vite only exposes variables prefixed with `VITE_`, and it inlines them at build
time — a production build needs the variable set when `npm run build` runs, not
when the server starts.

## Deployment

The app uses history-mode routing, so the web server must serve `index.html` for
any path that isn't a real file. Nginx:

```nginx
location / {
    try_files $uri $uri/ /index.html;
}
```

Leave `/api` routed to the FastAPI backend so the relative default keeps working,
and so `/api/docs` and `/api/openapi.json` stay reachable from the docs page.

## Layout

```
src/
  api.js            fetch wrapper, ApiError, one method per endpoint
  format.js         number/date formatting, JA3/JA4/domain classification
  router.js         routes; home is eager, everything else lazy
  App.vue           masthead, nav, theme toggle, footer
  assets/base.css   design tokens + reset for both themes
  components/       DataTable, StatGrid, CopyText, SpreadBar,
                    ThemeToggle, LookupInput, Pagination
  views/            Home, Fingerprint, Sni, Browse, Docs, NotFound
```

## Conventions

- **Theme.** Follows `prefers-color-scheme` by default; the toggle writes
  `data-theme` on `<html>` and persists to `localStorage` under `tlsrep-theme`.
  An inline script in `index.html` applies the stored choice before first paint
  so there is no flash of the wrong theme.
- **Design.** Square corners, 1px borders, one accent colour (amber), no
  shadows, no gradients, no animation. Data is monospace with tabular numerals;
  numbers are right-aligned. Wide tables scroll inside their own container so
  the page body never scrolls sideways.
- **404 vs. error.** A fingerprint or domain missing from the corpus renders a
  plain "not observed" page. Only transport and 5xx failures render as errors.
