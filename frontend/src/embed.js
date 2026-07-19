/**
 * Auto-height for embedded widgets.
 *
 * An iframe's height is fixed by the parent page; content inside cannot grow
 * it. So a content-sized widget (the ALPN chart, not the fixed-viewport graph)
 * measures itself and posts its height to the parent, which resizes the frame.
 * The parent verifies the message origin — see the snippet in the docs — so
 * this is a one-way size hint, not a channel anyone can drive.
 *
 * Returns a teardown function; call it on unmount.
 */
export function reportEmbedHeight(getEl) {
  // Not framed, or no parent to talk to: nothing to do.
  if (typeof window === 'undefined' || window.parent === window) {
    return () => {}
  }

  let last = -1
  const post = () => {
    const el = getEl()
    if (!el) return
    const height = Math.ceil(el.getBoundingClientRect().height)
    if (height && height !== last) {
      last = height
      window.parent.postMessage({ type: 'tlsrep-embed-height', height }, '*')
    }
  }

  const observer = new ResizeObserver(post)
  const el = getEl()
  if (el) observer.observe(el)
  // Fonts landing after first paint change the height; catch that too.
  window.addEventListener('load', post)
  post()

  return () => {
    observer.disconnect()
    window.removeEventListener('load', post)
  }
}
