<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { api } from '../api.js'
import { formatDate, formatInt, truncateMiddle } from '../format.js'
import DataTable from '../components/DataTable.vue'
import SpreadBar from '../components/SpreadBar.vue'
import StabilityBadge from '../components/StabilityBadge.vue'
import Pagination from '../components/Pagination.vue'

const route = useRoute()
const router = useRouter()

const TABS = [
  { value: 'fingerprints', label: 'fingerprints' },
  { value: 'domains', label: 'domains' },
]
const VALID_TABS = TABS.map((t) => t.value)

// Each mode has its own sort vocabulary; the backend rejects anything else.
const SORTS = {
  // No sort key for stability: the API does not offer one, and it is a class
  // rather than a magnitude, so there is no obvious direction to sort it in.
  fingerprints: [
    { value: 'observations', label: 'observations' },
    { value: 'unique_snis', label: 'unique snis' },
    { value: 'spread', label: 'spread' },
    { value: 'last_seen', label: 'last seen' },
  ],
  domains: [
    { value: 'observations', label: 'observations' },
    { value: 'unique_fingerprints', label: 'unique fingerprints' },
    { value: 'spread', label: 'spread' },
    { value: 'last_seen', label: 'last seen' },
  ],
}
const DEFAULT_SORT = 'observations'
const PAGE = 50

const items = ref([])
const total = ref(0)
const loading = ref(true)
const error = ref(null)

// Mode, sort and offset all live in the URL so a view is linkable and survives
// reload. An unknown value falls back rather than erroring.
const tab = computed(() => (VALID_TABS.includes(route.query.tab) ? route.query.tab : 'fingerprints'))

const sortOptions = computed(() => SORTS[tab.value])

const sort = computed(() => {
  const allowed = sortOptions.value.map((s) => s.value)
  return allowed.includes(route.query.sort) ? route.query.sort : DEFAULT_SORT
})

const offset = computed(() => {
  const n = Number.parseInt(route.query.offset, 10)
  return Number.isFinite(n) && n > 0 ? n : 0
})

const isDomains = computed(() => tab.value === 'domains')

let requestId = 0

async function load() {
  const id = ++requestId
  loading.value = true
  error.value = null
  try {
    const params = { sort: sort.value, limit: PAGE, offset: offset.value }
    const data = isDomains.value ? await api.snis(params) : await api.fingerprints(params)
    if (id !== requestId) return
    items.value = data?.items ?? []
    total.value = data?.total ?? 0
  } catch (err) {
    if (id !== requestId) return
    error.value = err
    items.value = []
    total.value = 0
  } finally {
    if (id === requestId) loading.value = false
  }
}

watch([tab, sort, offset], load, { immediate: true })

// The router's meta title is per-route, so the mode has to set its own.
watch(
  tab,
  (next) => {
    document.title = `browse ${next} — tls-reputation.com`
  },
  { immediate: true },
)

function setTab(next) {
  if (!VALID_TABS.includes(next) || next === tab.value) return
  // Sorts are not shared between modes, so switching starts clean.
  router.push({ name: 'browse', query: { tab: next } })
}

function setSort(key) {
  const allowed = sortOptions.value.map((s) => s.value)
  if (!allowed.includes(key) || key === sort.value) return
  router.push({ name: 'browse', query: { tab: tab.value, sort: key } }) // new sort restarts paging
}

function setOffset(next) {
  router.push({
    name: 'browse',
    query: { tab: tab.value, sort: sort.value, ...(next > 0 ? { offset: next } : {}) },
  })
}

const fpColumns = [
  { key: 'ja4', label: 'ja4', mono: true },
  { key: 'ja3', label: 'ja3', mono: true },
  { key: 'stability', label: 'stability' },
  { key: 'observations', label: 'observations', align: 'right', sortable: true },
  { key: 'unique_snis', label: 'unique snis', align: 'right', sortable: true },
  { key: 'spread', label: 'spread', align: 'right', sortable: true, width: '10rem' },
  { key: 'last_seen', label: 'last seen', align: 'right', sortable: true },
]

const domainColumns = [
  { key: 'sni', label: 'domain', mono: true },
  { key: 'observations', label: 'observations', align: 'right', sortable: true },
  { key: 'unique_fingerprints', label: 'unique fingerprints', align: 'right', sortable: true },
  { key: 'spread', label: 'spread', align: 'right', sortable: true, width: '10rem' },
  { key: 'last_seen', label: 'last seen', align: 'right', sortable: true },
]

function fpKey(row) {
  return row.ja4 || row.ja3
}
</script>

<template>
  <div>
    <header class="head">
      <h1>Browse the corpus</h1>
      <p v-if="!isDomains">
        Every fingerprint in the corpus, keyed on JA4. Sort by raw volume, by how many distinct
        server names the fingerprint reached, by spread, or by recency.
      </p>
      <p v-else>
        Every server name observed in the corpus. Sort by raw volume, by how many distinct
        fingerprints reached the name, by spread, or by recency.
      </p>
    </header>

    <div class="toolbar">
      <span class="label">view</span>
      <div class="group" role="group" aria-label="Browse fingerprints or domains">
        <button
          v-for="t in TABS"
          :key="t.value"
          type="button"
          class="control opt"
          :aria-pressed="tab === t.value"
          @click="setTab(t.value)"
        >
          {{ t.label }}
        </button>
      </div>
    </div>

    <div class="toolbar">
      <span class="label">sort</span>
      <div
        class="group"
        role="group"
        :aria-label="isDomains ? 'Sort domains by' : 'Sort fingerprints by'"
      >
        <button
          v-for="s in sortOptions"
          :key="s.value"
          type="button"
          class="control opt"
          :aria-pressed="sort === s.value"
          @click="setSort(s.value)"
        >
          {{ s.label }}
        </button>
      </div>
    </div>

    <DataTable
      v-if="!isDomains"
      :columns="fpColumns"
      :rows="items"
      :loading="loading"
      :error="error"
      :row-key="fpKey"
      :sort-key="sort"
      caption="All observed TLS fingerprints"
      empty-text="No fingerprints in the corpus yet."
      @sort="setSort"
    >
      <template #cell-ja4="{ row }">
        <RouterLink v-if="row.ja4" :to="{ name: 'fingerprint', params: { hash: row.ja4 } }">
          {{ truncateMiddle(row.ja4, 16, 6) }}
        </RouterLink>
        <span v-else class="faint">—</span>
      </template>
      <template #cell-ja3="{ row }">
        <RouterLink v-if="row.ja3" :to="{ name: 'fingerprint', params: { hash: row.ja3 } }">
          {{ truncateMiddle(row.ja3, 12, 6) }}
        </RouterLink>
        <span v-else class="faint">—</span>
      </template>
      <template #cell-stability="{ value }">
        <StabilityBadge :stability="value" />
      </template>
      <template #cell-observations="{ value }">{{ formatInt(value) }}</template>
      <template #cell-unique_snis="{ value }">{{ formatInt(value) }}</template>
      <template #cell-spread="{ value }">
        <SpreadBar :value="value" width="4rem" />
      </template>
      <template #cell-last_seen="{ value }">{{ formatDate(value) }}</template>
    </DataTable>

    <DataTable
      v-else
      :columns="domainColumns"
      :rows="items"
      :loading="loading"
      :error="error"
      row-key="sni"
      :sort-key="sort"
      caption="All observed server names"
      empty-text="No server names in the corpus yet."
      @sort="setSort"
    >
      <template #cell-sni="{ value }">
        <RouterLink :to="{ name: 'sni', params: { name: value } }">{{ value }}</RouterLink>
      </template>
      <template #cell-observations="{ value }">{{ formatInt(value) }}</template>
      <template #cell-unique_fingerprints="{ value }">{{ formatInt(value) }}</template>
      <template #cell-spread="{ value }">
        <SpreadBar :value="value" width="4rem" label="fingerprint spread" />
      </template>
      <template #cell-last_seen="{ value }">{{ formatDate(value) }}</template>
    </DataTable>

    <Pagination
      :offset="offset"
      :limit="PAGE"
      :total="total"
      :disabled="loading"
      @update="setOffset"
    />

    <template v-if="!isDomains">
      <p class="footnote">
        <strong>Spread</strong> is the normalised Shannon entropy of a fingerprint's SNI
        distribution: 0 = always the same domain, 1 = evenly spread across many unrelated
        domains. It measures reach, and reach alone is not a verdict — one JA4 aggregates every
        install of a build, so a popular browser scores high for the same reason a scraper does.
        Low volume makes it unreliable in the other direction: a fingerprint seen twice, on two
        domains, scores 1.0 and means nothing.
      </p>
      <p class="footnote">
        <strong>Stability</strong> is the second axis and reads independently of the first. It
        says whether the client stack randomises its own fingerprint, which is a property of the
        software rather than of who is running it. A <span class="mono">fixed</span> stack that
        also reaches many unrelated domains is the combination worth opening;
        <span class="mono">randomizing</span> with broad reach is what an ordinary browser looks
        like.
      </p>
      <p class="footnote">
        <span class="mono">ja3</span> is blank whenever more than one JA3 has been seen under a
        JA4. A client that permutes its ClientHello has no single hash, and a representative one
        would never match again — open the fingerprint to see every variant it has emitted.
      </p>
    </template>
    <p v-else class="footnote">
      <strong>Spread</strong> here is the mirror metric: the normalised Shannon entropy of the
      fingerprints reaching a domain. 0 = essentially one client stack; the middle range is what
      ordinary traffic looks like, an uneven mix of real clients; near 1.0 means many distinct
      client stacks in near-equal proportion. Read it against
      <span class="mono">observations</span> and <span class="mono">unique fingerprints</span> —
      1.0 over three connections is noise, 1.0 over sixty thousand is worth a look. What it does
      not tell you is who: with no per-connection identity in the corpus, a high figure is
      equally consistent with a varied audience and with one actor cycling through TLS stacks.
    </p>
  </div>
</template>

<style scoped>
.head {
  margin-bottom: var(--sp-5);
}

.head h1 {
  margin-bottom: var(--sp-3);
}

.head p {
  color: var(--dim);
  margin-bottom: 0;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin-bottom: var(--sp-3);
  flex-wrap: wrap;
}

.label {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--dim);
  /* Keep the two segmented rows left-aligned with each other. */
  min-width: 2.5rem;
}

/* Rounded chips sit side by side rather than sharing a border. */
.group {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}
</style>
