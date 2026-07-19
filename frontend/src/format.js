/**
 * Formatting + input-classification helpers.
 *
 * Classification runs client-side so the home page can route a lookup without
 * a round trip. The server's /search endpoint remains the authority; this is
 * only a fast path for the obvious cases.
 */

const RE_JA3 = /^[0-9a-f]{32}$/i

// JA4: <10-char profile>_<12 hex>_<12 hex>, e.g. t13d1516h2_8daaf6152771_02713d6af862
const RE_JA4 = /^[a-z0-9]{10}_[0-9a-f]{12}_[0-9a-f]{12}$/i

// Hostname: labels of alphanumerics/hyphens, at least one dot, no trailing dot.
const RE_DOMAIN = /^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$/i

/**
 * @param {string} raw
 * @returns {"ja3"|"ja4"|"sni"|"unknown"}
 */
export function classifyQuery(raw) {
  const q = normalizeQuery(raw)
  if (!q) return 'unknown'
  if (RE_JA3.test(q)) return 'ja3'
  if (RE_JA4.test(q)) return 'ja4'
  if (RE_DOMAIN.test(q)) return 'sni'
  return 'unknown'
}

/** Trim, lowercase, and strip a pasted scheme/path/port so URLs work as domains. */
export function normalizeQuery(raw) {
  let q = String(raw ?? '').trim()
  if (!q) return ''
  q = q.replace(/^[a-z][a-z0-9+.-]*:\/\//i, '') // scheme
  q = q.replace(/^[^/@]*@/, '') // userinfo
  q = q.split(/[/?#]/)[0] // path, query, fragment
  q = q.replace(/:\d+$/, '') // port
  q = q.replace(/\.$/, '') // fully-qualified trailing dot
  return q.toLowerCase()
}

/** The route a classified query should navigate to, or null if unroutable. */
export function routeForQuery(raw) {
  const q = normalizeQuery(raw)
  switch (classifyQuery(q)) {
    case 'ja3':
    case 'ja4':
      return { name: 'fingerprint', params: { hash: q } }
    case 'sni':
      return { name: 'sni', params: { name: q } }
    default:
      return null
  }
}

/* -------------------------------------------------------------------------
   Numbers, shares, dates
   ------------------------------------------------------------------------- */

const nfInt = new Intl.NumberFormat('en-US')

/** 128401 -> "128,401" */
export function formatInt(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—'
  return nfInt.format(Number(n))
}

/** 0.063 -> "6.30%"; keeps small shares legible instead of collapsing to 0%. */
export function formatShare(share) {
  if (share === null || share === undefined || Number.isNaN(Number(share))) return '—'
  const pct = Number(share) * 100
  if (pct > 0 && pct < 0.01) return '<0.01%'
  const digits = pct >= 10 ? 1 : 2
  return `${pct.toFixed(digits)}%`
}

/** 0.87 -> "0.870" — always 3 decimals so the column aligns. */
export function formatSpread(spread) {
  if (spread === null || spread === undefined || Number.isNaN(Number(spread))) return '—'
  return Number(spread).toFixed(3)
}

/**
 * JA3 variant counts: "128+" once the corpus has stopped recording new ones.
 *
 * Past the cap the stored count is a floor, not a total, and rendering a bare
 * "128" would claim a precision the corpus does not have.
 */
export function formatVariantCount(count, capped = false) {
  if (count === null || count === undefined || Number.isNaN(Number(count))) return '—'
  return `${formatInt(count)}${capped ? '+' : ''}`
}

/** ISO 8601 -> "2026-01-04 10:22 UTC" */
export function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  const p = (n) => String(n).padStart(2, '0')
  return (
    `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` +
    `${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`
  )
}

/** Shorten a long fingerprint for table cells: keeps head and tail. */
export function truncateMiddle(value, head = 10, tail = 6) {
  const s = String(value ?? '')
  if (s.length <= head + tail + 1) return s
  return `${s.slice(0, head)}…${s.slice(-tail)}`
}

/** Human label for a TLS value list entry: "0x1301 TLS_AES_128_GCM_SHA256". */
export function tlsEntryLabel(entry) {
  if (!entry) return ''
  return entry.name ? `${entry.value} ${entry.name}` : String(entry.value)
}
