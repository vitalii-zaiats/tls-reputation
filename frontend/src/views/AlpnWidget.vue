<script setup>
/**
 * Embeddable ALPN-distribution widget. Chrome-less, fills the iframe, follows
 * the reader's OS light/dark. One measure at a time (share by fingerprint or
 * by observation), so it is a single-series ranked bar chart — one amber fill,
 * length carries magnitude, labels carry identity. No rainbow across the
 * categories; that would be a chart made of noise.
 */
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'
import { formatInt } from '../format.js'

const SITE = 'tls-reputation.com'
const TOP = 8

const stats = ref(null)
const rows = ref([])
const loading = ref(true)
const error = ref(null)

// Which basis drives the bar length. Fingerprints and observations each
// partition the corpus and sum to a whole; domains overlap, so they are shown
// only as a hover figure, never as a bar.
const basis = ref('fingerprints')
const hovered = ref(null)

const BASES = [
  { key: 'fingerprints', label: 'fingerprint', share: 'share_of_fingerprints' },
  { key: 'observations', label: 'observation', share: 'share_of_observations' },
]
const shareKey = computed(() => BASES.find((b) => b.key === basis.value).share)

onMounted(async () => {
  try {
    const [alpn, corpus] = await Promise.all([api.alpn(), api.stats().catch(() => null)])
    stats.value = corpus
    rows.value = (alpn?.items ?? []).map((it) => ({
      label: it.label ?? '(none offered)',
      reversed: isReversed(it.alpn),
      fingerprints: it.fingerprints,
      observations: it.observations,
      unique_snis: it.unique_snis,
      share_of_fingerprints: it.share_of_fingerprints,
      share_of_observations: it.share_of_observations,
    }))
  } catch (err) {
    error.value = err
  } finally {
    loading.value = false
  }
})

/** A client offering http/1.1 before h2 is not the browser it claims to be. */
function isReversed(alpn) {
  const h2 = alpn.indexOf('h2')
  const h1 = alpn.indexOf('http/1.1')
  return h2 > -1 && h1 > -1 && h1 < h2
}

// Ranked by the active basis, with the long tail folded into one row so the
// chart stays legible. The tail is never given a bar of its own colour trick —
// it is just the remainder.
const ranked = computed(() => {
  const sorted = [...rows.value].sort((a, b) => b[shareKey.value] - a[shareKey.value])
  const head = sorted.slice(0, TOP)
  const tail = sorted.slice(TOP)
  const out = head.map((r) => ({ ...r, isTail: false }))
  if (tail.length) {
    out.push({
      label: `${tail.length} more offer lists`,
      isTail: true,
      reversed: false,
      fingerprints: tail.reduce((s, r) => s + r.fingerprints, 0),
      observations: tail.reduce((s, r) => s + r.observations, 0),
      unique_snis: null,
      share_of_fingerprints: tail.reduce((s, r) => s + r.share_of_fingerprints, 0),
      share_of_observations: tail.reduce((s, r) => s + r.share_of_observations, 0),
    })
  }
  return out
})

// Scale bars so the largest fills the track: the shape of the distribution is
// the point, and it genuinely differs between the two bases.
const maxShare = computed(() => Math.max(...ranked.value.map((r) => r[shareKey.value]), 0.0001))

function pct(share) {
  const v = share * 100
  if (v > 0 && v < 0.01) return '<0.01%'
  return `${v.toFixed(v < 10 ? 2 : 1)}%`
}
function width(r) {
  return `${Math.max((r[shareKey.value] / maxShare.value) * 100, 1.5)}%`
}

const statTiles = computed(() => {
  if (!stats.value) return []
  return [
    { label: 'fingerprints', value: formatInt(stats.value.fingerprints) },
    { label: 'server names', value: formatInt(stats.value.snis) },
    { label: 'observations', value: formatInt(stats.value.observations) },
  ]
})
</script>

<template>
  <div class="widget">
    <header class="head">
      <div class="titles">
        <h1>ALPN offers, live</h1>
        <p class="sub">What application protocols clients advertise — in their own order.</p>
      </div>
      <dl v-if="statTiles.length" class="stats">
        <div v-for="t in statTiles" :key="t.label" class="stat">
          <dd>{{ t.value }}</dd>
          <dt>{{ t.label }}</dt>
        </div>
      </dl>
    </header>

    <div class="toolbar">
      <span class="lbl">share by</span>
      <div class="seg" role="group" aria-label="Share basis">
        <button
          v-for="b in BASES"
          :key="b.key"
          type="button"
          class="control opt"
          :aria-pressed="basis === b.key"
          @click="basis = b.key"
        >
          {{ b.label }}
        </button>
      </div>
    </div>

    <p v-if="loading" class="state">loading…</p>
    <p v-else-if="error" class="state">couldn't load the corpus.</p>

    <div v-else class="chart" @mouseleave="hovered = null">
      <div
        v-for="r in ranked"
        :key="r.label"
        class="row"
        :class="{ tail: r.isTail, hot: hovered === r.label }"
        @mouseenter="hovered = r.label"
      >
        <div class="name mono">
          {{ r.label }}
          <span v-if="r.reversed" class="flag" title="http/1.1 offered before h2 — no real browser does this">⚠ reversed</span>
        </div>
        <div class="track">
          <div class="fill" :style="{ width: width(r) }"></div>
        </div>
        <div class="val mono">{{ pct(r[shareKey]) }}</div>

        <div v-if="hovered === r.label" class="tip mono">
          {{ formatInt(r.fingerprints) }} fps · {{ formatInt(r.observations) }} obs<template v-if="r.unique_snis !== null"> · {{ formatInt(r.unique_snis) }} domains</template>
        </div>
      </div>
    </div>

    <footer class="foot">
      <p class="note">
        Order is the signal: <span class="mono">h2, http/1.1</span> and
        <span class="mono">http/1.1, h2</span> are different clients. The two bases disagree —
        a few library fingerprints carry a large share of connections.
      </p>
      <a class="link mono" :href="`https://${SITE}`" target="_blank" rel="noopener">{{ SITE }} ↗</a>
    </footer>
  </div>
</template>

<style scoped>
.widget {
  box-sizing: border-box;
  min-height: 100vh;
  padding: clamp(16px, 3vw, 26px);
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--sp-4);
  flex-wrap: wrap;
}
.titles h1 {
  margin: 0;
  font-size: var(--fs-lg);
  letter-spacing: -0.01em;
}
.sub {
  margin: 4px 0 0;
  color: var(--dim);
  font-size: var(--fs-sm);
  max-width: 46ch;
}
.stats {
  display: flex;
  gap: var(--sp-2);
  margin: 0;
}
.stat {
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-card);
  padding: var(--sp-2) var(--sp-3);
  background: var(--panel);
  text-align: right;
}
.stat dd {
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--fs-md);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.stat dt {
  margin-top: 2px;
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--dim);
}

.toolbar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.lbl {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--dim);
}
.seg {
  display: inline-flex;
  gap: var(--sp-2);
}

.state {
  color: var(--dim);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
}

.chart {
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.row {
  display: grid;
  grid-template-columns: minmax(0, 15rem) 1fr 4.5rem;
  align-items: center;
  gap: var(--sp-3);
  padding: 5px var(--sp-2);
  border-radius: var(--radius-chip);
  position: relative;
}
.row.hot {
  background: var(--panel-2);
}
.name {
  font-size: var(--fs-sm);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.row.tail .name {
  color: var(--dim);
}
.flag {
  font-family: var(--font-sans);
  font-size: var(--fs-xs);
  color: var(--amber);
  white-space: nowrap;
}
.track {
  height: 12px;
  background: var(--panel-2);
  border-radius: 3px;
  overflow: hidden;
}
/* One fill, one hue: length is the magnitude, not colour. Rounded data-end. */
.fill {
  height: 100%;
  background: var(--amber);
  border-radius: 0 3px 3px 0;
  transition: width 0.35s cubic-bezier(0.22, 1, 0.36, 1);
}
.row.tail .fill {
  background: var(--faint);
}
.val {
  text-align: right;
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  color: var(--text);
}
.tip {
  position: absolute;
  top: -6px;
  left: 15.5rem;
  transform: translateY(-100%);
  background: var(--text);
  color: var(--bg);
  font-size: var(--fs-xs);
  padding: 4px 8px;
  border-radius: 6px;
  white-space: nowrap;
  pointer-events: none;
  z-index: 2;
}

.foot {
  margin-top: auto;
  padding-top: var(--sp-3);
  border-top: var(--border-width) solid var(--line);
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: var(--sp-4);
  flex-wrap: wrap;
}
.note {
  margin: 0;
  color: var(--dim);
  font-size: var(--fs-xs);
  line-height: 1.5;
  max-width: 60ch;
}
.note .mono {
  color: var(--text);
}
.link {
  font-size: var(--fs-xs);
  color: var(--link);
  white-space: nowrap;
}

@media (max-width: 34rem) {
  .row {
    grid-template-columns: minmax(0, 9rem) 1fr 3.5rem;
  }
  .tip {
    left: 0;
  }
}
</style>
