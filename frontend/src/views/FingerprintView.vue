<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { api, ApiError } from '../api.js'
import { classifyQuery, formatInt, formatShare, formatDate, tlsEntryLabel } from '../format.js'
import DataTable from '../components/DataTable.vue'
import StatGrid from '../components/StatGrid.vue'
import CopyText from '../components/CopyText.vue'
import SpreadBar from '../components/SpreadBar.vue'
import Pagination from '../components/Pagination.vue'

const route = useRoute()

const fp = ref(null)
const loading = ref(true)
const error = ref(null)
/** True when the API says 404 — a valid answer, not a fault. */
const notObserved = ref(false)

const hash = computed(() => String(route.params.hash || ''))
const kind = computed(() => classifyQuery(hash.value))

const PAGE = 50
const offset = ref(0)

let requestId = 0

async function load() {
  const id = ++requestId
  loading.value = true
  error.value = null
  notObserved.value = false
  fp.value = null
  offset.value = 0

  // Anything that isn't a well-formed JA3 or JA4 can't be in the corpus, so
  // answer locally rather than sending the backend a request it will reject.
  const id_ = hash.value
  if (kind.value !== 'ja3' && kind.value !== 'ja4') {
    loading.value = false
    notObserved.value = true
    document.title = 'not observed — tls-reputation.com'
    return
  }

  try {
    const data = kind.value === 'ja3' ? await api.ja3(id_) : await api.ja4(id_)
    if (id !== requestId) return // superseded by a newer navigation
    fp.value = data
    document.title = `${data.ja4 || data.ja3} — tls-reputation.com`
  } catch (err) {
    if (id !== requestId) return
    if (err instanceof ApiError && err.notFound) {
      notObserved.value = true
      document.title = `not observed — tls-reputation.com`
    } else {
      error.value = err
    }
  } finally {
    if (id === requestId) loading.value = false
  }
}

watch(hash, load, { immediate: true })

/* ---- stats row ---- */

const statItems = computed(() => {
  if (!fp.value) return []
  return [
    { key: 'observations', label: 'observations', value: formatInt(fp.value.observations) },
    { key: 'unique_snis', label: 'unique snis', value: formatInt(fp.value.unique_snis) },
    {
      key: 'spread',
      label: 'spread',
      value: fp.value.spread,
      title:
        '0 = always the same domain, 1 = evenly spread across many unrelated domains. ' +
        'High spread on a high-volume fingerprint indicates tooling, not a browser.',
    },
    { key: 'first_seen', label: 'first seen', value: formatDate(fp.value.first_seen) },
    { key: 'last_seen', label: 'last seen', value: formatDate(fp.value.last_seen) },
  ]
})

/* ---- decoded ClientHello ---- */

const helloSections = computed(() => {
  if (!fp.value) return []
  return [
    { key: 'cipher_suites', label: 'Cipher suites', entries: fp.value.cipher_suites || [] },
    { key: 'extensions', label: 'Extensions', entries: fp.value.extensions || [] },
    { key: 'curves', label: 'Supported groups', entries: fp.value.curves || [] },
    { key: 'sig_algs', label: 'Signature algorithms', entries: fp.value.sig_algs || [] },
  ]
})

/* ---- SNI table ---- */

// The fingerprint payload carries the full SNI list, so paging is done here.
const allSnis = computed(() => fp.value?.top_snis ?? [])
const pageSnis = computed(() => allSnis.value.slice(offset.value, offset.value + PAGE))

const sniColumns = [
  { key: 'sni', label: 'sni', mono: true },
  { key: 'count', label: 'count', align: 'right' },
  { key: 'share', label: 'share', align: 'right' },
]
</script>

<template>
  <div>
    <p v-if="loading" class="status" role="status">loading…</p>

    <p v-else-if="error" class="status status--error" role="alert">
      {{ error.message }}
    </p>

    <!-- A fingerprint we have never seen is a legitimate result. -->
    <section v-else-if="notObserved" class="notobserved">
      <h1>Not observed</h1>
      <p class="ident mono">{{ hash }}</p>
      <p>
        This {{ kind === 'ja3' ? 'JA3' : kind === 'ja4' ? 'JA4' : 'value' }} does not appear
        anywhere in the corpus. That means one of three things: it is a well-formed fingerprint
        that simply has not reached our sensors, the value is mistyped, or it is not a fingerprint
        at all.
      </p>
      <p>
        Absence is not a verdict. A fingerprint missing from this corpus is not thereby
        trustworthy, and one present in it is not thereby hostile — read the spread.
      </p>
      <p class="links">
        <RouterLink to="/">new lookup</RouterLink> ·
        <RouterLink to="/browse">browse the corpus</RouterLink>
      </p>
    </section>

    <template v-else-if="fp">
      <header class="head">
        <h1>Fingerprint</h1>
        <dl class="kv">
          <dt>JA3</dt>
          <dd><CopyText :value="fp.ja3" label="JA3 hash" /></dd>

          <dt>JA3 raw</dt>
          <dd class="wrap">
            <CopyText v-if="fp.ja3_raw" :value="fp.ja3_raw" label="JA3 raw string" />
            <span v-else class="faint">—</span>
          </dd>

          <dt>JA4</dt>
          <dd><CopyText :value="fp.ja4" label="JA4 string" /></dd>

          <dt>JA4 raw</dt>
          <dd class="wrap">
            <CopyText v-if="fp.ja4_r" :value="fp.ja4_r" label="JA4 raw string" />
            <span v-else class="faint">—</span>
          </dd>
        </dl>
      </header>

      <section class="section">
        <h2>Statistics</h2>
        <StatGrid :items="statItems">
          <template #value-spread="{ item }">
            <SpreadBar :value="item.value" width="5rem" />
          </template>
        </StatGrid>
        <p class="footnote">
          <strong>Spread</strong> is the normalised Shannon entropy of this fingerprint's SNI
          distribution. 0 = always the same domain, 1 = evenly spread across many unrelated
          domains. High spread on a high-volume fingerprint indicates tooling, not a browser.
        </p>
      </section>

      <section class="section">
        <h2>Decoded ClientHello</h2>
        <dl class="kv">
          <dt>TLS version</dt>
          <dd>{{ fp.tls_version || '—' }}</dd>
          <dt>ALPN</dt>
          <dd>{{ fp.alpn?.length ? fp.alpn.join(', ') : '—' }}</dd>
        </dl>

        <div v-for="sec in helloSections" :key="sec.key" class="hello">
          <h3>{{ sec.label }} <span class="muted nums">({{ sec.entries.length }})</span></h3>
          <ul v-if="sec.entries.length" class="entries">
            <li v-for="(entry, i) in sec.entries" :key="`${entry.value}-${i}`">
              <span class="hex">{{ entry.value }}</span>
              <span class="name">{{ entry.name || 'unassigned' }}</span>
            </li>
          </ul>
          <p v-else class="status">none advertised.</p>
        </div>
      </section>

      <section class="section">
        <h2>SNIs contacted</h2>
        <DataTable
          :columns="sniColumns"
          :rows="pageSnis"
          row-key="sni"
          caption="Server names this fingerprint has been observed reaching"
          empty-text="No SNIs recorded for this fingerprint."
        >
          <template #cell-sni="{ value }">
            <RouterLink :to="{ name: 'sni', params: { name: value } }">{{ value }}</RouterLink>
          </template>
          <template #cell-count="{ value }">{{ formatInt(value) }}</template>
          <template #cell-share="{ value }">{{ formatShare(value) }}</template>
        </DataTable>
        <Pagination
          v-if="allSnis.length > PAGE"
          :offset="offset"
          :limit="PAGE"
          :total="allSnis.length"
          @update="offset = $event"
        />
        <p v-if="fp.unique_snis > allSnis.length" class="footnote">
          Showing the top {{ formatInt(allSnis.length) }} of
          {{ formatInt(fp.unique_snis) }} unique SNIs. <span class="mono">share</span> is this
          SNI's fraction of all observations of this fingerprint.
        </p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.head h1 {
  margin-bottom: var(--sp-4);
}

.wrap {
  overflow-wrap: anywhere;
}

.hello {
  margin-top: var(--sp-5);
}

.hello h3 {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-weight: 600;
  margin-bottom: var(--sp-2);
}

.entries {
  list-style: none;
  margin: 0;
  padding: 0;
  background: var(--panel);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-panel);
  overflow: hidden; /* let the radius clip the first and last rows */
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(22rem, 1fr));
}

.entries li {
  display: flex;
  gap: var(--sp-3);
  padding: var(--sp-2) var(--sp-4);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  border-bottom: var(--border-width) solid var(--line);
  min-width: 0;
}

.hex {
  color: var(--dim);
  flex: none;
  width: 5rem;
  font-variant-numeric: tabular-nums;
}

.name {
  overflow-wrap: anywhere;
}

.notobserved h1 {
  margin-bottom: var(--sp-3);
}

.ident {
  font-size: var(--fs-sm);
  color: var(--dim);
  overflow-wrap: anywhere;
  margin-bottom: var(--sp-5);
}

.links {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
}
</style>
