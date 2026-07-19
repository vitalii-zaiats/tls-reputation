<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { api, ApiError } from '../api.js'
import {
  classifyQuery,
  formatInt,
  formatShare,
  formatDate,
  formatVariantCount,
  truncateMiddle,
} from '../format.js'
import DataTable from '../components/DataTable.vue'
import StatGrid from '../components/StatGrid.vue'
import CopyText from '../components/CopyText.vue'
import SpreadBar from '../components/SpreadBar.vue'
import StabilityBadge from '../components/StabilityBadge.vue'
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
        'A measure of reach, not of intent.',
    },
    {
      key: 'stability',
      label: 'stability',
      value: fp.value.stability,
      title:
        'Does this client stack randomise its own fingerprint? A property of the software, ' +
        'and independent of how widely it roams.',
    },
    { key: 'first_seen', label: 'first seen', value: formatDate(fp.value.first_seen) },
    { key: 'last_seen', label: 'last seen', value: formatDate(fp.value.last_seen) },
  ]
})

/* ---- JA3 variants ---- */

const variants = computed(() => fp.value?.ja3_variants ?? null)
const variantItems = computed(() => variants.value?.items ?? [])

/**
 * Only worth a section when there is more than one. A deterministic stack has
 * exactly one JA3 and it is already in the header.
 */
const showVariants = computed(() => (variants.value?.total ?? 0) > 1 && variantItems.value.length > 0)

/** "128+" past the cap: the stored count is a floor, not a total. */
const variantCount = computed(() =>
  formatVariantCount(variants.value?.total, variants.value?.capped),
)

const variantColumns = [
  { key: 'ja3', label: 'ja3', mono: true },
  { key: 'ja3_raw', label: 'ja3 raw', mono: true },
  { key: 'observations', label: 'observations', align: 'right' },
  { key: 'share', label: 'share', align: 'right' },
]

function variantShare(row) {
  const total = fp.value?.observations || 0
  if (!total) return null
  return row.observations / total
}

/**
 * Assembled here rather than as adjacent `v-if` templates: Vue drops
 * whitespace-only text between two elements, which would run the sentences
 * together.
 */
const variantNote = computed(() => {
  const v = variants.value
  if (!v) return ''
  const parts = []
  if (variantItems.value.length < v.total) {
    parts.push(
      `Showing the ${formatInt(variantItems.value.length)} busiest of ${variantCount.value}.`,
    )
  }
  if (v.capped) {
    parts.push(
      'The corpus stops recording new JA3s for a fingerprint once it has seen enough of them ' +
        'to classify it, so that figure is a floor, not a total.',
    )
  }
  return parts.join(' ')
})

/** A deterministic client has exactly one variant, so "one of 1" is avoided. */
const matchedPhrase = computed(() => {
  const total = variants.value?.total ?? 0
  if (total <= 1) {
    return 'It is the only JA3 this JA4 has ever emitted, and no other JA4 has emitted it.'
  }
  return `It is one of ${variantCount.value} JA3s emitted by this JA4, and no other JA4 has emitted it.`
})

/** Same reason: one string, so the optional clauses keep their spacing. */
const stabilityNote = computed(() => {
  const s = fp.value?.stability
  if (!s) return ''
  const parts = []
  if (s.explanation) parts.push(s.explanation)
  if (s.dominant_variant_share != null) {
    parts.push(
      `The busiest single JA3 carries ${formatShare(s.dominant_variant_share)} of this ` +
        "fingerprint's connections.",
    )
  }
  if (s.note) parts.push(s.note)
  return parts.join(' ')
})

/* ---- decoded ClientHello ---- */

const helloSections = computed(() => {
  if (!fp.value) return []
  return [
    { key: 'cipher_suites', label: 'Cipher suites', entries: fp.value.cipher_suites || [] },
    {
      key: 'extensions',
      label: 'Extensions',
      entries: fp.value.extensions || [],
      // Under one JA4 the wire order varies from connection to connection, so
      // presenting one arrival's order as "the" order would invent a fact.
      sorted: fp.value.extensions_sorted === true,
    },
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
      <p v-if="kind === 'ja3'">
        For a JA3 there is a fourth possibility, and it is the likely one. A client that
        permutes its ClientHello emits a new JA3 on every connection, so an unseen JA3 does not
        mean an unseen client. Look the same client up by its <strong>JA4</strong>, which is
        stable across those permutations and is the identity this corpus is keyed on.
      </p>
      <p>
        Absence is not a verdict. A fingerprint missing from this corpus is not thereby
        trustworthy, and one present in it is not thereby hostile.
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
          <dt>JA4</dt>
          <dd><CopyText :value="fp.ja4" label="JA4 string" /></dd>

          <dt>JA4 raw</dt>
          <dd class="wrap">
            <CopyText v-if="fp.ja4_r" :value="fp.ja4_r" label="JA4 raw string" />
            <span v-else class="faint">—</span>
          </dd>

          <dt>JA3</dt>
          <dd class="wrap">
            <CopyText v-if="fp.ja3" :value="fp.ja3" label="JA3 hash" />
            <!-- Null is the answer, not a gap. A "representative" JA3 for a
                 permuting client is a value that never matches again. -->
            <span v-else class="explain">
              no single JA3 — this client permutes its ClientHello, so it emits a different
              hash on almost every connection. Every one we have recorded is listed below.
            </span>
          </dd>

          <dt>JA3 raw</dt>
          <dd class="wrap">
            <CopyText v-if="fp.ja3_raw" :value="fp.ja3_raw" label="JA3 raw string" />
            <span v-else class="faint">—</span>
          </dd>
        </dl>

        <!-- Only the /ja3 route carries this: it says what the hash you typed
             resolved to, and whether that resolution was unambiguous. -->
        <div v-if="fp.matched_ja3" class="matched">
          <p v-if="fp.matched_ja3.canonical" class="matched-line">
            You looked up the JA3
            <span class="mono">{{ truncateMiddle(fp.matched_ja3.ja3, 12, 6) }}</span
            >. {{ matchedPhrase }} JA4 is the identity here; JA3 is a variant of it.
          </p>
          <template v-else>
            <p class="matched-line">
              The JA3 <span class="mono">{{ truncateMiddle(fp.matched_ja3.ja3, 12, 6) }}</span>
              is not unique to one client stack — it has also been observed under the JA4s
              below. This page shows the busiest of them, which may not be the one you meant.
            </p>
            <ul class="alts">
              <li v-for="alt in fp.matched_ja3.also_seen_under" :key="alt.ja4">
                <RouterLink :to="{ name: 'fingerprint', params: { hash: alt.ja4 } }">
                  {{ alt.ja4 }}
                </RouterLink>
                <span class="muted nums">{{ formatInt(alt.observations) }} obs</span>
              </li>
            </ul>
          </template>
        </div>
      </header>

      <section class="section">
        <h2>Statistics</h2>
        <StatGrid :items="statItems">
          <template #value-spread="{ item }">
            <SpreadBar :value="item.value" width="5rem" />
          </template>
          <template #value-stability="{ item }">
            <StabilityBadge :stability="item.value" show-variants />
          </template>
        </StatGrid>
        <p class="footnote">
          <strong>Spread</strong> is the normalised Shannon entropy of this fingerprint's SNI
          distribution: 0 = always the same domain, 1 = evenly spread across many unrelated
          domains. It measures reach, not intent. One JA4 aggregates every install of a build,
          so a popular browser reaches thousands of domains and scores close to 1 for the same
          reason a scraper does. This corpus stores no per-connection identity — that is what
          makes it publishable — so it cannot distinguish one client reaching 500 domains from
          500 clients reaching one each.
        </p>
        <!-- The tooltip on the chip is not reachable by keyboard, so the same
             sentence is stated here in the page. -->
        <p v-if="fp.stability" class="footnote">
          <strong>Stability</strong> is the other axis, and unlike spread it is a claim the
          corpus can support, because it is a property of the software: {{ stabilityNote }}
          Read the two together: a stack that never varies its own hello and still reaches many
          unrelated domains is the interesting case. A randomising stack with broad reach is
          usually just a popular browser.
        </p>
      </section>

      <section v-if="showVariants" class="section">
        <h2>JA3 variants</h2>
        <p class="variants-lead">
          {{ variantCount }} distinct JA3 hashes have been recorded under this JA4. Each is one
          permutation of the same ClientHello.
        </p>
        <DataTable
          :columns="variantColumns"
          :rows="variantItems"
          row-key="ja3"
          caption="The distinct JA3 hashes this fingerprint has emitted"
          empty-text="No JA3 variants recorded."
        >
          <template #cell-ja3="{ value }">
            <RouterLink :to="{ name: 'fingerprint', params: { hash: value } }">
              {{ truncateMiddle(value, 14, 6) }}
            </RouterLink>
          </template>
          <template #cell-ja3_raw="{ value }">
            <span :title="value">{{ truncateMiddle(value, 32, 10) }}</span>
          </template>
          <template #cell-observations="{ value }">{{ formatInt(value) }}</template>
          <template #cell-share="{ row }">{{ formatShare(variantShare(row)) }}</template>
        </DataTable>
        <p class="footnote">
          {{ variantNote }} JA3 hashes the extension list in the order it arrived on the wire;
          JA4 sorts it first. That single difference is why all of these collapse into one JA4.
        </p>
      </section>

      <section class="section">
        <h2>Decoded ClientHello</h2>
        <dl class="kv">
          <dt>TLS version</dt>
          <dd>{{ fp.tls_version || '—' }}</dd>
          <dt>ALPN</dt>
          <dd>{{ fp.alpn?.length ? fp.alpn.join(', ') : '(none offered)' }}</dd>
        </dl>

        <div v-for="sec in helloSections" :key="sec.key" class="hello">
          <h3>
            {{ sec.label }} <span class="muted nums">({{ sec.entries.length }})</span>
            <span v-if="sec.sorted" class="tag">sorted</span>
          </h3>
          <ul v-if="sec.entries.length" class="entries">
            <li v-for="(entry, i) in sec.entries" :key="`${entry.value}-${i}`">
              <span class="hex">{{ entry.value }}</span>
              <span class="name">{{ entry.name || 'unassigned' }}</span>
            </li>
          </ul>
          <p v-else class="status">none advertised.</p>
          <p v-if="sec.sorted" class="footnote">
            Listed in sorted order, which is not the order this client sent them. Under one JA4
            the wire order can vary from connection to connection, and JA4 sorts the list before
            hashing precisely so that it does not matter.
          </p>
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

/* A sentence standing in for a value. Sans-serif so it does not read as a
   fingerprint, and narrow so it does not fight the definition list. */
.explain {
  font-family: var(--font-sans);
  font-size: var(--fs-sm);
  color: var(--dim);
  display: block;
  max-width: var(--measure);
}

.matched {
  margin-top: var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
  background: var(--panel);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-card);
}

.matched-line {
  font-size: var(--fs-sm);
  color: var(--dim);
  margin: 0;
}

.alts {
  list-style: none;
  margin: var(--sp-3) 0 0;
  padding: 0;
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
}

.alts li {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--sp-3);
  padding: var(--sp-1) 0;
  overflow-wrap: anywhere;
}

.variants-lead {
  font-size: var(--fs-sm);
  color: var(--dim);
  margin-bottom: var(--sp-3);
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

/* Says how the list is ordered, without claiming it is the client's order. */
.tag {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  font-weight: 400;
  color: var(--dim);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 1px var(--sp-2);
  margin-left: var(--sp-2);
  vertical-align: 1px;
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
