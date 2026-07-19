<script setup>
/** Offset/limit pager. Emits `update` with the new offset. */
import { computed } from 'vue'
import { formatInt } from '../format.js'

const props = defineProps({
  offset: { type: Number, required: true },
  limit: { type: Number, required: true },
  total: { type: Number, default: 0 },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update'])

const from = computed(() => (props.total === 0 ? 0 : props.offset + 1))
const to = computed(() => Math.min(props.offset + props.limit, props.total))
const canPrev = computed(() => !props.disabled && props.offset > 0)
const canNext = computed(() => !props.disabled && props.offset + props.limit < props.total)

const label = computed(() =>
  props.total === 0
    ? 'no rows'
    : `${formatInt(from.value)}–${formatInt(to.value)} of ${formatInt(props.total)}`,
)

function prev() {
  emit('update', Math.max(0, props.offset - props.limit))
}

function next() {
  emit('update', props.offset + props.limit)
}
</script>

<template>
  <nav class="pager" aria-label="Pagination">
    <span class="range nums">{{ label }}</span>
    <span class="buttons">
      <button type="button" class="control" :disabled="!canPrev" @click="prev">
        &larr; prev
      </button>
      <button type="button" class="control" :disabled="!canNext" @click="next">
        next &rarr;
      </button>
    </span>
  </nav>
</template>

<style scoped>
.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  flex-wrap: wrap;
  margin-top: var(--sp-3);
}

.range {
  font-size: var(--fs-xs);
  color: var(--c-fg-muted);
}

.buttons {
  display: inline-flex;
}

.buttons .control + .control {
  margin-left: -1px;
}
</style>
