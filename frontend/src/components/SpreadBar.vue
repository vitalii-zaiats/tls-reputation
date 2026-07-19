<script setup>
/**
 * Spread = normalised Shannon entropy of a distribution. For a fingerprint that
 * is its SNI distribution; for a domain it is the mirror — the distribution of
 * fingerprints reaching it. Same bar, so `label` names which one is meant.
 *
 * Deliberately MONOCHROME. It used to run green -> amber -> red, which encodes
 * a good-to-bad verdict — and spread is not one. The corpus stores no
 * per-connection identity, so it cannot tell one scraper reaching 500 domains
 * from 500 people reaching one each; under the current model a popular browser
 * merges into a single JA4 and sits at the top of the scale. Painting that red
 * would assert exactly the claim the rest of the page retracts. Magnitude is
 * carried by length alone.
 */
import { computed } from 'vue'
import { formatSpread } from '../format.js'

const props = defineProps({
  value: { type: Number, default: null },
  /** Hide the numeric readout when the table already has a spread column. */
  showNumber: { type: Boolean, default: true },
  width: { type: String, default: '6rem' },
  /** Accessible name for the meter. */
  label: { type: String, default: 'SNI spread' },
})

const clamped = computed(() => {
  const n = Number(props.value)
  if (!Number.isFinite(n)) return null
  return Math.min(1, Math.max(0, n))
})

const pct = computed(() => (clamped.value === null ? 0 : clamped.value * 100))
const text = computed(() => formatSpread(props.value))

/** Only "have we got a value at all" — no severity banding. */
const band = computed(() => (clamped.value === null ? 'none' : 'set'))
</script>

<template>
  <span class="spread" :class="`is-${band}`">
    <span v-if="showNumber" class="num">{{ text }}</span>
    <span
      class="track"
      :style="{ width }"
      role="meter"
      aria-valuemin="0"
      aria-valuemax="1"
      :aria-valuenow="clamped ?? undefined"
      :aria-valuetext="`spread ${text}`"
      :aria-label="label"
    >
      <span v-if="clamped !== null" class="fill" :style="{ width: `${pct}%` }"></span>
    </span>
  </span>
</template>

<style scoped>
.spread {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  white-space: nowrap;
}

.num {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.track {
  display: inline-block;
  height: 6px;
  border-radius: var(--radius-bar);
  background: var(--panel-2);
  border: var(--border-width) solid var(--line);
  overflow: hidden;
  vertical-align: middle;
  flex: none;
}

.fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--bar);
}

/* One fill, no severity colour: see the note at the top of this file. */
.is-set {
  --bar: var(--amber);
}

.is-none {
  --bar: var(--line);
}

/* The number stays in --text rather than taking the bar's colour: --amber does
   not reach 4.5:1 as small text on the light theme. */
</style>
