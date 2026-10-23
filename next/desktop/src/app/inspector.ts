import type { InjectionKey, Ref } from 'vue'

/** App 壳里检查器容器元素的 ref；页面经 Inspector Teleport 进来。 */
export const inspectorHostKey: InjectionKey<Ref<HTMLElement | null>> = Symbol('inspector-host')
