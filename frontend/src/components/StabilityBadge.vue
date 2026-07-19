<script setup>
/**
 * Stability — does this client stack randomise its own fingerprint?
 *
 * The site's second axis, orthogonal to spread. Spread says how widely a stack
 * roams; stability says whether the stack is deterministic. That is a property
 * of software, which is the only kind of claim this corpus can support: it
 * stores no per-connection identity, so it can never tell one scraper reaching
 * 500 domains from 500 people reaching one each.
 *
 * Neither class is a verdict, so nothing here borrows --green/--red — those
 * belong to the spread scale. The one accent is spent on `fixed`, because a
 * stack that never varies its hello is the one worth a second look.
 *
 * The API returns the same object from /ja3, /ja4 and the list endpoints;
 * `explanation` is only guaranteed on the detail routes, so it is optional.
 */
import { computed } from 'vue'
import { formatVariantCount } from '../format.js'

const props = defineProps({
  /** The API's stability object, or null when a payload carries none. */
  stability: { type: Object, default: null },
  /** Append the JA3 variant count, e.g. "randomizing 128+". */
  showVariants: { type: Boolean, default: false },
})

const LABELS = {
  fixed: 'fixed',
  randomizing: 'randomizing',
  multi_build: 'multi-build',
  unknown: 'unknown',
}

/** A class we don't recognise is not a class we should invent a chip for. */
const kind = computed(() => {
  const c = props.stability?.class
  return c && Object.prototype.hasOwnProperty.call(LABELS, c) ? c : 'unknown'
})

const label = computed(() => LABELS[kind.value])

const variants = computed(() => {
  const s = props.stability
  if (!props.showVariants || !s || s.variants === null || s.variants === undefined) return ''
  return formatVariantCount(s.variants, s.variants_capped)
})

/** List payloads may omit `explanation`; the chip is never left unexplained. */
const FALLBACK = {
  fixed: 'one JA3 across every observed connection: a deterministic stack.',
  randomizing:
    'presents a JA3 never seen before on most connections — it reshuffles its own ClientHello.',
  multi_build:
    'several JA3s under one JA4, but most of them repeat: a few stable builds rather than '
    + 'per-connection randomisation.',
  unknown: 'too few observations to tell a permuting client from a coincidence.',
}

const title = computed(() => props.stability?.explanation || FALLBACK[kind.value])
</script>

<template>
  <span v-if="stability" class="stability" :class="`is-${kind}`" :title="title">
    <span class="name">{{ label }}</span>
    <span v-if="variants" class="variants nums"
      >{{ variants }}<span class="visually-hidden"> JA3 variants</span></span
    >
  </span>
  <span v-else class="faint">—</span>
</template>

<style scoped>
.stability {
  display: inline-flex;
  align-items: baseline;
  gap: var(--sp-2);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  line-height: 1.4;
  padding: 2px var(--sp-2);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-chip);
  white-space: nowrap;
  color: var(--dim);
  cursor: help;
}

/* The accent marks the deterministic stack. Not "good" and not "bad" — just
   the one that is worth opening when it also has reach. */
.is-fixed {
  color: var(--link);
  border-color: color-mix(in srgb, var(--amber) 55%, transparent);
  background: var(--amber-soft);
}

/* Common and unremarkable: every modern browser lands here. */
.is-randomizing {
  color: var(--text);
  background: var(--panel-2);
}

/* Plain text on the page surface — a middle case, deliberately unemphasised. */
.is-multi_build {
  color: var(--text);
}

/* Not a finding, an absence of evidence. Dashed says "not established"
   without relying on colour to say it. */
.is-unknown {
  color: var(--dim);
  border-style: dashed;
}

.variants {
  color: var(--dim);
  font-variant-numeric: tabular-nums;
}
</style>
