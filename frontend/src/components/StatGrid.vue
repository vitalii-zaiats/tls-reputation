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
/* Separate cards rather than one bordered strip — the corners need the room. */
.statgrid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
  gap: var(--sp-3);
  margin: 0;
}

.cell {
  padding: var(--sp-4);
  background: var(--panel);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-card);
  min-width: 0;
}

dt {
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-family: var(--font-mono);
  color: var(--dim);
  margin-bottom: var(--sp-2);
}

dt[title] {
  cursor: help;
  border-bottom: 1px dotted var(--line-strong);
  display: inline-block;
}

dd {
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--fs-md);
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}
</style>
