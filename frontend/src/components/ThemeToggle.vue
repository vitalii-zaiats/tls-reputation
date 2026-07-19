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

onMounted(() => {
  // The inline script in index.html already set the attribute; read it back so
  // the control renders in the correct state.
  const attr = document.documentElement.getAttribute('data-theme')
  mode.value = attr === 'light' || attr === 'dark' ? attr : 'auto'
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
}

.opt[aria-pressed="true"] {
  border-color: transparent;
}
</style>
