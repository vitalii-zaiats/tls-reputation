import { createRouter, createWebHistory } from 'vue-router'

import HomeView from './views/HomeView.vue'

const SITE = 'tls-reputation.com'

const routes = [
  {
    path: '/',
    name: 'home',
    component: HomeView,
    meta: { title: `${SITE} — TLS fingerprint reputation` },
  },
  {
    // Accepts either a JA3 md5 or a JA4 string; the view picks the endpoint.
    path: '/fp/:hash',
    name: 'fingerprint',
    component: () => import('./views/FingerprintView.vue'),
  },
  {
    path: '/sni/:name',
    name: 'sni',
    component: () => import('./views/SniView.vue'),
  },
  {
    path: '/browse',
    name: 'browse',
    component: () => import('./views/BrowseView.vue'),
    // No meta title: the view titles itself from the ?tab= mode, and a
    // meta title would overwrite it on every sort/page change.
  },
  {
    path: '/docs',
    name: 'docs',
    component: () => import('./views/DocsView.vue'),
    meta: { title: `API documentation — ${SITE}` },
  },
  {
    // Force-directed explorer. Seeded from ?sni= or ?ja4=; the view titles
    // itself from the seed once the graph is built.
    path: '/graph',
    name: 'graph',
    component: () => import('./views/GraphView.vue'),
  },
  {
    // Same component, chrome-less and compact, for iframing into a blog. App.vue
    // renders a bare RouterView for anything with meta.embed. The host nginx
    // only relaxes framing for paths under /embed, so this path is deliberate.
    path: '/embed',
    name: 'graph-embed',
    component: () => import('./views/GraphView.vue'),
    meta: { embed: true, title: `graph — ${SITE}` },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('./views/NotFoundView.vue'),
    meta: { title: `404 — ${SITE}` },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    return savedPosition || { top: 0 }
  },
})

// Detail views set their own titles once data arrives.
router.afterEach((to) => {
  if (to.meta?.title) document.title = to.meta.title
})

export default router
