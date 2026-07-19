<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import ThemeToggle from './components/ThemeToggle.vue'
import LookupInput from './components/LookupInput.vue'

const route = useRoute()

// The home page has its own large lookup box; don't duplicate it in the header.
const showHeaderLookup = computed(() => route.name !== 'home')
</script>

<template>
  <a class="skip" href="#main">Skip to content</a>

  <header class="masthead">
    <div class="masthead-inner">
      <div class="brand">
        <RouterLink to="/" class="wordmark">tls-reputation.com</RouterLink>
        <span class="tagline">TLS fingerprint reputation</span>
      </div>

      <nav class="nav" aria-label="Main">
        <RouterLink to="/browse">browse</RouterLink>
        <RouterLink to="/docs">docs</RouterLink>
        <a href="/api/docs">api</a>
      </nav>

      <ThemeToggle />
    </div>

    <div v-if="showHeaderLookup" class="header-lookup">
      <LookupInput size="sm" />
    </div>
  </header>

  <main id="main" class="page">
    <RouterView />
  </main>

  <footer class="footer">
    <div class="footer-inner">
      <p class="line">
        Public, free and open. Data licensed
        <a href="https://creativecommons.org/licenses/by/4.0/" rel="license noopener">CC&nbsp;BY&nbsp;4.0</a>.
        No authentication, no rate limit beyond fair use.
      </p>
      <p class="line faint">
        Fingerprints are observations of TLS ClientHello messages. They identify software, not people.
      </p>
    </div>
  </footer>
</template>

<style scoped>
.skip {
  position: absolute;
  left: -9999px;
}

.skip:focus {
  left: var(--sp-4);
  top: var(--sp-2);
  z-index: 10;
  background: var(--c-bg);
  border: var(--border-strong);
  padding: var(--sp-2) var(--sp-3);
  text-decoration: none;
}

.masthead {
  border-bottom: var(--border-width) solid var(--c-border-strong);
}

.masthead-inner,
.footer-inner {
  max-width: var(--page-max);
  margin: 0 auto;
  padding: var(--sp-3) var(--sp-4);
}

.masthead-inner {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  flex-wrap: wrap;
}

.brand {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
  margin-right: auto;
  min-width: 0;
}

.wordmark {
  font-family: var(--font-mono);
  font-size: var(--fs-base);
  font-weight: 600;
  color: var(--c-fg);
  text-decoration: none;
  white-space: nowrap;
}

.wordmark:hover {
  color: var(--c-accent);
}

.tagline {
  font-size: var(--fs-xs);
  color: var(--c-fg-faint);
  white-space: nowrap;
}

.nav {
  display: flex;
  gap: var(--sp-4);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
}

.nav a {
  color: var(--c-fg-muted);
  text-decoration: none;
  padding-bottom: 2px;
  border-bottom: 1px solid transparent;
}

.nav a:hover {
  color: var(--c-fg);
  border-bottom-color: var(--c-border);
}

/* The one active state, in the one accent colour. */
.nav a.router-link-active {
  color: var(--c-accent);
  border-bottom-color: var(--c-accent);
}

.header-lookup {
  max-width: var(--page-max);
  margin: 0 auto;
  padding: 0 var(--sp-4) var(--sp-3);
}

.footer {
  border-top: var(--border);
  margin-top: var(--sp-8);
}

.line {
  font-size: var(--fs-xs);
  color: var(--c-fg-muted);
  margin: 0 0 var(--sp-1);
  max-width: var(--measure);
}

@media (max-width: 40rem) {
  .tagline {
    display: none;
  }
  .brand {
    margin-right: 0;
    width: 100%;
  }
}
</style>
