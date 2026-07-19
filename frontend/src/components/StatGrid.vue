<script setup>
/**
 * A row of labelled figures, bordered as a single strip.
 *
 * items: [{ key, label, value, title? }] — value is pre-formatted by the caller.
 * A `value-<key>` slot overrides rendering for one cell (used for SpreadBar).
 */
defineProps({
  items: { type: Array, required: true },
})
</script>

<template>
  <dl class="statgrid">
    <div v-for="item in items" :key="item.key" class="cell">
      <dt :title="item.title || null">{{ item.label }}</dt>
      <dd>
        <slot :name="`value-${item.key}`" :item="item">{{ item.value }}</slot>
      </dd>
    </div>
  </dl>
</template>

<style scoped>
.statgrid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
  gap: 0;
  margin: 0;
  border: var(--border);
}

.cell {
  padding: var(--sp-3) var(--sp-4);
  border-right: var(--border);
  border-bottom: var(--border);
  min-width: 0;
}

/* Trailing borders are trimmed by the container's own border. */
.cell:last-child {
  border-right: 0;
}

dt {
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--c-fg-muted);
  margin-bottom: var(--sp-2);
}

dt[title] {
  cursor: help;
  border-bottom: 1px dotted var(--c-border);
  display: inline-block;
}

dd {
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--fs-md);
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

@media (max-width: 34rem) {
  .cell {
    border-right: 0;
  }
}
</style>
