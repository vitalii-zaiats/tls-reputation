<script setup>
import { computed, ref, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '../api.js'
import { formatInt, formatShare, truncateMiddle } from '../format.js'
import LookupInput from '../components/LookupInput.vue'
import DataTable from '../components/DataTable.vue'
import SpreadBar from '../components/SpreadBar.vue'

const stats = ref(null)

const promiscuous = ref({ rows: [], data: null, loading: true, error: null })
const contacted = ref({ rows: [], data: null, loading: true, error: null })
const varied = ref({ rows: [], data: null, loading: true, error: null })
const alpn = ref({ rows: [], data: null, loading: true, error: null })

const fpColumns = [
  { key: 'ja4', label: 'fingerprint', mono: true },
  { key: 'observations', label: 'obs', align: 'right' },
  { key: 'unique_snis', label: 'snis', align: 'right' },
  { key: 'spread', label: 'spread', align: 'right', width: '9rem' },
]

const sniColumns = [
  { key: 'sni', label: 'sni', mono: true },
  { key: 'observations', label: 'obs', align: 'right' },
  { key: 'unique_fingerprints', label: 'fps', align: 'right' },
]

const variedColumns = [
  { key: 'sni', label: 'domain', mono: true },
  { key: 'unique_fingerprints', label: 'fps', align: 'right' },
  { key: 'spread', label: 'spread', align: 'right', width: '9rem' },
]

/** Prefer the JA4 label but fall back to JA3 for pre-JA4 corpus entries. */
function fpKey(row) {
  return row.ja4 || row.ja3
}

/**
 * The "try" chips under the lookup box. Drawn from the corpus this page has
 * already loaded — never hardcoded — so they always point at something real.
 */
const examples = computed(() => {
  const out = []
  const fp = promiscuous.value.rows[0]
  const key = fp ? fpKey(fp) : ''
  if (key) {
    out.push({
      id: key,
      label: truncateMiddle(key, 12, 6),
      to: { name: 'fingerprint', params: { hash: key } },
    })
  }
  for (const row of contacted.value.rows.slice(0, 2)) {
    if (row?.sni) out.push({ id: row.sni, label: row.sni, to: { name: 'sni', params: { name: row.sni } } })
  }
  return out
})

/** Corpus totals, as three cards. No deltas and no series — the API has neither. */
const statCards = computed(() => {
  if (!stats.value) return []
  return [
    { key: 'fingerprints', label: 'fingerprints', value: formatInt(stats.value.fingerprints) },
    { key: 'snis', label: 'server names', value: formatInt(stats.value.snis) },
    { key: 'observations', label: 'observations', value: formatInt(stats.value.observations) },
  ]
})

/* -------------------------------------------------------------------------
   ALPN distribution
   ------------------------------------------------------------------------- */

const ALPN_BASES = [
  { value: 'fingerprints', label: 'fingerprint' },
  { value: 'observations', label: 'observation' },
]

/** Which denominator the bar is drawn against. Both are always in the table. */
const alpnBasis = ref('fingerprints')

/** Past this the tail is grouped, or the bar becomes a row of hairlines. */
const TOP_ALPN = 8

/**
 * A monochrome amber ramp. The palette has exactly one accent and reserves
 * --green/--red for the spread scale, so rank is expressed as tint rather than
 * as hue — and the table below carries every number in text regardless.
 */
const TINTS = [92, 74, 60, 48, 38, 30, 24, 19]

function tintFor(index, isOther) {
  if (isOther) return 'var(--line-strong)'
  const mix = TINTS[index] ?? 15
  return `color-mix(in srgb, var(--amber) ${mix}%, var(--panel-2))`
}

const alpnColumns = [
  { key: 'label', label: 'alpn offer', mono: true },
  { key: 'fingerprints', label: 'fingerprints', align: 'right' },
  { key: 'share_of_fingerprints', label: 'share of fps', align: 'right' },
  { key: 'observations', label: 'observations', align: 'right' },
  { key: 'share_of_observations', label: 'share of obs', align: 'right' },
]

/**
 * Top offers plus a grouped tail. The offer order inside each row is never
 * touched: `h2, http/1.1` and `http/1.1, h2` are different clients, and
 * normalising them would erase the only thing this table is for.
 */
const alpnRows = computed(() => {
  const items = alpn.value.rows
  if (!items.length) return []

  const head = items.length > TOP_ALPN + 1 ? items.slice(0, TOP_ALPN) : items
  const tail = items.length > TOP_ALPN + 1 ? items.slice(TOP_ALPN) : []

  const rows = head.map((item, i) => ({
    id: item.label ?? '(none offered)',
    // A null label means the client advertised no ALPN at all, which is a
    // finding of its own, not a missing value.
    label: item.label ?? '(none offered)',
    fingerprints: item.fingerprints,
    observations: item.observations,
    share_of_fingerprints: item.share_of_fingerprints,
    share_of_observations: item.share_of_observations,
    tint: tintFor(i, false),
  }))

  if (tail.length) {
    const sum = (key) => tail.reduce((acc, item) => acc + (item[key] || 0), 0)
    rows.push({
      id: '__other__',
      label: `${formatInt(tail.length)} further offer lists`,
      fingerprints: sum('fingerprints'),
      observations: sum('observations'),
      share_of_fingerprints: sum('share_of_fingerprints'),
      share_of_observations: sum('share_of_observations'),
      tint: tintFor(0, true),
    })
  }

  return rows
})

function alpnShare(row) {
  return alpnBasis.value === 'observations' ? row.share_of_observations : row.share_of_fingerprints
}

async function load(target, fn) {
  target.value.loading = true
  target.value.error = null
  try {
    const data = await fn()
    target.value.rows = data?.items ?? []
    // Some payloads carry totals alongside `items`; keep the envelope too.
    target.value.data = data ?? null
  } catch (err) {
    target.value.error = err
    target.value.rows = []
    target.value.data = null
  } finally {
    target.value.loading = false
  }
}

onMounted(() => {
  load(promiscuous, () => api.fingerprints({ sort: 'spread', limit: 10 }))
  load(contacted, () => api.snis({ limit: 10 }))
  load(varied, () => api.snis({ sort: 'spread', limit: 8 }))
  load(alpn, () => api.alpn())

  // Corpus size is supplementary; a failure here must not disturb the page.
  api
    .stats()
    .then((data) => {
      stats.value = data
    })
    .catch(() => {
      stats.value = null
    })
})
</script>

<template>
  <div class="home">
    <section class="hero">
      <!-- Decorative only: a ClientHello's own shape, drawn as the sorted
           cipher and extension lists JA4 hashes. aria-hidden because it says
           nothing a screen reader needs — the page states it in words below. -->
      <div class="backdrop" aria-hidden="true">
        <span class="glow"></span>
        <span class="grid"></span>
      </div>

      <h1>TLS fingerprint reputation</h1>
      <p class="lead">
        This is a public, free lookup service for TLS client fingerprints. Give it a
        <strong>JA3</strong> hash or a <strong>JA4</strong> string and it will show you which
        server names (SNIs) that fingerprint has been observed reaching, and how often. Give it a
        domain and it will show you which fingerprints reached it.
      </p>

      <div class="box">
        <LookupInput size="lg" autofocus />

        <p v-if="examples.length" class="tries">
          <span class="tries-label">try</span>
          <RouterLink v-for="ex in examples" :key="ex.id" :to="ex.to" class="chip">
            {{ ex.label }}
          </RouterLink>
        </p>
      </div>

      <dl v-if="statCards.length" class="stats">
        <!-- dt precedes dd for valid markup and sane reading order; the card
             flips them visually so the number leads. -->
        <div v-for="card in statCards" :key="card.key" class="stat">
          <dt class="stat-label">{{ card.label }}</dt>
          <dd class="stat-value">{{ card.value }}</dd>
        </div>
      </dl>
    </section>

    <section class="intro">
      <p>
        There are two things worth reading here, and they are independent of one another.
        <strong>Spread</strong> is how widely a client stack roams: the normalised entropy of the
        domains one fingerprint reaches, <span class="mono">0</span> for always the same domain,
        <span class="mono">1</span> for evenly spread across many unrelated ones.
        <strong>Stability</strong> is whether the stack randomises its own fingerprint. Chrome has
        permuted its ClientHello extension order since version 110, so it emits a new JA3 on
        nearly every connection while its JA4 stays put — which is what JA4 was designed for, and
        why identity here is JA4.
      </p>
      <p>
        Spread on its own is not a verdict. One JA4 aggregates every install of a build, so a
        popular browser carries enormous volume across thousands of domains and scores close to 1
        — the same shape as a scraper. This corpus deliberately stores no per-connection identity,
        which is what makes it publishable, and it therefore cannot tell one scraper reaching 500
        domains from 500 people reaching one each. Stability it can speak to, because that is a
        property of software. Read the two together: a stack that never varies its own hello and
        still reaches many unrelated domains is the interesting case; a randomising one with broad
        reach is just a popular browser.
      </p>
      <p class="links">
        <RouterLink to="/browse">browse the corpus</RouterLink> ·
        <RouterLink to="/docs">API documentation</RouterLink>
      </p>
    </section>

    <section class="section alpn">
      <h2>ALPN offers</h2>
      <p>
        Every ClientHello can advertise which application protocols the client speaks, in the
        client's own order of preference. That order is never normalised here, because the order
        is the signal: <span class="mono">h2, http/1.1</span> and
        <span class="mono">http/1.1, h2</span> are different rows, not two spellings of one. A
        browser offers <span class="mono">h2</span> first, and a client that lists them the other
        way round is not the browser it claims to be.
      </p>

      <div class="toolbar">
        <span class="toolbar-label">share by</span>
        <div class="group" role="group" aria-label="Draw ALPN shares by">
          <button
            v-for="b in ALPN_BASES"
            :key="b.value"
            type="button"
            class="control"
            :aria-pressed="alpnBasis === b.value"
            :disabled="alpn.loading || !!alpn.error"
            @click="alpnBasis = b.value"
          >
            {{ b.label }}
          </button>
        </div>
      </div>

      <!-- A summary of the table beneath it, which states every figure in text.
           aria-hidden so the numbers are not announced twice, and so nothing
           here depends on telling one amber tint from the next. -->
      <div v-if="alpnRows.length" class="bar" aria-hidden="true">
        <span
          v-for="row in alpnRows"
          :key="row.id"
          class="seg"
          :style="{ width: `${alpnShare(row) * 100}%`, background: row.tint }"
          :title="`${row.label} — ${formatShare(alpnShare(row))}`"
        ></span>
      </div>

      <DataTable
        :columns="alpnColumns"
        :rows="alpnRows"
        :loading="alpn.loading"
        :error="alpn.error"
        row-key="id"
        caption="ALPN offer lists, in the order clients advertised them, by share of fingerprints and of observations"
        empty-text="No ALPN offers recorded yet."
      >
        <template #cell-label="{ row }">
          <span class="swatch" :style="{ background: row.tint }" aria-hidden="true"></span>
          {{ row.label }}
        </template>
        <template #cell-fingerprints="{ value }">{{ formatInt(value) }}</template>
        <template #cell-share_of_fingerprints="{ value }">{{ formatShare(value) }}</template>
        <template #cell-observations="{ value }">{{ formatInt(value) }}</template>
        <template #cell-share_of_observations="{ value }">{{ formatShare(value) }}</template>
      </DataTable>

      <p v-if="alpn.data" class="footnote">
        Shares are of {{ formatInt(alpn.data.total_fingerprints) }} distinct fingerprints and
        {{ formatInt(alpn.data.total_observations) }} observations. The two columns disagree, and
        the disagreement is informative: a handful of library fingerprints can account for a large
        share of all connections.
      </p>
      <p class="footnote">
        JA4 cannot express any of this. It keeps only the first and last character of the
        <em>first</em> offered protocol, so <span class="mono">h2</span> and
        <span class="mono">h2, http/1.1</span> reduce to the same two characters — and the order
        of everything after the first is lost entirely.
      </p>
    </section>

    <div class="columns">
      <section class="section">
        <h2>Most promiscuous fingerprints</h2>
        <DataTable
          :columns="fpColumns"
          :rows="promiscuous.rows"
          :loading="promiscuous.loading"
          :error="promiscuous.error"
          :row-key="fpKey"
          caption="Fingerprints with the highest SNI spread"
          empty-text="No fingerprints observed yet."
        >
          <template #cell-ja4="{ row }">
            <RouterLink :to="{ name: 'fingerprint', params: { hash: fpKey(row) } }">
              {{ truncateMiddle(fpKey(row), 14, 6) }}
            </RouterLink>
          </template>
          <template #cell-observations="{ value }">{{ formatInt(value) }}</template>
          <template #cell-unique_snis="{ value }">{{ formatInt(value) }}</template>
          <template #cell-spread="{ value }">
            <SpreadBar :value="value" width="3.5rem" />
          </template>
        </DataTable>
        <p class="footnote">
          Highest spread first — widest reach, which is not by itself a verdict.
          <RouterLink to="/browse">Browse</RouterLink> shows the full list with the stability of
          each.
        </p>
      </section>

      <section class="section">
        <h2>Most contacted SNIs</h2>
        <DataTable
          :columns="sniColumns"
          :rows="contacted.rows"
          :loading="contacted.loading"
          :error="contacted.error"
          row-key="sni"
          caption="Server names with the most observations"
          empty-text="No SNIs observed yet."
        >
          <template #cell-sni="{ value }">
            <RouterLink :to="{ name: 'sni', params: { name: value } }">{{ value }}</RouterLink>
          </template>
          <template #cell-observations="{ value }">{{ formatInt(value) }}</template>
          <template #cell-unique_fingerprints="{ value }">{{ formatInt(value) }}</template>
        </DataTable>
        <p class="footnote">
          <span class="mono">fps</span> is the number of distinct fingerprints seen reaching that
          name.
        </p>
      </section>

      <section class="section">
        <h2>Most varied domains</h2>
        <DataTable
          :columns="variedColumns"
          :rows="varied.rows"
          :loading="varied.loading"
          :error="varied.error"
          row-key="sni"
          caption="Server names reached by the widest mix of fingerprints"
          empty-text="No SNIs observed yet."
        >
          <template #cell-sni="{ value }">
            <RouterLink :to="{ name: 'sni', params: { name: value } }">{{ value }}</RouterLink>
          </template>
          <template #cell-unique_fingerprints="{ value }">{{ formatInt(value) }}</template>
          <template #cell-spread="{ value }">
            <SpreadBar :value="value" width="3.5rem" label="fingerprint spread" />
          </template>
        </DataTable>
        <p class="footnote">
          Spread read the other way: entropy over the fingerprints reaching a name. Near 1.0 means
          many client stacks in near-equal proportion — ordinary on a busy public site, worth a
          look on a login endpoint. Weigh it against volume. See
          <RouterLink :to="{ name: 'browse', query: { tab: 'domains', sort: 'spread' } }"
            >browse domains</RouterLink
          >
          for the full list.
        </p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.hero {
  position: relative;
  padding: var(--sp-8) 0 var(--sp-7);
  text-align: center;
  animation: fadeUp 0.5s ease both;
}

/* The backdrop is absolutely positioned; everything else has to sit above it. */
.hero > *:not(.backdrop) {
  position: relative;
  z-index: 1;
}

/* --- hero backdrop ------------------------------------------------------
   CSS only: no image request, nothing for the CSP to allow, and it costs
   about a kilobyte. Two layers, both painted behind the content and both
   faded out at the edges so the section has no visible boundary. */

.backdrop {
  position: absolute;
  inset: calc(var(--sp-6) * -1) 50% auto;
  width: 100vw;
  height: calc(100% + var(--sp-8));
  transform: translateX(50%);
  z-index: 0;
  pointer-events: none;
  overflow: hidden;
}

/* A single off-centre amber wash. Low enough that it reads as depth rather
   than as a colour — on the light theme it is nearly imperceptible, which is
   correct: that theme has no darkness for it to lift. */
.glow {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(
      60% 70% at 50% 0%,
      color-mix(in srgb, var(--amber) 13%, transparent) 0%,
      transparent 72%
    );
}

/* A fine grid, masked to fade out in every direction. Suggests the tabular
   nature of what the site holds without drawing a table. */
.grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(to right, var(--line) 1px, transparent 1px),
    linear-gradient(to bottom, var(--line) 1px, transparent 1px);
  background-size: 56px 56px;
  opacity: 0.5;
  mask-image: radial-gradient(58% 62% at 50% 34%, #000 0%, transparent 78%);
  -webkit-mask-image: radial-gradient(58% 62% at 50% 34%, #000 0%, transparent 78%);
}

@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) .grid {
    opacity: 0.75;
  }
}

:root[data-theme="light"] .grid {
  opacity: 0.75;
}

h1 {
  font-size: var(--fs-xxl);
  letter-spacing: -0.02em;
  margin-bottom: var(--sp-4);
}

.lead {
  max-width: 46rem;
  margin: 0 auto var(--sp-6);
  color: var(--dim);
  font-size: var(--fs-md);
}

.box {
  max-width: 44rem;
  margin: 0 auto;
  text-align: left;
}

/* Real corpus values, pulled from the tables this page already loads. */
.tries {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin: var(--sp-3) 0 0;
  max-width: none;
}

.tries-label {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--dim);
}

.chip {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--dim);
  text-decoration: none;
  background: var(--panel);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 3px var(--sp-2);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color var(--transition), border-color var(--transition),
    background-color var(--transition);
}

.chip:hover {
  color: var(--link);
  border-color: color-mix(in srgb, var(--amber) 45%, transparent);
  background: var(--amber-soft);
}

/* Number and label only — the API carries no time series to draw against. */
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
  gap: var(--sp-3);
  max-width: 44rem;
  margin: var(--sp-6) auto 0;
  text-align: left;
}

.stat {
  display: flex;
  flex-direction: column-reverse; /* number above label */
  gap: var(--sp-2);
  background: var(--panel);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-card);
  padding: var(--sp-4);
}

.stat-value {
  margin: 0;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: var(--fs-xl);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.1;
}

.stat-label {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--dim);
}

.intro {
  border-top: var(--border-width) solid var(--line);
  padding-top: var(--sp-6);
}

/* --- ALPN distribution -------------------------------------------------- */

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  margin-bottom: var(--sp-4);
}

.toolbar-label {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--dim);
}

.group {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

/* One 100% bar. Segments never wrap and never overflow the page: the widths
   are shares of the same total, so they sum to 1. */
.bar {
  display: flex;
  width: 100%;
  height: 14px;
  margin-bottom: var(--sp-4);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-bar);
  overflow: hidden;
  background: var(--panel-2);
}

/* A hairline between neighbours, so adjacent tints are separable without
   depending on the tints themselves. */
.seg {
  min-width: 1px;
  box-shadow: inset -1px 0 0 var(--panel);
  transition: width var(--transition);
}

.seg:last-child {
  box-shadow: none;
}

/* Ties a table row to its band. Supplementary — the row is already labelled. */
.swatch {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 2px;
  margin-right: var(--sp-2);
  vertical-align: baseline;
  border: var(--border-width) solid var(--line);
}

.links {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  margin-bottom: 0;
}

.columns {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
  gap: var(--sp-6);
  align-items: start;
}

@media (max-width: 40rem) {
  .hero {
    padding-top: var(--sp-5);
  }
  h1 {
    font-size: var(--fs-xl);
  }
}
</style>
