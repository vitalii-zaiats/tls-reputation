<script setup>
import { ref, onBeforeUnmount } from 'vue'
import { RouterLink } from 'vue-router'

// Documentation shows the canonical public base, not the local dev override.
const BASE = 'https://tls-reputation.com/api/v1'

const endpoints = [
  {
    id: 'ja3',
    sig: 'GET /api/v1/ja3/{md5}',
    desc: 'Look up a fingerprint by its JA3 md5 hash. Returns a fingerprint object. 404 if the hash has never been observed.',
    curl: `curl -s ${BASE}/ja3/cd08e31494f9531f560d64c695473da9`,
  },
  {
    id: 'ja4',
    sig: 'GET /api/v1/ja4/{ja4}',
    desc: 'Look up a fingerprint by its JA4 string. Returns the same fingerprint object shape as /ja3.',
    curl: `curl -s ${BASE}/ja4/t13d1516h2_8daaf6152771_02713d6af862`,
  },
  {
    id: 'sni',
    sig: 'GET /api/v1/sni/{domain}?limit=&offset=',
    desc: 'Which fingerprints have been observed reaching this server name, plus the spread of that name. limit defaults to 50, offset to 0.',
    curl: `curl -s "${BASE}/sni/example.com?limit=50&offset=0"`,
  },
  {
    id: 'fingerprints',
    sig: 'GET /api/v1/fingerprints?sort=&limit=&offset=',
    desc: 'Paginated list of all fingerprints. sort is one of observations, unique_snis, spread — always descending.',
    curl: `curl -s "${BASE}/fingerprints?sort=spread&limit=50&offset=0"`,
  },
  {
    id: 'snis',
    sig: 'GET /api/v1/snis?sort=&limit=&offset=',
    desc: 'Paginated list of all observed server names. sort is one of observations, unique_fingerprints, spread, last_seen — always descending, and defaults to observations.',
    curl: `curl -s "${BASE}/snis?sort=spread&limit=50&offset=0"`,
  },
  {
    id: 'search',
    sig: 'GET /api/v1/search?q=',
    desc: 'Classify an arbitrary string and resolve it. kind is one of ja3, ja4, sni, unknown. match is the corresponding object, or null when the value is well-formed but unobserved.',
    curl: `curl -s "${BASE}/search?q=example.com"`,
  },
  {
    id: 'stats',
    sig: 'GET /api/v1/stats',
    desc: 'Corpus totals and the observation window.',
    curl: `curl -s ${BASE}/stats`,
  },
]

const fingerprintExample = `{
  "ja3": "cd08e31494f9531f560d64c695473da9",
  "ja3_raw": "771,4865-4866-4867-49195,0-23-65281-10-11,29-23-24,0",
  "ja4": "t13d1516h2_8daaf6152771_02713d6af862",
  "ja4_r": "t13d1516h2_002f,0035,009c...",
  "tls_version": "TLS 1.3",
  "alpn": ["h2", "http/1.1"],
  "cipher_suites": [{"value": "0x1301", "name": "TLS_AES_128_GCM_SHA256"}],
  "extensions": [{"value": "0x0000", "name": "server_name"}],
  "curves": [{"value": "0x001d", "name": "x25519"}],
  "sig_algs": [{"value": "0x0403", "name": "ecdsa_secp256r1_sha256"}],
  "observations": 128401,
  "unique_snis": 412,
  "spread": 0.87,
  "first_seen": "2026-01-04T10:22:31Z",
  "last_seen": "2026-07-19T08:00:00Z",
  "top_snis": [{"sni": "example.com", "count": 8123, "share": 0.063}]
}`

const sniExample = `{
  "sni": "example.com",
  "observations": 51221,
  "unique_fingerprints": 88,
  "spread": 0.83,
  "first_seen": "2026-01-04T10:22:31Z",
  "last_seen": "2026-07-19T08:00:00Z",
  "top_fingerprints": [
    {"ja3": "cd08e...", "ja4": "t13d1516h2_...", "count": 1201, "share": 0.023}
  ]
}`

const spreadCurl = `# fingerprints that roam the most domains
curl -s "${BASE}/fingerprints?sort=spread&limit=10"

# domains reached by the widest mix of fingerprints
curl -s "${BASE}/snis?sort=spread&limit=10"`

const copied = ref('')
let timer = null

async function copy(id, text) {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = id
  } catch (e) {
    copied.value = `${id}:failed`
  }
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    copied.value = ''
  }, 1200)
}

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div>
    <header class="head">
      <h1>API documentation</h1>
      <p>
        Everything this site displays is available as JSON over the same API. There is no
        authentication, no API key and no registration. Responses are
        <code>application/json</code>; all endpoints are <code>GET</code>.
      </p>
      <p>
        Base URL: <code>{{ BASE }}</code>
      </p>
      <p>
        Machine-readable specs:
        <a href="/api/docs">/api/docs</a> (interactive) and
        <a href="/api/openapi.json">/api/openapi.json</a> (OpenAPI schema).
      </p>
    </header>

    <section class="section">
      <h2>Terms</h2>
      <p>
        No authentication and no rate limit beyond fair use. If you need bulk access, pull the
        paginated list endpoints at a sane pace rather than hammering lookups — and if you are
        going to run a large crawl, mail us first and we will help you do it cheaply.
      </p>
      <p>
        The data is licensed <a href="https://creativecommons.org/licenses/by/4.0/" rel="license noopener">CC BY 4.0</a>.
        Use it, redistribute it, build on it commercially — just attribute
        <span class="mono">tls-reputation.com</span>.
      </p>
      <p>
        A fingerprint identifies TLS client software, not a person. Nothing here is a verdict:
        absence from the corpus does not make a client trustworthy, and presence does not make it
        hostile. Read the spread, and weigh it against volume.
      </p>
    </section>

    <section class="section">
      <h2>Endpoints</h2>
      <div v-for="ep in endpoints" :key="ep.id" class="endpoint">
        <h3 class="sig">{{ ep.sig }}</h3>
        <p class="desc">{{ ep.desc }}</p>
        <div class="codeblock">
          <pre><code>{{ ep.curl }}</code></pre>
          <button
            type="button"
            class="control copy"
            :aria-label="`Copy example request for ${ep.sig}`"
            @click="copy(ep.id, ep.curl)"
          >
            {{ copied === ep.id ? 'copied' : copied === `${ep.id}:failed` ? 'failed' : 'copy' }}
          </button>
        </div>
      </div>
    </section>

    <section class="section">
      <h2>Fingerprint object</h2>
      <div class="codeblock">
        <pre><code>{{ fingerprintExample }}</code></pre>
        <button
          type="button"
          class="control copy"
          aria-label="Copy the fingerprint object example"
          @click="copy('fp', fingerprintExample)"
        >
          {{ copied === 'fp' ? 'copied' : copied === 'fp:failed' ? 'failed' : 'copy' }}
        </button>
      </div>
      <dl class="kv fields">
        <dt>spread</dt>
        <dd>
          Normalised Shannon entropy of the SNI distribution, 0..1. 0 = always the same domain,
          1 = evenly spread across many unrelated domains. High spread on a high-volume
          fingerprint indicates tooling, not a browser. On low-volume fingerprints it is noise.
        </dd>
        <dt>share</dt>
        <dd>Fraction of the parent's total observations, 0..1.</dd>
        <dt>top_snis</dt>
        <dd>Truncated to the most contacted names; <code>unique_snis</code> gives the true count.</dd>
        <dt>timestamps</dt>
        <dd>ISO 8601, always UTC.</dd>
      </dl>
    </section>

    <section class="section">
      <h2>SNI object</h2>
      <div class="codeblock">
        <pre><code>{{ sniExample }}</code></pre>
        <button
          type="button"
          class="control copy"
          aria-label="Copy the SNI object example"
          @click="copy('sni', sniExample)"
        >
          {{ copied === 'sni' ? 'copied' : copied === 'sni:failed' ? 'failed' : 'copy' }}
        </button>
      </div>
      <dl class="kv fields">
        <dt>spread</dt>
        <dd>
          Normalised Shannon entropy of the fingerprint distribution, 0..1 — the mirror of the
          field on the fingerprint object. See below.
        </dd>
        <dt>unique_fingerprints</dt>
        <dd>
          True count of distinct fingerprints seen reaching the name;
          <code>top_fingerprints</code> is truncated to the most frequent.
        </dd>
        <dt>timestamps</dt>
        <dd>ISO 8601, always UTC.</dd>
      </dl>
    </section>

    <section class="section">
      <h2>Spread reads in two directions</h2>
      <p>
        The same statistic is computed over two different distributions, and the two read in
        opposite ways.
      </p>
      <p>
        On a <strong>fingerprint</strong>, spread is entropy over the domains it reaches.
        <code>0</code> is one client that only ever talks to one host; <code>1</code> is one client
        stack roaming many unrelated domains. High spread on a high-volume fingerprint means
        tooling, not a browser.
      </p>
      <p>
        On a <strong>domain</strong>, spread is entropy over the fingerprints that reach it.
        <code>0</code> means essentially one client stack reaches it. The middle of the range,
        roughly <code>0.3</code>–<code>0.7</code>, is what ordinary traffic looks like: a mix of
        real clients, unevenly distributed. Near <code>1.0</code> means many distinct fingerprints
        in near-equal proportion — unremarkable on a busy public site, but on a login or API
        endpoint it is the signature of one actor rotating fingerprints, where the variety itself
        is the tell.
      </p>
      <p>
        In both directions the number is meaningless without volume. Always read it against
        <code>observations</code> and the relevant unique count: spread <code>1.0</code> over three
        connections is noise; spread <code>1.0</code> over sixty thousand is a finding.
      </p>
      <div class="codeblock">
        <pre><code>{{ spreadCurl }}</code></pre>
        <button
          type="button"
          class="control copy"
          aria-label="Copy the spread example requests"
          @click="copy('spread', spreadCurl)"
        >
          {{ copied === 'spread' ? 'copied' : copied === 'spread:failed' ? 'failed' : 'copy' }}
        </button>
      </div>
    </section>

    <section class="section">
      <h2>Errors</h2>
      <p>
        Errors use standard status codes with a JSON body of the form
        <code>{"detail": "..."}</code>. <code>404</code> means the value is well-formed but has
        never been observed — treat it as an answer, not a failure. <code>422</code> means the
        value is not a valid JA3 hash, JA4 string or hostname.
      </p>
      <p class="links">
        <RouterLink to="/">lookup</RouterLink> ·
        <RouterLink to="/browse">browse</RouterLink>
      </p>
    </section>
  </div>
</template>

<style scoped>
.head {
  margin-bottom: var(--sp-4);
}

.head h1 {
  margin-bottom: var(--sp-4);
}

.endpoint {
  padding: var(--sp-4) 0;
  border-bottom: var(--border-width) solid var(--line);
}

.endpoint:last-child {
  border-bottom: 0;
}

.sig {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--link);
  margin-bottom: var(--sp-2);
  overflow-wrap: anywhere;
}

.desc {
  font-size: var(--fs-sm);
  color: var(--dim);
  margin-bottom: var(--sp-3);
}

.codeblock {
  position: relative;
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-panel);
  background: var(--panel);
}

pre {
  margin: 0;
  padding: var(--sp-4);
  padding-right: 5rem;
  overflow-x: auto; /* long curl lines scroll here, not on the page */
  font-size: var(--fs-sm);
  line-height: 1.5;
}

.copy {
  position: absolute;
  top: var(--sp-2);
  right: var(--sp-2);
  font-size: var(--fs-xs);
  padding: var(--sp-1) var(--sp-2);
}

.fields {
  margin-top: var(--sp-4);
  grid-template-columns: 8rem minmax(0, 1fr);
}

.fields dd {
  font-family: var(--font-sans);
  color: var(--dim);
}

.links {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
}
</style>
