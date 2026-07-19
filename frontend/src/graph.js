/**
 * Bipartite corpus graph — pure model + a small force-directed simulation,
 * written from scratch.
 *
 * The site's CSP is `script-src 'self'`, so there is no d3 and no CDN: the
 * physics below is a plain velocity-damped integrator, O(n²) repulsion at the
 * ≤200 nodes we cap the graph at. Nothing here touches Vue — GraphView.vue owns
 * reactivity, rendering and interaction and calls into these pure functions.
 *
 * A node is a server name (SNI) or a fingerprint (JA4). An edge means "this
 * fingerprint was observed reaching this server name". Node objects are mutated
 * in place every frame (x/y/vx/vy); keeping them out of Vue's reactivity is
 * deliberate — see the shallowRef/triggerRef note in GraphView.
 */

/** Hard ceiling on auto-growth. Expanding a browser fingerprint is what hits it. */
export const MAX_NODES = 200

/* -------------------------------------------------------------------------
   Sizing
   ------------------------------------------------------------------------- */

/**
 * Radius from a node's total incident edge weight. `sqrt` keeps a shared hub
 * honest across parents (summed counts), while within one parent's neighbours
 * the counts are the shares, so radius still reads as "bigger circle = bigger
 * share". Compact mode (embed) uses a tighter range so more fits in a 600px
 * iframe without scrolling.
 */
export function radiusForWeight(weight, compact = false) {
  const w = Number(weight) > 0 ? Number(weight) : 0
  if (compact) {
    return clamp(4 + 0.9 * Math.sqrt(w), 5, 30)
  }
  return clamp(6 + 1.25 * Math.sqrt(w), 7, 46)
}

/** Edge stroke width, log-ish in count, clamped so no line dominates. */
export function edgeWidthForCount(count) {
  const c = Number(count) > 0 ? Number(count) : 1
  return clamp(0.6 + Math.log2(1 + c) * 0.28, 0.6, 4)
}

/** Recompute every node's incident weight (and radius) from the edge list. */
export function recomputeSizes(nodes, edges, compact = false) {
  for (const node of nodes) node.weight = 0
  for (const e of edges) {
    if (e.sourceNode) e.sourceNode.weight += e.count
    if (e.targetNode) e.targetNode.weight += e.count
  }
  for (const node of nodes) node.r = radiusForWeight(node.weight, compact)
}

/* -------------------------------------------------------------------------
   Identity
   ------------------------------------------------------------------------- */

/** Stable node id. Dedupe is on this: one Chrome JA4 is one circle, not many. */
export function nodeId(type, value) {
  return type === 'sni' ? `sni:${value}` : `fp:${value}`
}

/** Unordered edge key, so the same pair from two directions collapses to one. */
export function edgeKey(a, b) {
  return a < b ? `${a}|${b}` : `${b}|${a}`
}

/**
 * Deterministic [0,1) hash of a string. Spawn jitter is derived from this
 * rather than Math.random so a given seed always lays out the same way — this
 * is a view, and reproducibility beats novelty.
 */
export function hash01(str) {
  let h = 2166136261
  const s = String(str)
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return (h >>> 0) / 4294967296
}

/* -------------------------------------------------------------------------
   Simulation
   ------------------------------------------------------------------------- */

const DEFAULTS = {
  damping: 0.85,
  kRepulsion: 5200,
  kSpring: 0.035,
  kCenter: 0.012,
  kCollide: 0.22,
  restLength: 90,
  minDist: 8,
  maxVelocity: 28,
  pad: 6,
}

/**
 * One integration step. Mutates node velocities and positions in place and
 * returns the total kinetic energy, which the caller watches to decide when to
 * let the loop sleep. Fixed nodes (pinned by a drag) are held in place.
 */
export function simulationStep(nodes, edges, opts = {}) {
  const o = { ...DEFAULTS, ...opts }
  const width = o.width || 900
  const height = o.height || 560
  const cx = width / 2
  const cy = height / 2
  const n = nodes.length
  if (n === 0) return 0

  const minDist2 = o.minDist * o.minDist

  // Repulsion (Coulomb) + soft collision so big circles don't overlap. O(n²),
  // which is fine at ≤200 nodes.
  for (let i = 0; i < n; i++) {
    const a = nodes[i]
    for (let j = i + 1; j < n; j++) {
      const b = nodes[j]
      let dx = a.x - b.x
      let dy = a.y - b.y
      let d2 = dx * dx + dy * dy
      if (d2 === 0) {
        // Coincident: nudge deterministically so the pair can separate.
        dx = hash01(a.id) - 0.5 || 0.5
        dy = hash01(b.id) - 0.5 || 0.5
        d2 = dx * dx + dy * dy
      }
      const dist = Math.sqrt(d2)
      const ux = dx / dist
      const uy = dy / dist
      let force = o.kRepulsion / Math.max(d2, minDist2)
      const minSep = a.r + b.r + o.pad
      if (dist < minSep) force += o.kCollide * (minSep - dist)
      const fx = ux * force
      const fy = uy * force
      if (!a.fixed) {
        a.vx += fx
        a.vy += fy
      }
      if (!b.fixed) {
        b.vx -= fx
        b.vy -= fy
      }
    }
  }

  // Spring attraction along edges toward the rest length. Heavier edges pull a
  // little harder, clamped so a huge count doesn't collapse the pair.
  for (const e of edges) {
    const s = e.sourceNode
    const t = e.targetNode
    if (!s || !t) continue
    const dx = t.x - s.x
    const dy = t.y - s.y
    const dist = Math.sqrt(dx * dx + dy * dy) || 0.01
    const ux = dx / dist
    const uy = dy / dist
    const stiffness = o.kSpring * (1 + Math.min(0.6, Math.log2(1 + e.count) * 0.05))
    const f = stiffness * (dist - o.restLength)
    if (!s.fixed) {
      s.vx += ux * f
      s.vy += uy * f
    }
    if (!t.fixed) {
      t.vx -= ux * f
      t.vy -= uy * f
    }
  }

  // Centering pull, damping, integration.
  let energy = 0
  for (let i = 0; i < n; i++) {
    const node = nodes[i]
    if (node.fixed) {
      node.vx = 0
      node.vy = 0
      continue
    }
    node.vx += (cx - node.x) * o.kCenter
    node.vy += (cy - node.y) * o.kCenter
    node.vx *= o.damping
    node.vy *= o.damping
    node.vx = clamp(node.vx, -o.maxVelocity, o.maxVelocity)
    node.vy = clamp(node.vy, -o.maxVelocity, o.maxVelocity)
    node.x += node.vx
    node.y += node.vy
    energy += node.vx * node.vx + node.vy * node.vy
  }
  return energy
}

/** Let the loop sleep once the graph is essentially at rest. */
export function energyThreshold(nodeCount) {
  return 0.02 * Math.max(1, nodeCount)
}

function clamp(v, lo, hi) {
  return v < lo ? lo : v > hi ? hi : v
}
