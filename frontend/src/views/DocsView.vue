<script setup>
import { ref, onBeforeUnmount } from 'vue'
import { RouterLink } from 'vue-router'

// Documentation shows the canonical public base, not the local dev override.
const BASE = 'https://tls-reputation.com/api/v1'

const endpoints = [
  {
    id: 'ja4',
    sig: 'GET /api/v1/ja4/{ja4}',
    desc: 'Look up a fingerprint by its JA4 string. JA4 is the identity in this corpus, so this is the canonical route. Returns a fingerprint object. 404 if the JA4 has never been observed.',
    curl: `curl -s ${BASE}/ja4/t13d1516h2_8daaf6152771_e5627efa2ab1`,
  },
  {
    id: 'ja3',
    sig: 'GET /api/v1/ja3/{md5}',
    desc: 'Resolve a JA3 md5 to the fingerprint that emitted it. JA3 is not an identity — a client that permutes its ClientHello emits a new one per connection — so this is a lookup through the variant table, and the response carries an extra matched_ja3 block saying which JA4 it resolved to. Otherwise the same object as /ja4. A 404 here does not mean an unknown client; try its JA4.',
    curl: `curl -s ${BASE}/ja3/cd08e31494f9531f560d64c695473da9`,
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
    desc: 'Paginated list of all fingerprints. sort is one of observations, unique_snis, spread, last_seen — always descending. Items carry ja4, a nullable ja3, alpn, stability and the counters. There is no sort key for stability.',
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
    id: 'alpn',
    sig: 'GET /api/v1/alpn',
    desc: 'How the corpus splits across ALPN offer lists, reported both per distinct fingerprint and per observation. Keyed on the offer list in order, which is never normalised — the order is the signal. No parameters.',
    curl: `curl -s ${BASE}/alpn`,
  },
  {
    id: 'stats',
    sig: 'GET /api/v1/stats',
    desc: 'Corpus totals and the observation window.',
    curl: `curl -s ${BASE}/stats`,
  },
]

const fingerprintExample = `{
  "ja4": "t13d1516h2_8daaf6152771_e5627efa2ab1",
  "ja4_r": "t13d1516h2_002f,0035,009c...",
  "ja3": null,
  "ja3_raw": null,
  "tls_version": "TLS 1.3",
  "alpn": ["h2", "http/1.1"],
  "observations": 4341,
  "unique_snis": 31,
  "spread": 0.651,
  "stability": {
    "class": "randomizing",
    "novelty": 0.94,
    "variants": 128,
    "variants_capped": true,
    "observations": 4341,
    "dominant_variant_share": 0.12,
    "explanation": "94% of connections presented a JA3 never seen before..."
  },
  "cipher_suites": [{"value": "0x1301", "name": "TLS_AES_128_GCM_SHA256"}],
  "extensions": [{"value": "0x0000", "name": "server_name"}],
  "extensions_sorted": true,
  "curves": [{"value": "0x001d", "name": "x25519"}],
  "sig_algs": [{"value": "0x0403", "name": "ecdsa_secp256r1_sha256"}],
  "point_formats": ["0x0000"],
  "ja3_variants": {
    "total": 128,
    "capped": true,
    "items": [{"ja3": "cd08e...", "ja3_raw": "771,4865-...", "observations": 1}]
  },
  "first_seen": "2026-01-04T10:22:31Z",
  "last_seen": "2026-07-19T08:00:00Z",
  "top_snis": [{"sni": "example.com", "count": 8123, "share": 0.063}]
}`

// Only the /ja3 route adds this.
const matchedExample = `"matched_ja3": {
  "ja3": "cd08e31494f9531f560d64c695473da9",
  "canonical": "t13d1516h2_8daaf6152771_e5627efa2ab1",
  "also_seen_under": []
}`

const alpnExample = `{
  "total_fingerprints": 2698,
  "total_observations": 15999,
  "items": [
    {"alpn": ["h2", "http/1.1"],
     "label": "h2, http/1.1",
     "fingerprints": 2443,
     "observations": 13591,
     "share_of_fingerprints": 0.9052,
     "share_of_observations": 0.8495}
  ]
}`

const sniExample = `{
  "sni": "example.com",
  "observations": 51221,
  "unique_fingerprints": 88,
  "spread": 0.83,
  "first_seen": "2026-01-04T10:22:31Z",
  "last_seen": "2026-07-19T08:00:00Z",
  "top_fingerprints": [
    {"ja4": "t13d1516h2_...", "ja3": null, "count": 1201, "share": 0.023}
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
        hostile. Read <code>spread</code> and <code>stability</code> together, and weigh both
        against volume.
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
        <dt>ja4</dt>
        <dd>The identity. Always present, and the only field you can key on.</dd>
        <dt>ja3, ja3_raw</dt>
        <dd>
          <strong><code>null</code> whenever more than one JA3 has been seen</strong> under this
          JA4 — which is the common case, not the exception. Guard for it at every render site.
          A representative JA3 for a permuting client is a value that will never match again, so
          the API returns nothing rather than something misleading. The full list is in
          <code>ja3_variants</code>.
        </dd>
        <dt>spread</dt>
        <dd>
          Normalised Shannon entropy of the SNI distribution, 0..1. 0 = always the same domain,
          1 = evenly spread across many unrelated domains. It measures reach, not intent — see
          below. On low-volume fingerprints it is noise.
        </dd>
        <dt>stability</dt>
        <dd>
          Whether the stack randomises its own fingerprint. Same object shape from
          <code>/ja3</code>, <code>/ja4</code> and <code>/fingerprints</code>. See below.
        </dd>
        <dt>ja3_variants</dt>
        <dd>
          <code>{ total, capped, items }</code>. Each item is
          <code>{ ja3, ja3_raw, observations }</code>, busiest first, and
          <code>items</code> is truncated — <code>total</code> is the count. When
          <code>capped</code> is true the corpus has stopped recording new variants for this
          fingerprint, so <code>total</code> is a floor rather than a total.
        </dd>
        <dt>matched_ja3</dt>
        <dd>
          Present only on the <code>/ja3</code> route. <code>canonical</code> is the JA4 the hash
          resolved to when the resolution was unambiguous, and <code>null</code> when it was not
          — in which case <code>also_seen_under</code> lists the other JA4s that have emitted the
          same JA3, and the object you were served is merely the busiest of them.
        </dd>
        <dt>extensions</dt>
        <dd>
          Sorted, and flagged as such by <code>extensions_sorted</code>. Do not present it as the
          client's own order: under one JA4 the wire order varies from connection to connection,
          and that variation is what <code>ja3_variants</code> records.
        </dd>
        <dt>alpn</dt>
        <dd>
          The offered protocols in the client's order of preference. Never sorted; the order
          distinguishes clients that JA4 cannot. Empty array when none were offered.
        </dd>
        <dt>share</dt>
        <dd>Fraction of the parent's total observations, 0..1.</dd>
        <dt>top_snis</dt>
        <dd>Truncated to the most contacted names; <code>unique_snis</code> gives the true count.</dd>
        <dt>timestamps</dt>
        <dd>ISO 8601, always UTC.</dd>
      </dl>

      <h3 class="sub">matched_ja3, on the /ja3 route only</h3>
      <div class="codeblock">
        <pre><code>{{ matchedExample }}</code></pre>
        <button
          type="button"
          class="control copy"
          aria-label="Copy the matched_ja3 example"
          @click="copy('matched', matchedExample)"
        >
          {{ copied === 'matched' ? 'copied' : copied === 'matched:failed' ? 'failed' : 'copy' }}
        </button>
      </div>
    </section>

    <section class="section">
      <h2>Identity is JA4</h2>
      <p>
        Fingerprints used to be keyed on the pair (JA3, JA4). That was wrong. Chrome has permuted
        its ClientHello extension order on every connection since version 110, so JA3 changes
        every time while JA4 — which sorts the extension list before hashing — stays put. That is
        precisely what JA4 was designed for. Measured on live traffic: 162 observations of one
        domain produced 162 distinct JA3 values and 2 distinct JA4 values. Keying on JA3 shattered
        one browser into one row per connection.
      </p>
      <p>
        JA3 is now demoted to a variant under its JA4. It is still a first-class lookup — the
        <code>/ja3</code> route resolves a hash to the client that emitted it — but it is no
        longer an identity, and <code>ja3</code> is <code>null</code> on any fingerprint that has
        emitted more than one.
      </p>
      <p>
        <strong><code>also_seen_as</code> has been removed.</strong> The equivalent information —
        other JA4s that have also emitted the JA3 you looked up — now lives in
        <code>matched_ja3.also_seen_under</code>, and appears only on the <code>/ja3</code> route.
      </p>
    </section>

    <section class="section">
      <h2>Stability</h2>
      <p>
        The second axis, orthogonal to spread. Spread says how widely a client stack roams;
        stability says whether the stack randomises its own fingerprint. That is a property of
        software, which is the only kind of claim an identity-free corpus can support.
      </p>
      <dl class="kv fields">
        <dt>fixed</dt>
        <dd>
          One JA3 across every observed connection: a deterministic stack. Libraries and
          command-line clients look like this.
        </dd>
        <dt>randomizing</dt>
        <dd>
          More than half of connections presented a JA3 never seen before under this JA4. Chrome
          110 and later, and everything built on it.
        </dd>
        <dt>multi_build</dt>
        <dd>
          Several JA3s, but most of them repeat — a handful of stable builds sharing one JA4
          rather than per-connection randomisation.
        </dd>
        <dt>unknown</dt>
        <dd>
          Too few observations to tell a permuting client from a coincidence. Not a finding, an
          absence of one.
        </dd>
        <dt>variants</dt>
        <dd>
          Distinct JA3s recorded. When <code>variants_capped</code> is true this is a floor, not a
          total — render it as <code>128+</code>, never as a bare <code>128</code>.
        </dd>
        <dt>novelty</dt>
        <dd>
          Fraction of connections that presented a JA3 not previously seen under this JA4, 0..1.
        </dd>
        <dt>dominant_variant_share</dt>
        <dd>
          Share of connections carried by the single busiest JA3; detail routes only. A high value
          on a <code>randomizing</code> profile is worth noticing: it is what a deterministic
          client wearing a browser's JA4 looks like, since tools that reproduce a browser's JA4
          rarely implement the permutation behind it.
        </dd>
        <dt>explanation, note</dt>
        <dd>
          Prose, safe to display verbatim. Treat both as optional — do not require them.
        </dd>
      </dl>
      <p>
        There is no <code>sort=stability</code>, deliberately: it is a class, not a magnitude.
        Read the two axes together instead. A <code>fixed</code> stack that reaches many unrelated
        domains is the combination worth opening; <code>randomizing</code> with broad reach is
        what a popular browser looks like.
      </p>
    </section>

    <section class="section">
      <h2>ALPN distribution</h2>
      <div class="codeblock">
        <pre><code>{{ alpnExample }}</code></pre>
        <button
          type="button"
          class="control copy"
          aria-label="Copy the ALPN distribution example"
          @click="copy('alpn', alpnExample)"
        >
          {{ copied === 'alpn' ? 'copied' : copied === 'alpn:failed' ? 'failed' : 'copy' }}
        </button>
      </div>
      <p>
        Keyed on the offer list <em>in order</em>. The order is never normalised, because it is
        the signal: a browser offers <code>h2</code> before <code>http/1.1</code>, and a client
        that lists them the other way round is not the browser it claims to be.
        <code>["h2","http/1.1"]</code> and <code>["http/1.1","h2"]</code> are therefore two
        separate items, and merging them would erase the only thing the endpoint is for.
      </p>
      <p>
        JA4 cannot carry this. It keeps only the first and last character of the
        <em>first</em> offered protocol, so <code>h2</code> and <code>h2, http/1.1</code> reduce
        to the same two characters and everything after the first protocol is lost.
      </p>
      <dl class="kv fields">
        <dt>label</dt>
        <dd>
          The offer list joined with commas, or <code>null</code> when the client offered no ALPN
          at all. Render that case explicitly rather than as a blank.
        </dd>
        <dt>fingerprints</dt>
        <dd>Distinct fingerprints with this exact offer list.</dd>
        <dt>observations</dt>
        <dd>
          Connections from those fingerprints. The two denominators disagree, and the disagreement
          is informative: a few library fingerprints can carry a large share of all connections.
        </dd>
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
          <code>top_fingerprints</code> is truncated to the most frequent. Distinct here means
          distinct JA4, so a browser that permutes its ClientHello counts once, not once per
          connection.
        </dd>
        <dt>top_fingerprints[].ja3</dt>
        <dd>
          Nullable, on the same rule as everywhere else: absent whenever the fingerprint has
          emitted more than one JA3. <code>ja4</code> is always there.
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
        stack roaming many unrelated domains.
      </p>
      <p>
        <strong>Spread is not a verdict, and it never was one on its own.</strong> A single JA4
        aggregates every install of a given build, so a popular browser has high volume, thousands
        of domains and spread close to <code>1</code> — the same shape a scraper has. This corpus
        stores no per-connection identity, deliberately: that is what makes it publishable, and it
        is also why it can never distinguish one scraper reaching 500 domains from 500 people
        reaching one domain each. Spread is one coordinate. Pair it with
        <code>stability</code>, which is a claim about software and therefore one the data can
        actually support.
      </p>
      <p>
        On a <strong>domain</strong>, spread is entropy over the fingerprints that reach it.
        <code>0</code> means essentially one client stack reaches it. The middle of the range,
        roughly <code>0.3</code>–<code>0.7</code>, is what ordinary traffic looks like: a mix of
        real clients, unevenly distributed. Near <code>1.0</code> means many distinct client stacks
        in near-equal proportion — unremarkable on a busy public site, and worth a second look on a
        login or API endpoint, though the corpus cannot tell you whether that variety is a varied
        audience or one actor cycling through TLS stacks.
      </p>
      <p>
        In both directions the number is meaningless without volume. Always read it against
        <code>observations</code> and the relevant unique count: spread <code>1.0</code> over three
        connections is noise; spread <code>1.0</code> over sixty thousand is worth investigating.
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
        never been observed — treat it as an answer, not a failure. On a JA3 that 404 is
        especially weak evidence: a permuting client emits a new hash every connection, so look
        the client up by its JA4 instead. <code>400</code> means the path value is not a valid
        JA3 hash, JA4 string or hostname; <code>422</code> means a query parameter failed
        validation.
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

/* A heading inside a section, one step below the section label. */
.sub {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-weight: 600;
  margin: var(--sp-5) 0 var(--sp-3);
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
  grid-template-columns: 11rem minmax(0, 1fr);
}

/* Some field names are long enough to leave the column. */
.fields dt {
  overflow-wrap: anywhere;
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
