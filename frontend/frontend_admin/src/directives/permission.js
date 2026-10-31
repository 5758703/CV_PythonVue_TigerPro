import { useUserStore } from '../store/user'

/**
 * v-permission 指令：按钮级权限控制。
 * 用法： v-permission="'system:user:add'"  或  v-permission="['system:user:add','system:user:edit']"
 * 无权限则从 DOM 移除元素。admin(*:*:*) 放行。
 */
function hasPermission(value) {
  const store = useUserStore()
  return store.hasPerm(value)
}

export default {
  mounted(el, binding) {
    if (!hasPermission(binding.value)) {
      el.style.display = 'none'
    }
  },
  updated(el, binding) {
    el.style.display = hasPermission(binding.value) ? '' : 'none'
  }
}
