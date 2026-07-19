<script setup>
/**
 * Spread = normalised Shannon entropy of a distribution. For a fingerprint that
 * is its SNI distribution; for a domain it is the mirror — the distribution of
 * fingerprints reaching it. Same bar, so `label` names which one is meant.
 * Rendered as the number plus a plain track — no gradient, no glow. The fill is
 * coloured by the value itself (<0.4 green, <0.7 amber, else red), which is the
 * only place --green and --red are used in the UI.
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

/** Low spread reads as normal, high spread as worth a look. */
const band = computed(() => {
  if (clamped.value === null) return 'none'
  if (clamped.value < 0.4) return 'low'
  if (clamped.value < 0.7) return 'mid'
  return 'high'
})
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

/* The spread scale — the one place --green and --red appear. */
.is-low {
  --bar: var(--green);
}
.is-mid {
  --bar: var(--amber);
}
.is-high {
  --bar: var(--red);
}
.is-none {
  --bar: var(--faint);
}

/* The bar carries the colour; the number stays in --text so it is always
   legible. --amber and --green do not reach 4.5:1 as small text on light. */
</style>
