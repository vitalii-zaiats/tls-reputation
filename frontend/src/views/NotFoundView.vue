<script setup>
import { computed } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import LookupInput from '../components/LookupInput.vue'

const route = useRoute()
const path = computed(() => route.fullPath)
</script>

<template>
  <section class="notfound">
    <h1>404</h1>
    <p class="ident mono">{{ path }}</p>
    <p>
      No such page. If you were looking up a fingerprint or a domain, the paths are
      <code>/fp/&lt;ja3-or-ja4&gt;</code> and <code>/sni/&lt;domain&gt;</code> — or just use the
      box below.
    </p>

    <div class="box">
      <LookupInput size="lg" />
    </div>

    <p class="links">
      <RouterLink to="/">home</RouterLink> ·
      <RouterLink to="/browse">browse</RouterLink> ·
      <RouterLink to="/docs">docs</RouterLink>
    </p>
  </section>
</template>

<style scoped>
.notfound {
  padding-top: var(--sp-6);
}

h1 {
  font-family: var(--font-mono);
  font-size: var(--fs-xxl);
  margin-bottom: var(--sp-3);
}

.ident {
  font-size: var(--fs-sm);
  color: var(--dim);
  overflow-wrap: anywhere;
  margin-bottom: var(--sp-5);
}

.box {
  max-width: 40rem;
  margin: var(--sp-6) 0;
}

.links {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
}
</style>
