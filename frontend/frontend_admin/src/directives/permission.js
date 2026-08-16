import { useUserStore } from '../store/user'

/**
 * v-permission 指令：按钮级权限控制。
 * 用法： v-permission="'system:user:add'"  或  v-permission="['system:user:add','system:user:edit']"
 * 无权限则从 DOM 移除元素。admin(*:*:*) 放行。
 */
function hasPermission(value) {
  const store = useUserStore()
  const perms = store.perms || []
  if (perms.includes('*:*:*')) return true
  const need = Array.isArray(value) ? value : [value]
  return need.some((p) => perms.includes(p))
}

export default {
  mounted(el, binding) {
    if (!hasPermission(binding.value)) {
      el.parentNode && el.parentNode.removeChild(el)
    }
  }
}
