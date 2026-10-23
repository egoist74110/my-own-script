import './design/app.css'

import { VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './app/App.vue'
import { backendRuntimeKey, createBackendRuntime } from './app/backend-runtime'
import { createAppRouter } from './app/router'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(VueQueryPlugin)
app.use(createAppRouter())

const runtime = createBackendRuntime()
app.provide(backendRuntimeKey, runtime)
app.mount('#app')
runtime.start()
