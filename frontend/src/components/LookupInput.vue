<script setup>
/**
 * The single lookup box. Accepts a JA3 md5, a JA4 string, or a domain and
 * routes to the right detail page.
 *
 * Classification is attempted locally first (instant, no round trip). If the
 * input doesn't match a known shape, we defer to the server's /search endpoint
 * before declaring it unrecognised.
 */
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api.js'
import { classifyQuery, normalizeQuery, routeForQuery } from '../format.js'

const props = defineProps({
  /** 'lg' for the home hero, 'sm' for the header. */
  size: { type: String, default: 'lg' },
  autofocus: { type: Boolean, default: false },
  initial: { type: String, default: '' },
})

const router = useRouter()

const query = ref(props.initial)
const checking = ref(false)
const message = ref('')

const kind = computed(() => classifyQuery(query.value))

/** Live echo of what the input will be treated as. */
const kindLabel = computed(() => {
  if (!query.value.trim()) return ''
  switch (kind.value) {
    case 'ja3':
      return 'JA3 (md5)'
    case 'ja4':
      return 'JA4'
    case 'sni':
      return 'domain'
    default:
      return 'unrecognised'
  }
})

async function submit() {
  message.value = ''
  const q = normalizeQuery(query.value)
  if (!q) {
    message.value = 'Enter a JA3 hash, a JA4 string, or a domain.'
    return
  }

  const local = routeForQuery(q)
  if (local) {
    router.push(local)
    return
  }

  // Ambiguous input — ask the server what it is.
  checking.value = true
  try {
    const result = await api.search(q)
    switch (result?.kind) {
      case 'ja3':
        router.push({ name: 'fingerprint', params: { hash: result.match?.ja3 || q } })
        break
      case 'ja4':
        router.push({ name: 'fingerprint', params: { hash: result.match?.ja4 || q } })
        break
      case 'sni':
        router.push({ name: 'sni', params: { name: result.match?.sni || q } })
        break
      default:
        message.value = 'Not a recognised JA3 hash, JA4 string, or domain.'
    }
  } catch (err) {
    message.value = err?.message || 'Lookup failed.'
  } finally {
    checking.value = false
  }
}
</script>

<template>
  <form class="lookup" :class="`lookup--${size}`" role="search" @submit.prevent="submit">
    <label class="visually-hidden" :for="`lookup-${size}`">
      JA3 hash, JA4 string, or domain
    </label>
    <div class="row">
      <input
        :id="`lookup-${size}`"
        v-model="query"
        type="text"
        class="field"
        name="q"
        placeholder="JA3 md5, JA4 string, or domain"
        autocomplete="off"
        autocapitalize="off"
        autocorrect="off"
        spellcheck="false"
        :autofocus="autofocus"
        @input="message = ''"
      />
      <button type="submit" class="control submit" :disabled="checking">
        {{ checking ? 'checking…' : 'look up' }}
      </button>
    </div>

    <p v-if="message" class="note note--error" role="alert">{{ message }}</p>
    <p v-else-if="kindLabel && size === 'lg'" class="note" aria-live="polite">
      detected: {{ kindLabel }}
    </p>
  </form>
</template>

<style scoped>
.lookup {
  width: 100%;
}

.row {
  display: flex;
}

.field {
  flex: 1 1 auto;
  min-width: 0;
  font-family: var(--font-mono);
  color: var(--c-fg);
  background: var(--c-bg);
  border: var(--border-width) solid var(--c-border-strong);
  border-radius: var(--radius);
  padding: var(--sp-2) var(--sp-3);
}

.field::placeholder {
  color: var(--c-fg-faint);
}

.submit {
  flex: none;
  border-color: var(--c-border-strong);
  margin-left: -1px; /* share the border with the field */
}

.lookup--lg .field,
.lookup--lg .submit {
  font-size: var(--fs-md);
  padding: var(--sp-3) var(--sp-4);
}

.lookup--sm .field,
.lookup--sm .submit {
  font-size: var(--fs-sm);
  padding: var(--sp-1) var(--sp-2);
}

.note {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--c-fg-muted);
  margin: var(--sp-2) 0 0;
  min-height: 1.2em;
}

.note--error {
  color: var(--c-danger);
}
</style>
