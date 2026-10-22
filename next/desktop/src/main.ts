import '@fontsource/montserrat/latin-300.css'
import '@fontsource/montserrat/latin-400.css'
import '@fontsource/montserrat/latin-500.css'
import '@fontsource/montserrat/latin-600.css'
import '@fontsource/montserrat/latin-700.css'
import '@fontsource/jetbrains-mono/latin-400.css'
import '@fontsource/jetbrains-mono/latin-500.css'
import '@fontsource/jetbrains-mono/latin-700.css'
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
