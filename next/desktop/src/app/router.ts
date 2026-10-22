import { createMemoryHistory, createRouter, createWebHistory, type RouterHistory } from 'vue-router'

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({
    history,
    routes: [
      { path: '/', redirect: '/tasks' },
      {
        path: '/tasks',
        name: 'tasks',
        component: () => import('@/features/tasks/TasksPage.vue'),
      },
      {
        path: '/work-items',
        name: 'work-items',
        component: () => import('@/features/work-items/WorkItemsPage.vue'),
      },
      {
        path: '/ai',
        name: 'ai',
        component: () => import('@/features/ai/AiSessionsPage.vue'),
      },
      { path: '/:pathMatch(.*)*', redirect: '/tasks' },
    ],
  })
}

export function createTestRouter() {
  return createAppRouter(createMemoryHistory())
}
