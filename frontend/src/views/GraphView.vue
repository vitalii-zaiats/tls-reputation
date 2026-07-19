<script setup>
/**
 * Interactive force-directed explorer of the corpus.
 *
 * A bipartite graph of server-name (SNI) and fingerprint (JA4) nodes joined by
 * "was observed reaching" edges. You seed it from the route query and click a
 * circle to fetch ITS neighbours and grow the graph; shared nodes merge, so the
 * structure becomes visible. Everything runs on the existing /sni and /ja4
 * endpoints — the physics is hand-written (see graph.js), because the site's
 * CSP forbids d3 or any CDN script.
 *
 * The same component serves both `/graph` (full, inside the site chrome) and
 * `/embed` (compact, chrome-less, for iframing into a blog). `route.meta.embed`
 * drives the difference.
 *
 * Reactivity note: node positions change ~60×/s for up to 200 nodes. Wrapping
 * every node in a Vue proxy would put a get/set trap on the hot path of the
 * O(n²) loop. Instead the node/edge arrays are `shallowRef`s of PLAIN objects,
 * mutated in place, and `triggerRef` forces one re-render per frame. Structural
 * lookups use plain Maps; genuine UI state (hover, seed, messages) uses refs.
 */
import { computed, onMounted, onUnmounted, ref, shallowRef, triggerRef, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { api, ApiError } from '../api.js'
import { classifyQuery, normalizeQuery, truncateMiddle, formatInt } from '../format.js'
import {
  MAX_NODES,
  nodeId,
  edgeKey,
  hash01,
  radiusForWeight,
  recomputeSizes,
  edgeWidthForCount,
  simulationStep,
  energyThreshold,
} from '../graph.js'

const route = useRoute()
const router = useRouter()

const isEmbed = computed(() => route.meta.embed === true)

/* -------------------------------------------------------------------------
   Graph state
   ------------------------------------------------------------------------- */

// Plain objects inside shallowRefs — see the reactivity note above.
const nodes = shallowRef([])
const edges = shallowRef([])
// Non-reactive indexes for O(1) dedupe.
const byId = new Map()
const edgeByKey = new Map()

const hoverId = ref(null)
const seedError = ref('')
const expandError = ref('')
const largeNote = ref(false)
const reseedText = ref('')
const reseedMsg = ref('')

// Viewport (world coordinates == container px at zoom 1).
const width = ref(900)
const height = ref(560)
const panX = ref(0)
const panY = ref(0)
const zoom = ref(1)

const svgRef = ref(null)
const stageRef = ref(null)

const nodeCount = computed(() => nodes.value.length)
const edgeCount = computed(() => edges.value.length)

/* -------------------------------------------------------------------------
   Seed
   ------------------------------------------------------------------------- */

function firstQuery(v) {
  if (Array.isArray(v)) return typeof v[0] === 'string' ? v[0] : ''
  return typeof v === 'string' ? v : ''
}

/**
 * The seed the graph is built from. `?sni=` wins over `?ja4=`; with neither we
 * default to a domain everyone recognises so the page is never empty. A seed
 * that fails the same shape check LookupInput/FingerprintView use is invalid,
 * and produces an inline message rather than a request the backend rejects.
 */
const seed = computed(() => {
  const sniRaw = firstQuery(route.query.sni)
  const ja4Raw = firstQuery(route.query.ja4)
  if (sniRaw) {
    const value = normalizeQuery(sniRaw)
    return { type: 'sni', value, valid: classifyQuery(value) === 'sni', raw: sniRaw }
  }
  if (ja4Raw) {
    const value = ja4Raw.trim().toLowerCase()
    return { type: 'fp', value, valid: classifyQuery(value) === 'ja4', raw: ja4Raw }
  }
  const value = 'www.facebook.com'
  return { type: 'sni', value, valid: true, raw: value, isDefault: true }
})

const seedLabel = computed(() =>
  seed.value.type === 'sni'
    ? truncateMiddle(seed.value.value, 22, 8)
    : truncateMiddle(seed.value.value, 10, 6),
)

const seedQuery = computed(() =>
  seed.value.type === 'sni' ? { sni: seed.value.value } : { ja4: seed.value.value },
)

/** Full-view URL for the embed's "open full view" link (new tab). */
const fullViewHref = computed(() => router.resolve({ name: 'graph', query: seedQuery.value }).href)

/* -------------------------------------------------------------------------
   Model mutations
   ------------------------------------------------------------------------- */

function labelFor(type, value) {
  if (type === 'sni') return truncateMiddle(value, isEmbed.value ? 13 : 18, isEmbed.value ? 5 : 6)
  return truncateMiddle(value, isEmbed.value ? 7 : 9, isEmbed.value ? 4 : 5)
}

function createNode({ type, value, x, y }) {
  return {
    id: nodeId(type, value),
    type,
    value,
    label: labelFor(type, value),
    x,
    y,
    vx: 0,
    vy: 0,
    weight: 0,
    r: radiusForWeight(0, isEmbed.value),
    fixed: false,
    expanded: false,
    loading: false,
    obs: null,
    uniq: null,
    error: null,
  }
}

function addEdge(a, b, count) {
  const key = edgeKey(a.id, b.id)
  const existing = edgeByKey.get(key)
  const c = Number(count) || 0
  if (existing) {
    // Same pair from another parent: keep the larger count, don't duplicate.
    if (c > existing.count) existing.count = c
    return existing
  }
  const edge = { key, source: a.id, target: b.id, sourceNode: a, targetNode: b, count: c }
  edgeByKey.set(key, edge)
  edges.value.push(edge)
  return edge
}

/** Add (or reuse) a neighbour of `parent` and the edge to it. */
function addNeighbour(parent, { type, value, count }, index) {
  const id = nodeId(type, value)
  let node = byId.get(id)
  if (!node) {
    if (nodes.value.length >= MAX_NODES) {
      largeNote.value = true
      return null
    }
    // Spawn near the parent with a small deterministic offset — a golden-angle
    // fan plus a per-id jitter so siblings don't stack and explode apart.
    const h = hash01(id)
    const angle = index * 2.3999632 + h * 6.2831853
    const dist = 34 + h * 26
    node = createNode({
      type,
      value,
      x: parent.x + Math.cos(angle) * dist,
      y: parent.y + Math.sin(angle) * dist,
    })
    byId.set(id, node)
    nodes.value.push(node)
  }
  addEdge(parent, node, count)
  return node
}

/**
 * Fetch a node's neighbours and grow the graph. A node already expanded, or one
 * mid-fetch, does nothing. Past the node cap we stop fetching and show a quiet
 * note instead — the detail links remain the way to keep exploring.
 */
async function expandNode(node) {
  if (!node || node.expanded || node.loading) return
  if (nodes.value.length >= MAX_NODES) {
    largeNote.value = true
    return
  }
  node.loading = true
  node.error = null
  expandError.value = ''
  triggerRef(nodes)

  try {
    if (node.type === 'sni') {
      const data = await api.sni(node.value)
      node.obs = data.observations
      node.uniq = data.unique_fingerprints
      const list = data.top_fingerprints || []
      list.forEach((f, i) => {
        if (f.ja4) addNeighbour(node, { type: 'fp', value: f.ja4, count: f.count }, i)
      })
    } else {
      const data = await api.ja4(node.value)
      node.obs = data.observations
      node.uniq = data.unique_snis
      const list = data.top_snis || []
      list.forEach((s, i) => {
        if (s.sni) addNeighbour(node, { type: 'sni', value: s.sni, count: s.count }, i)
      })
    }
    node.expanded = true
  } catch (err) {
    if (err instanceof ApiError && err.notFound) {
      node.error = 'not observed'
    } else {
      node.error = (err && err.message) || 'expand failed'
    }
    expandError.value = `${node.value}: ${node.error}`
  } finally {
    node.loading = false
    recomputeSizes(nodes.value, edges.value, isEmbed.value)
    triggerRef(nodes)
    triggerRef(edges)
    startSim()
  }
}

/** Rebuild from just the seed. */
function buildGraph() {
  stopSim()
  nodes.value = []
  edges.value = []
  byId.clear()
  edgeByKey.clear()
  panX.value = 0
  panY.value = 0
  zoom.value = 1
  hoverId.value = null
  largeNote.value = false
  expandError.value = ''
  reseedMsg.value = ''

  if (!seed.value.valid) {
    seedError.value =
      seed.value.type === 'fp'
        ? `"${seed.value.raw}" is not a valid JA4 string.`
        : `"${seed.value.raw}" is not a valid domain.`
    triggerRef(nodes)
    return
  }
  seedError.value = ''

  const node = createNode({ type: seed.value.type, value: seed.value.value, x: width.value / 2, y: height.value / 2 })
  byId.set(node.id, node)
  nodes.value = [node]
  triggerRef(nodes)

  if (!isEmbed.value) document.title = `graph: ${seed.value.value} — tls-reputation.com`

  // The seed shows its neighbours immediately.
  expandNode(node)
}

function resetGraph() {
  buildGraph()
}

/* -------------------------------------------------------------------------
   Reseed (full mode only)
   ------------------------------------------------------------------------- */

function submitReseed() {
  reseedMsg.value = ''
  const norm = normalizeQuery(reseedText.value)
  if (!norm) {
    reseedMsg.value = 'Enter a JA4 string or a domain.'
    return
  }
  const kind = classifyQuery(norm)
  if (kind === 'ja4') {
    router.push({ name: 'graph', query: { ja4: norm } })
  } else if (kind === 'sni') {
    router.push({ name: 'graph', query: { sni: norm } })
  } else if (kind === 'ja3') {
    reseedMsg.value = 'JA3 is a variant, not a graph seed — use its JA4, or a domain.'
  } else {
    reseedMsg.value = 'Not a recognised JA4 string or domain.'
  }
  reseedText.value = ''
}

/* -------------------------------------------------------------------------
   Force loop
   ------------------------------------------------------------------------- */

let rafId = null
let running = false

const simOpts = computed(() =>
  isEmbed.value
    ? { restLength: 72, kRepulsion: 3400, kCenter: 0.016 }
    : { restLength: 90, kRepulsion: 5200, kCenter: 0.012 },
)

function step() {
  if (!running) return
  const energy = simulationStep(nodes.value, edges.value, {
    ...simOpts.value,
    width: width.value,
    height: height.value,
  })
  triggerRef(nodes)
  if (energy < energyThreshold(nodes.value.length)) {
    running = false
    rafId = null
    return
  }
  rafId = requestAnimationFrame(step)
}

function startSim() {
  if (running || document.hidden || nodes.value.length === 0) return
  running = true
  rafId = requestAnimationFrame(step)
}

function stopSim() {
  running = false
  if (rafId) cancelAnimationFrame(rafId)
  rafId = null
}

/* -------------------------------------------------------------------------
   Pointer interaction: drag nodes, pan background, click to expand
   ------------------------------------------------------------------------- */

const DRAG_THRESHOLD = 4
let drag = null

function toWorld(clientX, clientY) {
  const rect = svgRef.value.getBoundingClientRect()
  return {
    x: (clientX - rect.left - panX.value) / zoom.value,
    y: (clientY - rect.top - panY.value) / zoom.value,
  }
}

function onNodePointerDown(node, e) {
  if (e.button !== 0) return
  e.stopPropagation() // don't also start a background pan
  try {
    svgRef.value.setPointerCapture(e.pointerId)
  } catch (err) {
    /* capture is best-effort */
  }
  drag = { mode: 'node', nodeId: node.id, pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, moved: false }
}

function onBackgroundPointerDown(e) {
  if (e.button !== 0) return
  try {
    svgRef.value.setPointerCapture(e.pointerId)
  } catch (err) {
    /* best-effort */
  }
  drag = {
    mode: 'pan',
    pointerId: e.pointerId,
    startX: e.clientX,
    startY: e.clientY,
    moved: false,
    panX0: panX.value,
    panY0: panY.value,
  }
}

function onPointerMove(e) {
  if (!drag || e.pointerId !== drag.pointerId) return
  const dx = e.clientX - drag.startX
  const dy = e.clientY - drag.startY
  if (!drag.moved && Math.hypot(dx, dy) > DRAG_THRESHOLD) drag.moved = true
  if (!drag.moved) return

  if (drag.mode === 'node') {
    const node = byId.get(drag.nodeId)
    if (node) {
      const p = toWorld(e.clientX, e.clientY)
      node.x = p.x
      node.y = p.y
      node.vx = 0
      node.vy = 0
      node.fixed = true // pin while dragging
      triggerRef(nodes)
      startSim()
    }
  } else if (drag.mode === 'pan') {
    panX.value = drag.panX0 + dx
    panY.value = drag.panY0 + dy
  }
}

function onPointerUp(e) {
  if (!drag || e.pointerId !== drag.pointerId) return
  try {
    svgRef.value.releasePointerCapture(e.pointerId)
  } catch (err) {
    /* best-effort */
  }
  if (drag.mode === 'node') {
    const node = byId.get(drag.nodeId)
    if (node) {
      if (!drag.moved) {
        // A click, not a drag: expand.
        expandNode(node)
      } else {
        // Release the pin so it rejoins the simulation.
        node.fixed = false
        startSim()
      }
    }
  }
  drag = null
}

function setHover(id) {
  hoverId.value = id
}

function clearHover(id) {
  if (hoverId.value === id) hoverId.value = null
}

/* -------------------------------------------------------------------------
   Zoom (full mode has buttons; ctrl/⌘ + wheel everywhere, so a bare wheel
   still scrolls the host page — important inside an iframe)
   ------------------------------------------------------------------------- */

function applyZoom(factor, px, py) {
  const old = zoom.value
  const next = Math.max(0.4, Math.min(2.5, old * factor))
  if (next === old) return
  // Keep the point under the cursor fixed.
  const wx = (px - panX.value) / old
  const wy = (py - panY.value) / old
  panX.value = px - wx * next
  panY.value = py - wy * next
  zoom.value = next
}

function zoomBy(factor) {
  applyZoom(factor, width.value / 2, height.value / 2)
}

function resetView() {
  panX.value = 0
  panY.value = 0
  zoom.value = 1
}

function onWheel(e) {
  if (!(e.ctrlKey || e.metaKey)) return // let a plain wheel scroll the page
  e.preventDefault()
  const rect = svgRef.value.getBoundingClientRect()
  const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1
  applyZoom(factor, e.clientX - rect.left, e.clientY - rect.top)
}

/* -------------------------------------------------------------------------
   Highlight, readout, links
   ------------------------------------------------------------------------- */

const highlight = computed(() => {
  const id = hoverId.value
  if (!id) return null
  const nodeSet = new Set([id])
  const edgeSet = new Set()
  for (const e of edges.value) {
    if (e.source === id || e.target === id) {
      edgeSet.add(e.key)
      nodeSet.add(e.source)
      nodeSet.add(e.target)
    }
  }
  return { nodeSet, edgeSet }
})

function dimNode(node) {
  const h = highlight.value
  return h ? !h.nodeSet.has(node.id) : false
}

function dimEdge(e) {
  const h = highlight.value
  return h ? !h.edgeSet.has(e.key) : false
}

function hotEdge(e) {
  const h = highlight.value
  return h ? h.edgeSet.has(e.key) : false
}

const activeNode = computed(() => (hoverId.value ? byId.get(hoverId.value) || null : null))

function nodeStat(node) {
  if (node.error) return node.error
  if (node.loading) return 'loading…'
  if (node.obs != null) {
    const unit = node.type === 'sni' ? 'fingerprints' : 'server names'
    return `${formatInt(node.obs)} obs · ${formatInt(node.uniq)} ${unit}`
  }
  return node.expanded ? 'expanded' : 'click to expand'
}

function nodeTitle(node) {
  const kind = node.type === 'sni' ? 'SNI' : 'JA4'
  const stat = node.obs != null ? ` — ${nodeStat(node)}` : ''
  return `${kind}: ${node.value}${stat}`
}

function detailRoute(node) {
  return node.type === 'sni'
    ? { name: 'sni', params: { name: node.value } }
    : { name: 'fingerprint', params: { hash: node.value } }
}

function detailHref(node) {
  return router.resolve(detailRoute(node)).href
}

const ariaLabel = computed(
  () =>
    `Force-directed graph seeded at ${seed.value.value}: ${nodeCount.value} nodes, ${edgeCount.value} links.`,
)

/* -------------------------------------------------------------------------
   Lifecycle
   ------------------------------------------------------------------------- */

let resizeObserver = null

function measure() {
  const el = stageRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  width.value = Math.max(320, Math.round(rect.width))
  height.value = Math.max(240, Math.round(rect.height))
}

function onWindowResize() {
  measure()
}

function onVisibility() {
  if (document.hidden) stopSim()
  else startSim()
}

onMounted(() => {
  measure()
  if (window.ResizeObserver) {
    resizeObserver = new ResizeObserver(() => measure())
    resizeObserver.observe(stageRef.value)
  } else {
    window.addEventListener('resize', onWindowResize)
  }
  document.addEventListener('visibilitychange', onVisibility)
  // Non-passive so ctrl/⌘ + wheel can preventDefault when it zooms.
  svgRef.value.addEventListener('wheel', onWheel, { passive: false })
  buildGraph()
})

onUnmounted(() => {
  stopSim()
  if (resizeObserver) resizeObserver.disconnect()
  else window.removeEventListener('resize', onWindowResize)
  document.removeEventListener('visibilitychange', onVisibility)
  if (svgRef.value) svgRef.value.removeEventListener('wheel', onWheel)
})

// Reseeding (or a host page changing ?sni=) rebuilds the graph. The embed flag
// is in the key too: navigating full↔embed reuses this component instance
// (same lazy component), so a rebuild is what re-sizes nodes for the new mode.
watch(
  () => `${isEmbed.value}|${seed.value.type}:${seed.value.value}`,
  () => buildGraph(),
)
</script>

<template>
  <div class="graph" :class="{ 'graph--embed': isEmbed }">
    <!-- Full-mode intro. The embed drops all of this. -->
    <header v-if="!isEmbed" class="intro">
      <h1>Graph explorer</h1>
      <p class="lead">
        The corpus as a bipartite graph: server names and TLS fingerprints, joined where a
        fingerprint was observed reaching a name. Seeded below; <strong>click any circle</strong> to
        fetch its neighbours and grow the graph. Circles that two seeds share merge into one, which
        is how the shape becomes visible.
      </p>
      <p class="note faint">
        The graph is mouse-driven — drag to move a circle, drag the background to pan, ctrl/⌘ and
        the wheel to zoom. Every circle is also a page: the same data is browsable as tables under
        <RouterLink to="/browse">browse</RouterLink>, and each node links to its
        <span class="mono">/sni</span> or <span class="mono">/fp</span> detail.
      </p>
    </header>

    <!-- Toolbar. Full mode gets reseed + zoom; embed gets seed + reset only. -->
    <div class="toolbar" :class="{ 'toolbar--embed': isEmbed }">
      <div class="seed" :title="seed.value">
        <span class="seed-kind">{{ seed.type === 'sni' ? 'SNI' : 'JA4' }}</span>
        <span class="seed-val mono">{{ seedLabel }}</span>
      </div>

      <form v-if="!isEmbed" class="reseed" role="search" @submit.prevent="submitReseed">
        <label class="visually-hidden" for="graph-reseed">Reseed by JA4 string or domain</label>
        <span class="reseed-prompt mono" aria-hidden="true">&gt;</span>
        <input
          id="graph-reseed"
          v-model="reseedText"
          class="reseed-field mono"
          type="text"
          name="q"
          placeholder="reseed: JA4 or domain"
          autocomplete="off"
          autocapitalize="off"
          autocorrect="off"
          spellcheck="false"
        />
        <button type="submit" class="control">seed</button>
      </form>

      <button type="button" class="control" @click="resetGraph">reset</button>

      <div v-if="!isEmbed" class="zoomers" role="group" aria-label="Zoom">
        <button type="button" class="control" aria-label="Zoom out" @click="zoomBy(1 / 1.15)">−</button>
        <button type="button" class="control" aria-label="Zoom in" @click="zoomBy(1.15)">+</button>
        <button type="button" class="control" @click="resetView">fit</button>
      </div>
    </div>

    <p v-if="reseedMsg" class="msg msg--error" role="alert">{{ reseedMsg }}</p>
    <p v-else-if="expandError" class="msg msg--error" role="alert">{{ expandError }}</p>

    <div ref="stageRef" class="stage">
      <svg
        ref="svgRef"
        class="canvas"
        :viewBox="`0 0 ${width} ${height}`"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        :aria-label="ariaLabel"
        @pointerdown="onBackgroundPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
      >
        <desc>
          Circles are server names and TLS fingerprints; a line means the fingerprint was observed
          reaching the server name. Click a circle to expand its neighbours.
        </desc>

        <g :transform="`translate(${panX} ${panY}) scale(${zoom})`">
          <line
            v-for="e in edges"
            :key="e.key"
            class="edge"
            :class="{ dim: dimEdge(e), hot: hotEdge(e) }"
            :x1="e.sourceNode.x"
            :y1="e.sourceNode.y"
            :x2="e.targetNode.x"
            :y2="e.targetNode.y"
            :stroke-width="edgeWidthForCount(e.count)"
          />

          <g
            v-for="node in nodes"
            :key="node.id"
            class="node"
            :class="[
              `node--${node.type}`,
              { expanded: node.expanded, loading: node.loading, dim: dimNode(node), hot: node.id === hoverId },
            ]"
            :transform="`translate(${node.x} ${node.y})`"
            @pointerdown="onNodePointerDown(node, $event)"
            @pointerenter="setHover(node.id)"
            @pointerleave="clearHover(node.id)"
          >
            <title>{{ nodeTitle(node) }}</title>
            <circle class="disc" :r="node.r" />
            <circle v-if="node.expanded" class="core" :r="Math.max(2, node.r * 0.32)" />
            <text class="label" :y="node.r + (isEmbed ? 9 : 12)">{{ node.label }}</text>
          </g>
        </g>
      </svg>

      <!-- Corner readout: full label + a stat, since the on-canvas labels are
           truncated. Falls back to a one-line hint. -->
      <div class="readout" :class="{ empty: !activeNode }">
        <template v-if="activeNode">
          <div class="readout-kind">{{ activeNode.type === 'sni' ? 'server name' : 'fingerprint' }}</div>
          <div class="readout-label mono">{{ activeNode.value }}</div>
          <div class="readout-stat">{{ nodeStat(activeNode) }}</div>
          <div class="readout-link">
            <RouterLink v-if="!isEmbed" :to="detailRoute(activeNode)">open detail →</RouterLink>
            <a v-else :href="detailHref(activeNode)" target="_blank" rel="noopener">open detail →</a>
          </div>
        </template>
        <div v-else class="readout-hint">
          {{ nodeCount }} nodes · {{ edgeCount }} links — click to expand, drag to move
        </div>
      </div>

      <p v-if="seedError" class="stage-msg" role="alert">{{ seedError }}</p>

      <p v-if="largeNote" class="stage-note">
        graph is large — open a node's detail page to keep exploring
      </p>

      <!-- Embed-only: a single quiet escape hatch to the full site (new tab so
           it leaves the iframe). -->
      <a v-if="isEmbed" class="embed-full" :href="fullViewHref" target="_blank" rel="noopener">
        open full view ↗
      </a>
    </div>

    <p v-if="!isEmbed" class="footnote">
      Neighbour lists are capped server-side and the graph stops auto-growing at {{ MAX_NODES }}
      nodes. Bigger circle = larger observed volume. Fingerprint circles are amber with a dashed
      outline; server-name circles are solid — the shape tells them apart without relying on colour.
    </p>

    <!-- The graph is mouse-driven; this parallel list keeps every node reachable
         by keyboard and screen reader, and links straight to the detail pages. -->
    <div class="visually-hidden">
      <h2>Nodes currently in the graph</h2>
      <ul>
        <li v-for="node in nodes" :key="`sr-${node.id}`">
          {{ node.type === 'sni' ? 'server name' : 'fingerprint' }}
          <RouterLink v-if="!isEmbed" :to="detailRoute(node)">{{ node.value }}</RouterLink>
          <a v-else :href="detailHref(node)" target="_blank" rel="noopener">{{ node.value }}</a>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.graph {
  min-width: 0;
}

/* --- embed shell: fills the iframe, its own background, no page margins --- */
.graph--embed {
  position: fixed;
  inset: 0;
  background: var(--bg);
  display: flex;
  flex-direction: column;
  padding: var(--sp-2);
  gap: var(--sp-2);
}

.intro {
  margin-bottom: var(--sp-4);
}

.intro h1 {
  margin-bottom: var(--sp-3);
}

.lead {
  color: var(--dim);
  font-size: var(--fs-md);
}

.note {
  font-size: var(--fs-sm);
}

/* --- toolbar --- */
.toolbar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  margin-bottom: var(--sp-3);
}

.toolbar--embed {
  margin-bottom: 0;
  gap: var(--sp-2);
}

.seed {
  display: inline-flex;
  align-items: baseline;
  gap: var(--sp-2);
  min-width: 0;
  max-width: 100%;
}

.seed-kind {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--dim);
  flex: none;
}

.seed-val {
  font-size: var(--fs-sm);
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reseed {
  display: inline-flex;
  align-items: stretch;
  background: var(--panel);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-chip);
  transition: border-color var(--transition);
}

.reseed:focus-within {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
  border-color: var(--line-strong);
}

.reseed-prompt {
  display: flex;
  align-items: center;
  color: var(--link);
  font-weight: 600;
  padding-left: var(--sp-2);
  user-select: none;
}

.reseed-field {
  border: 0;
  background: none;
  color: var(--text);
  font-size: var(--fs-sm);
  padding: var(--sp-2);
  min-width: 0;
  width: 14rem;
  max-width: 40vw;
}

.reseed-field:focus {
  outline: none;
}

.reseed-field::placeholder {
  color: var(--dim);
}

.reseed .control {
  border: 0;
  border-left: var(--border-width) solid var(--line);
  border-radius: 0 var(--radius-chip) var(--radius-chip) 0;
}

.zoomers {
  display: inline-flex;
  gap: var(--sp-1);
  margin-left: auto;
}

.zoomers .control {
  min-width: 2rem;
  text-align: center;
}

.msg {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--dim);
  margin: 0 0 var(--sp-2);
}

.msg--error {
  color: var(--red);
}

/* --- stage --- */
.stage {
  position: relative;
  height: min(72vh, 720px);
  /* --bg, not --panel: the SNI circles are --panel-filled and need to read
     against the canvas. Also gives the embed "its own background from --bg". */
  background: var(--bg);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-panel);
  overflow: hidden;
  touch-action: none; /* pointer drag/pan owns the gesture */
}

.graph--embed .stage {
  flex: 1 1 auto;
  height: auto;
  min-height: 0;
  border-radius: var(--radius-card);
  /* Never trap the host blog's vertical scroll on touch. */
  touch-action: pan-y;
}

.canvas {
  display: block;
  width: 100%;
  height: 100%;
  cursor: grab;
}

.canvas:active {
  cursor: grabbing;
}

/* --- edges --- */
.edge {
  stroke: var(--line-strong);
  opacity: 0.55;
  pointer-events: none;
  transition: opacity var(--transition);
}

.edge.dim {
  opacity: 0.1;
}

.edge.hot {
  stroke: var(--amber);
  opacity: 0.95;
}

/* --- nodes --- */
.node {
  cursor: pointer;
}

.node.dim {
  opacity: 0.28;
}

.disc {
  stroke-width: 1.5;
  transition: stroke-width var(--transition);
}

/* SNI: solid outline, panel fill. FP: amber fill, DASHED outline — the dash is
   the non-colour cue so the two types are separable in greyscale too. */
.node--sni .disc {
  fill: var(--panel);
  stroke: var(--text);
}

.node--fp .disc {
  fill: var(--amber-soft);
  stroke: var(--amber);
  stroke-dasharray: 4 3;
}

.node.expanded .disc {
  stroke-width: 2.5;
}

.node--sni.expanded .disc {
  fill: var(--panel-2);
}

.node--fp.expanded .disc {
  fill: color-mix(in srgb, var(--amber) 30%, var(--panel));
}

.node.hot .disc {
  stroke: var(--link);
  stroke-width: 3;
}

/* Inner dot marks an expanded node. */
.core {
  pointer-events: none;
  fill: var(--dim);
  opacity: 0.55;
}

.node--fp .core {
  fill: var(--amber);
  opacity: 0.8;
}

.label {
  font-family: var(--font-mono);
  font-size: 11px;
  fill: var(--text);
  text-anchor: middle;
  pointer-events: none;
  /* Halo so labels stay legible over edges and neighbours. */
  paint-order: stroke;
  stroke: var(--bg);
  stroke-width: 3px;
  stroke-linejoin: round;
}

.graph--embed .label {
  font-size: 9px;
  stroke-width: 2.5px;
}

.node.dim .label {
  opacity: 0.4;
}

.node.loading .disc {
  stroke-dasharray: 3 3;
  animation: nodepulse 1s ease-in-out infinite;
}

@keyframes nodepulse {
  0%,
  100% {
    opacity: 0.45;
  }
  50% {
    opacity: 1;
  }
}

/* --- readout --- */
.readout {
  position: absolute;
  left: var(--sp-3);
  bottom: var(--sp-3);
  max-width: min(22rem, calc(100% - var(--sp-6)));
  padding: var(--sp-2) var(--sp-3);
  background: color-mix(in srgb, var(--panel) 92%, transparent);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-card);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  pointer-events: auto;
}

.readout.empty {
  border-color: transparent;
  background: none;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  padding: var(--sp-1) var(--sp-2);
  pointer-events: none; /* the bare hint must not block clicks on nodes beneath */
}

.graph--embed .readout {
  left: var(--sp-2);
  bottom: var(--sp-2);
  padding: var(--sp-1) var(--sp-2);
}

.readout-kind {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--dim);
}

.readout-label {
  font-size: var(--fs-sm);
  color: var(--text);
  overflow-wrap: anywhere;
  margin: 2px 0;
}

.readout-stat {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--dim);
}

.readout-link {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  margin-top: 2px;
}

.readout-hint {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--dim);
}

.graph--embed .readout-hint {
  font-size: var(--fs-xs);
}

/* --- stage overlays --- */
.stage-msg {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--sp-5);
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  color: var(--red);
}

.stage-note {
  position: absolute;
  top: var(--sp-3);
  left: 50%;
  transform: translateX(-50%);
  margin: 0;
  padding: var(--sp-1) var(--sp-3);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--dim);
  background: color-mix(in srgb, var(--panel) 92%, transparent);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-chip);
  max-width: calc(100% - var(--sp-6));
  text-align: center;
  pointer-events: none; /* status only — never intercept a node click */
}

.embed-full {
  position: absolute;
  top: var(--sp-2);
  right: var(--sp-2);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--dim);
  text-decoration: none;
  background: color-mix(in srgb, var(--panel) 90%, transparent);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 2px var(--sp-2);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}

.embed-full:hover {
  color: var(--link);
  border-color: color-mix(in srgb, var(--amber) 45%, transparent);
}

.footnote {
  font-size: var(--fs-xs);
  color: var(--dim);
  margin-top: var(--sp-3);
  max-width: var(--measure);
  line-height: 1.5;
}

@media (max-width: 40rem) {
  .stage {
    height: min(70vh, 560px);
  }
  .reseed-field {
    width: 9rem;
  }
  .zoomers {
    margin-left: 0;
  }
}
</style>
