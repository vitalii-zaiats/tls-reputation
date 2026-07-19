<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { api } from '../api.js'
import { formatInt, truncateMiddle } from '../format.js'
import DataTable from '../components/DataTable.vue'
import SpreadBar from '../components/SpreadBar.vue'
import Pagination from '../components/Pagination.vue'

const route = useRoute()
const router = useRouter()

const SORTS = [
  { value: 'observations', label: 'observations' },
  { value: 'unique_snis', label: 'unique snis' },
  { value: 'spread', label: 'spread' },
]
const VALID_SORTS = SORTS.map((s) => s.value)
const PAGE = 50

const items = ref([])
const total = ref(0)
const loading = ref(true)
const error = ref(null)

// Sort and offset live in the URL so a view is linkable and survives reload.
const sort = computed(() =>
  VALID_SORTS.includes(route.query.sort) ? route.query.sort : 'observations',
)
const offset = computed(() => {
  const n = Number.parseInt(route.query.offset, 10)
  return Number.isFinite(n) && n > 0 ? n : 0
})

let requestId = 0

async function load() {
  const id = ++requestId
  loading.value = true
  error.value = null
  try {
    const data = await api.fingerprints({ sort: sort.value, limit: PAGE, offset: offset.value })
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

watch([sort, offset], load, { immediate: true })

function setSort(key) {
  if (!VALID_SORTS.includes(key) || key === sort.value) return
  router.push({ name: 'browse', query: { sort: key } }) // new sort restarts paging
}

function setOffset(next) {
  router.push({
    name: 'browse',
    query: { sort: sort.value, ...(next > 0 ? { offset: next } : {}) },
  })
}

const columns = computed(() => [
  { key: 'ja4', label: 'ja4', mono: true },
  { key: 'ja3', label: 'ja3', mono: true },
  {
    key: 'observations',
    label: 'observations',
    align: 'right',
    sortable: true,
  },
  { key: 'unique_snis', label: 'unique snis', align: 'right', sortable: true },
  { key: 'spread', label: 'spread', align: 'right', sortable: true, width: '10rem' },
])

function fpKey(row) {
  return row.ja4 || row.ja3
}
</script>

<template>
  <div>
    <header class="head">
      <h1>Browse fingerprints</h1>
      <p>
        Every fingerprint in the corpus, newest observations included. Sort by raw volume, by how
        many distinct server names the fingerprint reached, or by spread.
      </p>
    </header>

    <div class="toolbar">
      <span class="label">sort</span>
      <div class="group" role="group" aria-label="Sort fingerprints by">
        <button
          v-for="s in SORTS"
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
      :columns="columns"
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
      <template #cell-observations="{ value }">{{ formatInt(value) }}</template>
      <template #cell-unique_snis="{ value }">{{ formatInt(value) }}</template>
      <template #cell-spread="{ value }">
        <SpreadBar :value="value" width="4rem" />
      </template>
    </DataTable>

    <Pagination
      :offset="offset"
      :limit="PAGE"
      :total="total"
      :disabled="loading"
      @update="setOffset"
    />

    <p class="footnote">
      <strong>Spread</strong> is the normalised Shannon entropy of a fingerprint's SNI
      distribution: 0 = always the same domain, 1 = evenly spread across many unrelated domains.
      High spread on a high-volume fingerprint indicates tooling, not a browser. Low volume makes
      spread unreliable — a fingerprint seen twice, on two domains, scores 1.0 and means nothing.
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
  letter-spacing: 0.06em;
  color: var(--c-fg-muted);
}

.group {
  display: inline-flex;
}

.opt + .opt {
  margin-left: -1px;
}

.opt[aria-pressed="true"] {
  position: relative;
  z-index: 1;
}
</style>
