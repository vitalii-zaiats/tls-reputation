<script setup>
import { computed, ref, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '../api.js'
import { formatInt, truncateMiddle } from '../format.js'
import LookupInput from '../components/LookupInput.vue'
import DataTable from '../components/DataTable.vue'
import SpreadBar from '../components/SpreadBar.vue'

const stats = ref(null)

const promiscuous = ref({ rows: [], loading: true, error: null })
const contacted = ref({ rows: [], loading: true, error: null })
const varied = ref({ rows: [], loading: true, error: null })

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

async function load(target, fn) {
  target.value.loading = true
  target.value.error = null
  try {
    const data = await fn()
    target.value.rows = data?.items ?? []
  } catch (err) {
    target.value.error = err
    target.value.rows = []
  } finally {
    target.value.loading = false
  }
}

onMounted(() => {
  load(promiscuous, () => api.fingerprints({ sort: 'spread', limit: 10 }))
  load(contacted, () => api.snis({ limit: 10 }))
  load(varied, () => api.snis({ sort: 'spread', limit: 8 }))

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
      <p class="eyebrow">public · free · read-only</p>
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
        The signal worth reading is <strong>spread</strong>. A real browser on a real machine
        produces a fingerprint that touches a handful of related domains. A scraper, a proxy pool
        or an attack tool produces one fingerprint that touches hundreds of unrelated ones. Spread
        is the normalised entropy of that distribution: <span class="mono">0</span> means always
        the same domain, <span class="mono">1</span> means evenly spread across many unrelated
        domains. High spread on a high-volume fingerprint indicates tooling, not a browser.
      </p>
      <p class="links">
        <RouterLink to="/browse">browse the corpus</RouterLink> ·
        <RouterLink to="/docs">API documentation</RouterLink>
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
          Highest spread first. See <RouterLink to="/browse">browse</RouterLink> for the full list.
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
          many clients in near-equal proportion — ordinary on a busy public site, telling on a
          login endpoint. Weigh it against volume. See
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
  padding: var(--sp-8) 0 var(--sp-7);
  text-align: center;
  animation: fadeUp 0.5s ease both;
}

.eyebrow {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.18em;
  color: var(--link);
  margin: 0 0 var(--sp-4);
  max-width: none;
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
