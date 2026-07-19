<script setup>
/**
 * Spread = normalised Shannon entropy of a distribution. For a fingerprint that
 * is its SNI distribution; for a domain it is the mirror — the distribution of
 * fingerprints reaching it. Same bar, so `label` names which one is meant.
 * Rendered as the number plus a plain 1px-bordered bar — no gradient, no glow.
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
</script>

<template>
  <span class="spread">
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
  height: 0.625rem;
  border: var(--border-width) solid var(--c-border-strong);
  background: var(--c-bg);
  vertical-align: middle;
  flex: none;
}

.fill {
  display: block;
  height: 100%;
  background: var(--c-fg);
}
</style>
