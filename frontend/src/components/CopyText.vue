<script setup>
/**
 * Monospace value with click-to-copy. The whole thing is one button so the
 * hit target matches the visible text; state feedback is a text swap, not an icon.
 */
import { ref, onBeforeUnmount } from 'vue'

const props = defineProps({
  value: { type: String, required: true },
  /** Optional shortened display text; the full `value` is still what gets copied. */
  display: { type: String, default: '' },
  /** Announced to screen readers, e.g. "JA3 fingerprint". */
  label: { type: String, default: 'value' },
})

const state = ref('idle') // 'idle' | 'copied' | 'failed'
let timer = null

async function copy() {
  if (timer) clearTimeout(timer)
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(props.value)
    } else {
      legacyCopy(props.value)
    }
    state.value = 'copied'
  } catch (e) {
    state.value = 'failed'
  }
  timer = setTimeout(() => {
    state.value = 'idle'
  }, 1200)
}

/** Fallback for non-secure contexts, where the async clipboard API is unavailable. */
function legacyCopy(text) {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.setAttribute('readonly', '')
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  const ok = document.execCommand('copy')
  document.body.removeChild(ta)
  if (!ok) throw new Error('copy command rejected')
}

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <span class="copytext">
    <button
      type="button"
      class="value"
      :aria-label="`Copy ${label} to clipboard`"
      :title="value"
      @click="copy"
    >
      {{ display || value }}
    </button>
    <span class="hint" aria-hidden="true">{{
      state === 'copied' ? 'copied' : state === 'failed' ? 'copy failed' : 'copy'
    }}</span>
    <span role="status" class="visually-hidden">
      {{ state === 'copied' ? `${label} copied` : state === 'failed' ? 'Copy failed' : '' }}
    </span>
  </span>
</template>

<style scoped>
.copytext {
  display: inline-flex;
  align-items: baseline;
  gap: var(--sp-2);
  max-width: 100%;
  min-width: 0;
}

.value {
  font-family: var(--font-mono);
  font-size: inherit;
  color: inherit;
  background: none;
  border: 0;
  border-bottom: 1px dotted var(--line-strong);
  padding: 0;
  cursor: pointer;
  text-align: left;
  overflow-wrap: anywhere;
  transition: color var(--transition), border-color var(--transition);
}

.value:hover {
  border-bottom-color: var(--amber);
  color: var(--link);
}

/* Affordance stays quiet until you're near it. */
.hint {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--faint);
  white-space: nowrap;
  visibility: hidden;
}

.copytext:hover .hint,
.value:focus-visible ~ .hint {
  visibility: visible;
}
</style>
