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

/**
 * Only the active basis's two count columns are shown. Fingerprints and
 * observations disagree by design, but a reader compares within one basis at a
 * time; showing both doubles the table's width for no gain and pushes it into a
 * sideways scroll. The toggle picks which pair appears; the bar and the
 * composition already follow the same toggle.
 */
const alpnColumns = computed(() => {
  const byObs = alpnBasis.value === 'observations'
  return [
    { key: 'label', label: 'alpn offer', mono: true },
    { key: 'composition', label: 'clients', width: '16rem' },
    byObs
      ? { key: 'observations', label: 'observations', align: 'right' }
      : { key: 'fingerprints', label: 'fingerprints', align: 'right' },
    byObs
      ? { key: 'share_of_observations', label: 'share of obs', align: 'right' }
      : { key: 'share_of_fingerprints', label: 'share of fps', align: 'right' },
    { key: 'unique_snis', label: 'domains', align: 'right' },
    { key: 'share_of_snis', label: 'of all domains', align: 'right' },
  ]
})

/**
 * Fold a set of ALPN offers' client splits into one. Used for the grouped
 * tail: several offers become a row, so their per-client weights are summed by
 * client name. Named clients come out biggest-first, the anonymous bucket last,
 * matching the order the API already returns per offer.
 */
function mergeClients(items) {
  const acc = new Map()
  for (const it of items) {
    for (const c of it.clients ?? []) {
      const key = c.known ? c.name : '__anon__'
      const prev = acc.get(key)
      if (prev) {
        prev.fingerprints += c.fingerprints
        prev.observations += c.observations
      } else {
        acc.set(key, { ...c })
      }
    }
  }
  const all = [...acc.values()]
  const named = all
    .filter((c) => c.known)
    .sort((a, b) => b.fingerprints - a.fingerprints || b.observations - a.observations)
  return [...named, ...all.filter((c) => !c.known)]
}

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
    unique_snis: item.unique_snis,
    share_of_snis: item.share_of_snis,
    // The per-client split of this offer, and how much of it the catalog names.
    clients: item.clients ?? [],
    known_fingerprints: item.known_fingerprints ?? 0,
    known_observations: item.known_observations ?? 0,
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
      // Domain counts overlap between offer lists, so they cannot be summed:
      // adding them would double-count every domain more than one kind of
      // client reached. null renders as an em dash.
      unique_snis: null,
      share_of_snis: null,
      // The client split is additive, so the tail's is the merge of its offers'.
      clients: mergeClients(tail),
      known_fingerprints: sum('known_fingerprints'),
      known_observations: sum('known_observations'),
      tint: tintFor(0, true),
    })
  }

  return rows
})

/**
 * Only fingerprints and observations can drive the bar. Domain counts overlap
 * — one domain reached by both a browser and a library is counted under both —
 * so they sum past the total and are not a share of a whole. Drawing them as
 * segments of a 100% bar would be a lie about the data.
 */
function alpnShare(row) {
  const value =
    alpnBasis.value === 'observations' ? row.share_of_observations : row.share_of_fingerprints
  return Number.isFinite(value) ? value : 0
}

/* -------------------------------------------------------------------------
   Per-ALPN client composition
   Each row carries how its own fingerprints (or observations) split across
   the clients the catalog can name, plus one anonymous remainder. Drawn as a
   stacked bar: named clients in amber, the unnamed rest in a neutral, so the
   amber fraction reads at a glance as "how much of this offer we can identify"
   — and it answers the known/not-known question per ALPN offer directly.
   ------------------------------------------------------------------------- */

/** The measure the split is taken on follows the same toggle as the bar. */
const compKey = computed(() => (alpnBasis.value === 'observations' ? 'observations' : 'fingerprints'))

/**
 * A short amber ramp for the named clients within a row, brightest first. This
 * is a rank tint inside one row, not a cross-row identity — a row rarely holds
 * more than three named clients, and the tooltip carries the actual name.
 */
const NAMED_TINTS = [90, 66, 48, 36, 28, 22]
function namedTint(i) {
  return `color-mix(in srgb, var(--amber) ${NAMED_TINTS[i] ?? 16}%, var(--panel-2))`
}

/** Segments for one row's bar, widths as a fraction of that row's own total. */
function compSegments(row) {
  const key = compKey.value
  const total = row[key] || 0
  if (!total) return []
  let named = -1
  return (row.clients ?? []).map((c) => {
    const value = c[key] || 0
    const share = value / total
    return {
      id: c.known ? c.name : '(unrecognised)',
      name: c.known ? c.name : 'unrecognised',
      known: c.known,
      value,
      share,
      width: `${(share * 100).toFixed(3)}%`,
      tint: c.known ? namedTint(++named) : 'var(--line-strong)',
    }
  })
}

/** How much of this row the catalog can put a name to, on the active measure. */
function namedShare(row) {
  const total = row[compKey.value] || 0
  if (!total) return 0
  const known =
    (compKey.value === 'observations' ? row.known_observations : row.known_fingerprints) || 0
  return known / total
}

/** The caption under a row's bar: the leading named clients and the named share. */
function compCaption(row) {
  const named = (row.clients ?? []).filter((c) => c.known)
  if (!named.length) return 'unidentified'
  const shown = named.slice(0, 2).map((c) => c.name)
  const extra = named.length - shown.length
  return `${shown.join(', ')}${extra > 0 ? ` +${extra}` : ''} · ${formatShare(namedShare(row))} named`
}

/** Non-visual description of the whole bar, for the aria-label. */
function compAria(row) {
  const segs = compSegments(row)
  if (!segs.length) return 'no client data'
  return 'clients: ' + segs.map((s) => `${formatShare(s.share)} ${s.name}`).join(', ')
}

/** Corpus-wide named share, for the section footnote. */
const corpusNamed = computed(() => {
  const d = alpn.value.data
  if (!d) return null
  const total = alpnBasis.value === 'observations' ? d.total_observations : d.total_fingerprints
  const known = alpnBasis.value === 'observations' ? d.known_observations : d.known_fingerprints
  if (!total || known == null) return null
  return known / total
})

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

    <section class="section">
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
        <!-- What this offer is made of, by client. Named clients in amber, the
             rest of the offer in a neutral: the amber fraction is how much of
             the offer the catalog can identify. Widths follow the same
             fingerprint/observation toggle as the summary bar. -->
        <template #cell-composition="{ row }">
          <div class="comp">
            <div class="comp-bar" role="img" :aria-label="compAria(row)">
              <span
                v-for="seg in compSegments(row)"
                :key="seg.id"
                class="comp-seg"
                :class="{ anon: !seg.known }"
                :style="{ width: seg.width, background: seg.tint }"
                :title="`${seg.name} — ${formatShare(seg.share)} of this offer (${formatInt(seg.value)} ${compKey})`"
              ></span>
            </div>
            <span class="comp-cap" :class="{ none: !row.known_fingerprints }">{{
              compCaption(row)
            }}</span>
          </div>
        </template>
        <template #cell-fingerprints="{ value }">{{ formatInt(value) }}</template>
        <template #cell-share_of_fingerprints="{ value }">{{ formatShare(value) }}</template>
        <template #cell-observations="{ value }">{{ formatInt(value) }}</template>
        <template #cell-share_of_observations="{ value }">{{ formatShare(value) }}</template>
        <template #cell-unique_snis="{ value }">
          {{ value === null ? '—' : formatInt(value) }}
        </template>
        <template #cell-share_of_snis="{ value }">
          {{ value === null ? '—' : formatShare(value) }}
        </template>
      </DataTable>

      <p v-if="alpn.data" class="footnote">
        Shares are of {{ formatInt(alpn.data.total_fingerprints) }} distinct fingerprints and
        {{ formatInt(alpn.data.total_observations) }} observations. The two disagree, and the
        disagreement is informative: a handful of library fingerprints can account for a large
        share of all connections.
      </p>
      <p class="footnote">
        <strong>clients</strong> breaks each offer down by who sent it. The amber runs are the
        clients the ground-truth catalog can name — <span class="mono">Python requests</span>,
        <span class="mono">Go net/http</span>, a browser — and the neutral remainder is every
        fingerprint no catalogued build has reproduced yet. So the amber fraction is how much of
        an offer we can put a name to; hover a run for the client and its share.<template
          v-if="corpusNamed !== null"
        >
          Across the corpus that is {{ formatShare(corpusNamed) }} of
          {{ alpnBasis === 'observations' ? 'connections' : 'fingerprints' }} — the catalog is new
          and small, so most of the corpus is still anonymous.</template
        >
      </p>
      <p v-if="alpn.data" class="footnote">
        <strong>domains</strong> counts the distinct server names each offer list was seen
        reaching, against {{ formatInt(alpn.data.total_snis) }} in the corpus. Unlike the other
        two, these <em>overlap</em>: a domain reached by both a browser and a library is counted
        under both, so the column sums past 100%. That is why the bar above can only be drawn per
        fingerprint or per observation — those partition the corpus, and this does not.
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

/* Full-bleed and centred on the hero. The left edge is pinned to the hero's
   horizontal centre, then pulled back by half its own (viewport-wide) width —
   translateX must be NEGATIVE, or the whole layer slides a half-width off to
   the right and the grid disappears past the edge. */
.backdrop {
  position: absolute;
  top: calc(var(--sp-6) * -1);
  bottom: auto;
  left: 50%;
  width: 100vw;
  height: calc(100% + var(--sp-8));
  transform: translateX(-50%);
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
      62% 72% at 50% 0%,
      color-mix(in srgb, var(--amber) 22%, transparent) 0%,
      transparent 72%
    );
}

/* A fine grid, masked to fade out in every direction. Suggests the tabular
   nature of what the site holds without drawing a table. Drawn in the stronger
   line token so it reads as texture rather than disappearing into the surface;
   the mask still keeps it to a soft patch behind the hero. */
.grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(to right, var(--line-strong) 1px, transparent 1px),
    linear-gradient(to bottom, var(--line-strong) 1px, transparent 1px);
  background-size: 56px 56px;
  opacity: 0.7;
  mask-image: radial-gradient(60% 66% at 50% 32%, #000 0%, transparent 82%);
  -webkit-mask-image: radial-gradient(60% 66% at 50% 32%, #000 0%, transparent 82%);
}

/* Light theme: the dark-tuned layers all but vanish on a pale surface — the
   grid lines sit at nearly the background's own lightness and the amber wash
   has no darkness to lift. Both are lifted here: the grid onto a darker line,
   the glow onto a stronger amber, enough to read as texture without becoming a
   pattern. Written twice — once for an explicit light toggle, once for OS-light
   with no explicit choice. */
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) .grid {
    background-image:
      linear-gradient(to right, var(--line-strong) 1px, transparent 1px),
      linear-gradient(to bottom, var(--line-strong) 1px, transparent 1px);
    opacity: 0.8;
  }
  :root:not([data-theme="dark"]) .glow {
    background: radial-gradient(
      60% 70% at 50% 0%,
      color-mix(in srgb, var(--amber) 15%, transparent) 0%,
      transparent 72%
    );
  }
}

:root[data-theme="light"] .grid {
  background-image:
    linear-gradient(to right, var(--line-strong) 1px, transparent 1px),
    linear-gradient(to bottom, var(--line-strong) 1px, transparent 1px);
  opacity: 0.8;
}
:root[data-theme="light"] .glow {
  background: radial-gradient(
    60% 70% at 50% 0%,
    color-mix(in srgb, var(--amber) 15%, transparent) 0%,
    transparent 72%
  );
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

/* Per-row client composition: the stacked bar plus its caption. Kept narrow so
   the numeric columns still fit; the cell overrides the table's nowrap so the
   caption can sit under the bar. */
/* Fixed width, not just a min: the caption is nowrap, so without a ceiling it
   would stretch the cell to its full text and balloon the whole table into a
   sideways scroll. At 15rem the caption ellipsises and the column holds. */
.comp {
  display: flex;
  flex-direction: column;
  gap: 5px;
  width: 15rem;
  max-width: 15rem;
  white-space: normal;
}
.comp-bar {
  display: flex;
  width: 100%;
  height: 12px;
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-bar);
  overflow: hidden;
  background: var(--panel-2);
}
/* Same hairline trick as the summary bar, so neighbours are separable without
   leaning on the tints. A named run keeps a floor width so a client that is a
   sliver of the offer is still visible and hoverable; the caption states the
   true share, so the floor doesn't overstate anything. */
.comp-seg {
  min-width: 1px;
  box-shadow: inset -1px 0 0 var(--panel);
  transition: width var(--transition);
}
.comp-seg:not(.anon) {
  min-width: 3px;
}
.comp-seg:last-child {
  box-shadow: none;
}
.comp-cap {
  font-size: var(--fs-xs);
  color: var(--dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.comp-cap.none {
  color: var(--faint);
  font-style: italic;
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
