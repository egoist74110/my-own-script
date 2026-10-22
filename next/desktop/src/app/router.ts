import { createMemoryHistory, createRouter, createWebHistory, type RouterHistory } from 'vue-router'

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({
    history,
    routes: [
      {
        path: '/',
        name: 'overview',
        component: () => import('@/features/overview/OverviewPage.vue'),
      },
      { path: '/:pathMatch(.*)*', redirect: '/' },
    ],
  })
}

export function createTestRouter() {
  return createAppRouter(createMemoryHistory())
}
