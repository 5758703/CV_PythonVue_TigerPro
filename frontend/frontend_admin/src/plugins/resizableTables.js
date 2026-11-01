import { unref } from 'vue'
import { attachColumnResize, nativeTableAdapter } from '../utils/tableColumnResize'
import '../styles/resizableTables.css'

export default {
  install(app) {
    const cleanups = new WeakMap()
    // Element Plus exposes its leaf columns and doLayout. Use its own column
    // width model so fixed columns, horizontal scrolling and body cells agree.
    app.mixin({
      mounted() {
        if (this.$options.name !== 'ElTable') return
        const table = this.$.exposed
        const root = this.$el
        cleanups.set(this, attachColumnResize(root, {
          headers: () => {
            const columns = unref(table.columns) || []
            return Array.from(root.querySelectorAll('thead th')).flatMap(cell => {
              if (cell.closest('.el-table') !== root) return []
              const column = columns.find(c => cell.classList.contains(c.id))
              return column && !column.children?.length ? [{ cell, column }] : []
            })
          },
          begin: ({ column }) => width => {
            column.width = column.realWidth = width
            table.doLayout()
          }
        }))
      },
      beforeUnmount() { cleanups.get(this)?.(); cleanups.delete(this) }
    })
    app.directive('resizable-columns', {
      mounted(el) { cleanups.set(el, attachColumnResize(el, nativeTableAdapter(el))) },
      beforeUnmount(el) { cleanups.get(el)?.(); cleanups.delete(el) }
    })
  }
}
