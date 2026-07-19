<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { api, ApiError } from '../api.js'
import { formatDate, formatInt, formatShare, truncateMiddle } from '../format.js'
import DataTable from '../components/DataTable.vue'
import StatGrid from '../components/StatGrid.vue'
import CopyText from '../components/CopyText.vue'
import SpreadBar from '../components/SpreadBar.vue'
import Pagination from '../components/Pagination.vue'

const route = useRoute()

const sni = ref(null)
const loading = ref(true)
const error = ref(null)
const notObserved = ref(false)

const PAGE = 50
const offset = ref(0)

const domain = computed(() => String(route.params.name || ''))

let requestId = 0

async function load() {
  const id = ++requestId
  loading.value = true
  error.value = null
  notObserved.value = false

  try {
    const data = await api.sni(domain.value, { limit: PAGE, offset: offset.value })
    if (id !== requestId) return
    sni.value = data
    document.title = `${data.sni} — tls-reputation.com`
  } catch (err) {
    if (id !== requestId) return
    if (err instanceof ApiError && err.notFound) {
      notObserved.value = true
      sni.value = null
      document.title = `not observed — tls-reputation.com`
    } else {
      error.value = err
    }
  } finally {
    if (id === requestId) loading.value = false
  }
}

// A new domain resets paging; a new offset refetches in place. When the domain
// changes off a later page, resetting the offset is what triggers the reload —
// calling load() here as well would fire two requests for the same view.
watch(domain, () => {
  if (offset.value === 0) load()
  else offset.value = 0
})
watch(offset, load)
load()

const statItems = computed(() => {
  if (!sni.value) return []
  return [
    { key: 'observations', label: 'observations', value: formatInt(sni.value.observations) },
    {
      key: 'unique_fingerprints',
      label: 'unique fingerprints',
      value: formatInt(sni.value.unique_fingerprints),
    },
    {
      key: 'spread',
      label: 'spread',
      value: sni.value.spread,
      title:
        '0 = essentially one client stack reaches this name, 1 = many distinct fingerprints ' +
        'in near-equal proportion. Only meaningful against the observation count.',
    },
    { key: 'first_seen', label: 'first seen', value: formatDate(sni.value.first_seen) },
    { key: 'last_seen', label: 'last seen', value: formatDate(sni.value.last_seen) },
  ]
})

const rows = computed(() => sni.value?.top_fingerprints ?? [])
const total = computed(() => sni.value?.unique_fingerprints ?? 0)

const columns = [
  { key: 'ja4', label: 'ja4', mono: true },
  { key: 'ja3', label: 'ja3', mono: true },
  { key: 'count', label: 'count', align: 'right' },
  { key: 'share', label: 'share', align: 'right' },
]

function fpKey(row) {
  return row.ja4 || row.ja3
}
</script>

<template>
  <div>
    <p v-if="loading" class="status" role="status">loading…</p>

    <p v-else-if="error" class="status status--error" role="alert">{{ error.message }}</p>

    <section v-else-if="notObserved" class="notobserved">
      <h1>Not observed</h1>
      <p class="ident mono">{{ domain }}</p>
      <p>
        No TLS connection to this server name appears in the corpus. Either nothing we observe has
        reached it, or the name is mistyped.
      </p>
      <p class="links">
        <RouterLink to="/">new lookup</RouterLink> ·
        <RouterLink to="/browse">browse the corpus</RouterLink>
      </p>
    </section>

    <template v-else-if="sni">
      <header class="head">
        <h1>SNI</h1>
        <p class="domain">
          <CopyText :value="sni.sni" label="domain" />
        </p>
      </header>

      <section class="section">
        <h2>Statistics</h2>
        <StatGrid :items="statItems">
          <template #value-spread="{ item }">
            <SpreadBar :value="item.value" width="5rem" label="fingerprint spread" />
          </template>
        </StatGrid>
        <p class="footnote">
          <strong>Spread</strong> is the mirror of the fingerprint metric: the normalised Shannon
          entropy of the fingerprints reaching this name. 0 means essentially one client stack; the
          middle range is what ordinary traffic looks like; near 1.0 means many distinct
          fingerprints in near-equal proportion — normal on a busy public site, but on a login or
          API endpoint it is the shape of one actor rotating fingerprints. Read it against the
          observation count: 1.0 over three connections is noise, 1.0 over sixty thousand is a
          finding.
        </p>
      </section>

      <section class="section">
        <h2>Fingerprints observed reaching this name</h2>
        <DataTable
          :columns="columns"
          :rows="rows"
          :row-key="fpKey"
          caption="TLS fingerprints observed connecting to this server name"
          empty-text="No fingerprints recorded for this name."
        >
          <template #cell-ja4="{ row }">
            <RouterLink
              v-if="row.ja4"
              :to="{ name: 'fingerprint', params: { hash: row.ja4 } }"
            >
              {{ truncateMiddle(row.ja4, 14, 6) }}
            </RouterLink>
            <span v-else class="faint">—</span>
          </template>
          <template #cell-ja3="{ row }">
            <RouterLink
              v-if="row.ja3"
              :to="{ name: 'fingerprint', params: { hash: row.ja3 } }"
            >
              {{ truncateMiddle(row.ja3, 12, 6) }}
            </RouterLink>
            <span v-else class="faint">—</span>
          </template>
          <template #cell-count="{ value }">{{ formatInt(value) }}</template>
          <template #cell-share="{ value }">{{ formatShare(value) }}</template>
        </DataTable>
        <Pagination
          :offset="offset"
          :limit="PAGE"
          :total="total"
          :disabled="loading"
          @update="offset = $event"
        />
        <p class="footnote">
          <span class="mono">share</span> is this fingerprint's fraction of all observations of
          this server name. Many distinct fingerprints on a low-traffic name is itself worth a
          look.
        </p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.head h1 {
  margin-bottom: var(--sp-3);
}

.domain {
  font-family: var(--font-mono);
  font-size: var(--fs-md);
  margin: 0;
}

.notobserved h1 {
  margin-bottom: var(--sp-3);
}

.ident {
  font-size: var(--fs-sm);
  color: var(--c-fg-muted);
  overflow-wrap: anywhere;
  margin-bottom: var(--sp-5);
}

.links {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
}
</style>
