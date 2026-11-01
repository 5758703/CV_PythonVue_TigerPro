// Shared header interaction for Element Plus and native result tables.
// Column widths live only with the mounted table; no cross-page storage keys.
export const minimumColumnWidth = 36

export function resizedWidth(start, delta) {
  return Math.max(minimumColumnWidth, Math.round(start + delta))
}

export function attachColumnResize(root, adapter) {
  const handles = new Map()
  let frame = 0, dragFrame = 0, active = null, disposed = false
  const schedule = () => {
    if (!frame && !disposed) frame = requestAnimationFrame(() => { frame = 0; sync() })
  }
  const sync = () => {
    const columns = adapter.headers()
    const live = new Set(columns.map(c => c.cell))
    for (const [cell, item] of handles) {
      if (!live.has(cell) || !cell.contains(item.handle)) {
        if (active?.cell === cell) finish(true)
        item.remove(); handles.delete(cell)
      }
    }
    columns.forEach((column, index) => {
      const { cell } = column
      if (handles.has(cell)) { handles.get(cell).column = column; return }
      const handle = document.createElement('span')
      handle.className = 'tiger-column-resize-handle'
      handle.tabIndex = 0
      handle.setAttribute('role', 'separator')
      handle.setAttribute('aria-orientation', 'vertical')
      handle.setAttribute('aria-label', `调整${cell.textContent.trim() || `第 ${index + 1}`}列宽`)
      handle.setAttribute('title', '拖动调整列宽；也可用左右方向键调整')
      handle.setAttribute('data-html2canvas-ignore', 'true')
      const position = cell.style.position
      if (getComputedStyle(cell).position === 'static') cell.style.position = 'relative'
      const item = { column, handle, remove: () => { handle.remove(); cell.style.position = position } }
      handle.addEventListener('pointerdown', event => {
        if (event.button !== 0 || active) return
        event.preventDefault(); event.stopPropagation()
        const start = cell.getBoundingClientRect().width
        const write = adapter.begin(item.column)
        if (!write) return
        active = { cell, write, start, x: event.clientX, pointerId: event.pointerId, width: start }
        document.documentElement.classList.add('tiger-resizing-column')
        document.addEventListener('pointermove', move)
        document.addEventListener('pointerup', up)
        document.addEventListener('pointercancel', cancel)
        window.addEventListener('blur', cancel)
      })
      // Header sorting/selection must not run after a drag or keyboard adjustment.
      for (const name of ['click', 'dblclick', 'mousedown']) handle.addEventListener(name, event => event.stopPropagation())
      handle.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return
        event.preventDefault(); event.stopPropagation()
        const write = adapter.begin(item.column)
        if (write) write(resizedWidth(cell.getBoundingClientRect().width,
          (event.key === 'ArrowLeft' ? -1 : 1) * (event.shiftKey ? 50 : 10)))
      })
      cell.appendChild(handle)
      handles.set(cell, item)
    })
  }
  const move = event => {
    if (!active || event.pointerId !== active.pointerId) return
    active.width = resizedWidth(active.start, event.clientX - active.x)
    if (!dragFrame) dragFrame = requestAnimationFrame(() => {
      dragFrame = 0
      if (active) active.write(active.width)
    })
  }
  const finish = cancelled => {
    if (dragFrame) cancelAnimationFrame(dragFrame)
    dragFrame = 0
    if (active) active.write(cancelled ? active.start : active.width)
    active = null
    document.documentElement.classList.remove('tiger-resizing-column')
    document.removeEventListener('pointermove', move)
    document.removeEventListener('pointerup', up)
    document.removeEventListener('pointercancel', cancel)
    window.removeEventListener('blur', cancel)
  }
  const up = event => { if (active && event.pointerId === active.pointerId) { move(event); finish(false) } }
  const cancel = () => finish(true)
  const observer = new MutationObserver(schedule)
  observer.observe(root, { childList: true, subtree: true })
  schedule()
  return () => {
    disposed = true
    observer.disconnect()
    cancelAnimationFrame(frame)
    if (active) finish(true)
    for (const item of handles.values()) item.remove()
    handles.clear()
    adapter.dispose?.()
  }
}

export function nativeTableAdapter(table) {
  let colgroup = null
  const initial = { width: table.style.width, minWidth: table.style.minWidth, tableLayout: table.style.tableLayout }
  const cells = () => Array.from((table.tHead?.rows[0] || table.rows[0])?.cells || [])
  return {
    headers: () => cells().filter(cell => cell.colSpan === 1).map(cell => ({ cell })),
    begin: ({ cell }) => {
      const header = cells()
      if (header.some(c => c.colSpan !== 1)) return null
      const widths = header.map(c => c.getBoundingClientRect().width)
      const index = header.indexOf(cell)
      if (index < 0 || widths.some(w => w <= 0)) return null
      if (!colgroup) { colgroup = document.createElement('colgroup'); table.prepend(colgroup) }
      colgroup.replaceChildren(...widths.map(() => document.createElement('col')))
      table.style.tableLayout = 'fixed'
      table.style.minWidth = '0'
      return width => {
        widths[index] = width
        widths.forEach((w, i) => { colgroup.children[i].style.width = `${w}px` })
        table.style.width = `${widths.reduce((a, b) => a + b, 0)}px`
      }
    },
    dispose: () => { colgroup?.remove(); Object.assign(table.style, initial) }
  }
}
