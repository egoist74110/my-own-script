<script setup lang="ts">
import { computed, inject, provide } from 'vue'
import Banner from '@/components/Banner.vue'
import CloudflaredCard from './CloudflaredCard.vue'
import CodeServerCard from './CodeServerCard.vue'
import NetworkBar from './NetworkBar.vue'
import VpnCard from './VpnCard.vue'
import { settingsContextKey } from './useSettings'
import { servicesContextKey, useServices } from './useServices'
import { vpnContextKey, useVpn } from './useVpn'

const ctx = inject(settingsContextKey, null)
const services = useServices()
provide(servicesContextKey, services)

const vpn = useVpn()
provide(vpnContextKey, vpn)

const snapshot = computed(() => services.snapshot.value)
const codeServer = computed(() => snapshot.value?.code_server)
const cloudflared = computed(() => snapshot.value?.cloudflared)
const network = computed(() => snapshot.value?.network)
const codeServerBinary = computed(() => snapshot.value?.binaries?.code_server)
const cloudflaredBinary = computed(() => snapshot.value?.binaries?.cloudflared)
const codeServerSettings = computed(() => snapshot.value?.settings?.code_server)
const cloudflaredSettings = computed(() => snapshot.value?.settings?.cloudflared)
</script>

<template>
  <div class="st-body" data-testid="services-tab">
    <Banner v-if="services.error.value" kind="error" data-testid="services-global-error">
      {{ services.error.value }}
    </Banner>

    <!-- 顶部网络信息条：VPN IP、局域网 IP（只读，缺失显示“未检测到”，复制按钮） -->
    <NetworkBar :network="network" />

    <!-- VPN 卡 -->
    <VpnCard
      :snapshot="vpn.snapshot.value"
      :busy="ctx?.busy.value"
      :writable="ctx?.writable.value"
    />

    <!-- code-server 卡 -->
    <CodeServerCard
      :service="codeServer"
      :binary="codeServerBinary"
      :settings="codeServerSettings"
      :busy="ctx?.busy.value"
      :writable="ctx?.writable.value"
    />

    <!-- cloudflared 卡 -->
    <CloudflaredCard
      :cloudflared="cloudflared"
      :binary="cloudflaredBinary"
      :settings="cloudflaredSettings"
      :busy="ctx?.busy.value"
      :writable="ctx?.writable.value"
    />
  </div>
</template>
