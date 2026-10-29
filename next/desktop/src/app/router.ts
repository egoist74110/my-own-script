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
      {
        // /settings/:tab? —— 分区可直达；vpn 落在“服务”分区并滚到 VPN 卡片。未知分区走兜底重定向。
        path: '/settings/:tab(import|ado|repos|credentials|telegram|ai|mcp|services|vpn|general)?',
        name: 'settings',
        component: () => import('@/features/settings/SettingsPage.vue'),
      },
      { path: '/:pathMatch(.*)*', redirect: '/tasks' },
    ],
  })
}

export function createTestRouter() {
  return createAppRouter(createMemoryHistory())
}
