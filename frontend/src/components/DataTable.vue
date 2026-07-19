<script setup>
/**
 * Semantic data table with its own horizontal overflow container.
 *
 * Columns are declared as:
 *   { key, label, align?: 'left'|'right', width?, mono?: bool, sortable?: bool }
 *
 * Per-cell rendering is overridable with a `cell-<key>` slot, which receives
 * { row, value, index }.
 */
import { computed } from 'vue'

const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  /** Accessible description of the table; rendered as a visually-hidden caption. */
  caption: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  error: { type: [String, Object], default: null },
  emptyText: { type: String, default: 'No rows.' },
  /** Key of the currently sorted column, if the table is sortable. */
  sortKey: { type: String, default: '' },
  /** Stable row identity; falls back to index. */
  rowKey: { type: [String, Function], default: '' },
})

const emit = defineEmits(['sort'])

const errorText = computed(() => {
  if (!props.error) return ''
  return typeof props.error === 'string' ? props.error : props.error.message || 'Request failed.'
})

const showTable = computed(() => !props.loading && !props.error && props.rows.length > 0)

function keyFor(row, index) {
  if (typeof props.rowKey === 'function') return props.rowKey(row, index)
  if (props.rowKey && row && row[props.rowKey] !== undefined) return row[props.rowKey]
  return index
}

function ariaSort(col) {
  if (!col.sortable) return undefined
  return props.sortKey === col.key ? 'descending' : 'none'
}
</script>

<template>
  <div class="datatable">
    <p v-if="loading" class="status" role="status">loading…</p>

    <p v-else-if="error" class="status status--error" role="alert">
      {{ errorText }}
    </p>

    <p v-else-if="!rows.length" class="status">{{ emptyText }}</p>

    <div v-if="showTable" class="scroll">
      <table>
        <caption v-if="caption" class="visually-hidden">{{ caption }}</caption>
        <thead>
          <tr>
            <th
              v-for="col in columns"
              :key="col.key"
              scope="col"
              :style="col.width ? { width: col.width } : null"
              :class="{ 'is-right': col.align === 'right' }"
              :aria-sort="ariaSort(col)"
            >
              <button
                v-if="col.sortable"
                type="button"
                class="sort"
                :class="{ 'is-active': sortKey === col.key }"
                @click="emit('sort', col.key)"
              >
                {{ col.label }}
              </button>
              <template v-else>{{ col.label }}</template>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in rows" :key="keyFor(row, index)">
            <td
              v-for="col in columns"
              :key="col.key"
              :class="{ 'is-right': col.align === 'right', 'is-mono': col.mono }"
            >
              <slot :name="`cell-${col.key}`" :row="row" :value="row[col.key]" :index="index">
                {{ row[col.key] }}
              </slot>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
/* Loading / error / empty occupy the same rounded surface the table would, so
   the page doesn't reflow around them. */
.datatable > .status {
  margin: 0;
  padding: var(--sp-5) var(--sp-4);
  background: var(--panel);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-panel);
}

/* The one place sideways scrolling is allowed. The radius clips the header and
   the last row, so the panel reads as a single rounded surface. */
.scroll {
  overflow-x: auto;
  background: var(--panel);
  border: var(--border-width) solid var(--line);
  border-radius: var(--radius-panel);
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-sm);
}

th,
td {
  padding: var(--row-pad) var(--sp-4);
  text-align: left;
  vertical-align: top;
  white-space: nowrap;
  border-bottom: var(--border-width) solid var(--line);
}

thead th {
  font-size: var(--fs-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-family: var(--font-mono);
  color: var(--dim);
  background: var(--panel-2);
  border-bottom: var(--border-width) solid var(--line);
  position: sticky;
  top: 0;
}

tbody tr:last-child td {
  border-bottom: 0;
}

tbody tr td {
  transition: background-color var(--transition);
}

tbody tr:hover td {
  background: var(--panel-2);
}

.is-right {
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono);
}

.is-mono {
  font-family: var(--font-mono);
}

.sort {
  font: inherit;
  color: inherit;
  letter-spacing: inherit;
  text-transform: inherit;
  background: none;
  border: 0;
  padding: 0;
  cursor: pointer;
  transition: color var(--transition);
}

.sort:hover {
  color: var(--text);
}

/* The single active state gets the accent. */
.sort.is-active {
  color: var(--link);
}

.sort.is-active::after {
  content: " \2193"; /* down arrow — descending */
}
</style>
