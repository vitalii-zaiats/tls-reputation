<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import ThemeToggle from './components/ThemeToggle.vue'
import LookupInput from './components/LookupInput.vue'

const route = useRoute()

// The home page has its own large lookup box; don't duplicate it in the header.
const showHeaderLookup = computed(() => route.name !== 'home')

// Embed routes (the iframeable graph) render ONLY the view — no masthead, nav
// or footer — so a blog can drop them in at 100% of the frame.
const isEmbed = computed(() => route.meta.embed === true)
</script>

<template>
  <!-- Chrome-less: the embedded view owns the whole viewport. -->
  <RouterView v-if="isEmbed" />

  <template v-else>
    <a class="skip" href="#main">Skip to content</a>

    <header class="masthead">
      <div class="masthead-inner">
        <div class="brand">
          <RouterLink to="/" class="wordmark">tls-reputation.com</RouterLink>
          <span class="tagline">TLS fingerprint reputation</span>
        </div>

        <nav class="nav" aria-label="Main">
          <RouterLink to="/browse">browse</RouterLink>
          <RouterLink to="/graph">graph</RouterLink>
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
</template>

<style scoped>
.skip {
  position: absolute;
  left: -9999px;
}

.skip:focus {
  left: var(--sp-4);
  top: var(--sp-2);
  z-index: 30;
  background: var(--panel);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-chip);
  padding: var(--sp-2) var(--sp-3);
  text-decoration: none;
}

/* Sticky, translucent over whatever scrolls beneath it. */
.masthead {
  position: sticky;
  top: 0;
  z-index: 20;
  background: color-mix(in srgb, var(--bg) 86%, transparent);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: var(--border-width) solid var(--line);
}

.masthead-inner,
.footer-inner {
  max-width: var(--page-max);
  margin: 0 auto;
  padding: var(--sp-3) var(--page-pad);
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
  color: var(--text);
  text-decoration: none;
  white-space: nowrap;
  transition: color var(--transition);
}

.wordmark:hover {
  color: var(--link);
}

.tagline {
  font-size: var(--fs-xs);
  color: var(--dim);
  white-space: nowrap;
}

.nav {
  display: flex;
  gap: var(--sp-4);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
}

.nav a {
  color: var(--dim);
  text-decoration: none;
  padding-bottom: 2px;
  border-bottom: 1px solid transparent;
  transition: color var(--transition), border-color var(--transition);
}

.nav a:hover {
  color: var(--text);
  border-bottom-color: var(--line-strong);
}

/* The one active state, in the one accent colour. */
.nav a.router-link-active {
  color: var(--link);
  border-bottom-color: var(--amber);
}

.header-lookup {
  max-width: var(--page-max);
  margin: 0 auto;
  padding: 0 var(--page-pad) var(--sp-3);
}

.footer {
  border-top: var(--border-width) solid var(--line);
  margin-top: var(--sp-8);
}

.line {
  font-size: var(--fs-xs);
  color: var(--dim);
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
