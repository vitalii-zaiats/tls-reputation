<script setup>
/**
 * Three-state theme control: auto (follow the OS) / light / dark.
 * Choice persists in localStorage; `auto` clears the override so
 * prefers-color-scheme takes back over.
 */
import { ref, onMounted } from 'vue'

const STORAGE_KEY = 'tlsrep-theme'
const MODES = [
  { value: 'auto', label: 'auto' },
  { value: 'light', label: 'light' },
  { value: 'dark', label: 'dark' },
]

const mode = ref('auto')

function apply(next) {
  mode.value = next
  const root = document.documentElement
  if (next === 'auto') {
    root.removeAttribute('data-theme')
  } else {
    root.setAttribute('data-theme', next)
  }
  try {
    if (next === 'auto') localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, next)
  } catch (e) {
    /* private mode / storage disabled — the in-page choice still applies */
  }
}

function stored() {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'light' || value === 'dark' ? value : 'auto'
  } catch {
    return 'auto'
  }
}

onMounted(() => {
  // Re-assert from storage rather than reading back the DOM attribute the
  // inline script set. Storage is the source of truth; the attribute is a
  // derived value, and anything that strips it between first paint and mount
  // would otherwise leave the page silently on the wrong theme with no way
  // back short of clicking the toggle again.
  apply(stored())
})

// A choice made in one tab applies to the others.
window.addEventListener('storage', (event) => {
  if (event.key === STORAGE_KEY) apply(stored())
})

// Restoring from the back/forward cache skips the inline script, so re-assert.
window.addEventListener('pageshow', (event) => {
  if (event.persisted) apply(stored())
})
</script>

<template>
  <div class="theme" role="group" aria-label="Colour theme">
    <button
      v-for="m in MODES"
      :key="m.value"
      type="button"
      class="control opt"
      :aria-pressed="mode === m.value"
      @click="apply(m.value)"
    >
      {{ m.label }}
    </button>
  </div>
</template>

<style scoped>
/* Rounded chips can't share borders, so they sit in a track instead. */
.theme {
  display: inline-flex;
  gap: 3px;
  padding: 3px;
  background: var(--panel);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-chip);
}

.opt {
  padding: var(--sp-1) var(--sp-2);
  font-size: var(--fs-xs);
  border-color: transparent;
  background: none;
}

.opt:hover:not(:disabled) {
  border-color: transparent;
  color: var(--text);
}

/* The active segment has to be unmistakable: it is the only thing telling you
   the choice was remembered. The shared .control[aria-pressed] rule supplies a
   border this track deliberately hides, and .opt's own `background: none`
   cancels its fill at equal specificity — so state both here explicitly. */
.opt[aria-pressed="true"] {
  background: var(--amber-soft);
  color: var(--link);
  border-color: transparent;
}
</style>
