<script setup>
import { ref, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '../api.js'
import { formatInt, formatSpread, truncateMiddle } from '../format.js'
import LookupInput from '../components/LookupInput.vue'
import DataTable from '../components/DataTable.vue'
import SpreadBar from '../components/SpreadBar.vue'

const stats = ref(null)

const promiscuous = ref({ rows: [], loading: true, error: null })
const contacted = ref({ rows: [], loading: true, error: null })

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

/** Prefer the JA4 label but fall back to JA3 for pre-JA4 corpus entries. */
function fpKey(row) {
  return row.ja4 || row.ja3
}

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
      <h1>TLS fingerprint reputation</h1>
      <div class="box">
        <LookupInput size="lg" autofocus />
      </div>
      <p v-if="stats" class="corpus nums">
        {{ formatInt(stats.fingerprints) }} fingerprints ·
        {{ formatInt(stats.snis) }} SNIs ·
        {{ formatInt(stats.observations) }} observations
      </p>
    </section>

    <section class="intro">
      <p>
        This is a public, free lookup service for TLS client fingerprints. Give it a
        <strong>JA3</strong> hash or a <strong>JA4</strong> string and it will show you which
        server names (SNIs) that fingerprint has been observed reaching, and how often. Give it a
        domain and it will show you which fingerprints reached it.
      </p>
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
    </div>
  </div>
</template>

<style scoped>
.hero {
  padding: var(--sp-8) 0 var(--sp-6);
  text-align: center;
}

h1 {
  font-size: var(--fs-xxl);
  margin-bottom: var(--sp-6);
}

.box {
  max-width: 44rem;
  margin: 0 auto;
  text-align: left;
}

.corpus {
  font-size: var(--fs-xs);
  color: var(--c-fg-faint);
  margin: var(--sp-4) 0 0;
  max-width: none;
}

.intro {
  border-top: var(--border);
  padding-top: var(--sp-5);
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
