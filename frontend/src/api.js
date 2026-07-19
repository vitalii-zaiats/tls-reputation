/**
 * Tiny fetch wrapper around the tls-reputation API.
 *
 * Base URL comes from VITE_API_BASE. In production the frontend is served from
 * the same origin as the API, so the relative default is what you want. In dev,
 * the relative default is handled by the Vite proxy (see vite.config.js).
 */

export const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

/** Thrown for any non-2xx response or transport failure. */
export class ApiError extends Error {
  constructor(message, { status = 0, url = '', body = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.url = url
    this.body = body
  }

  /** 404 means "we have never observed this", which is a real answer, not a fault. */
  get notFound() {
    return this.status === 404
  }
}

function buildUrl(path, params) {
  const url = `${API_BASE}${path}`
  if (!params) return url
  const qs = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    qs.append(key, String(value))
  }
  const query = qs.toString()
  return query ? `${url}?${query}` : url
}

/**
 * @param {string} path      path under the API base, e.g. "/stats"
 * @param {object} [options]
 * @param {object} [options.params]  query string params; empty values dropped
 * @param {AbortSignal} [options.signal]
 */
export async function request(path, { params, signal } = {}) {
  const url = buildUrl(path, params)

  let response
  try {
    response = await fetch(url, {
      signal,
      headers: { Accept: 'application/json' },
    })
  } catch (err) {
    // Re-throw aborts untouched so callers can ignore superseded requests.
    if (err && err.name === 'AbortError') throw err
    throw new ApiError('Network error — could not reach the API.', { url })
  }

  if (!response.ok) {
    let body = null
    let detail = ''
    try {
      body = await response.json()
      if (body && typeof body.detail === 'string') detail = body.detail
    } catch (e) {
      /* non-JSON error body; the status alone will have to do */
    }
    throw new ApiError(detail || `Request failed with status ${response.status}.`, {
      status: response.status,
      url,
      body,
    })
  }

  try {
    return await response.json()
  } catch (e) {
    throw new ApiError('Malformed JSON in API response.', {
      status: response.status,
      url,
    })
  }
}

/* -------------------------------------------------------------------------
   Endpoints
   ------------------------------------------------------------------------- */

export const api = {
  ja3: (md5, opts) => request(`/ja3/${encodeURIComponent(md5)}`, opts),

  ja4: (ja4, opts) => request(`/ja4/${encodeURIComponent(ja4)}`, opts),

  sni: (domain, { limit, offset, ...opts } = {}) =>
    request(`/sni/${encodeURIComponent(domain)}`, { params: { limit, offset }, ...opts }),

  fingerprints: ({ sort, limit, offset, ...opts } = {}) =>
    request('/fingerprints', { params: { sort, limit, offset }, ...opts }),

  snis: ({ limit, offset, ...opts } = {}) =>
    request('/snis', { params: { limit, offset }, ...opts }),

  search: (q, opts) => request('/search', { params: { q }, ...opts }),

  stats: (opts) => request('/stats', opts),
}

export default api
