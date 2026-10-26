<script setup lang="ts">
import { ref } from 'vue'
import Button from '@/components/Button.vue'
import Tag from '@/components/Tag.vue'
import type { NetworkInfo } from './api'

const props = defineProps<{
  network?: NetworkInfo
}>()

const vpnCopied = ref(false)
const lanCopied = ref(false)

async function onCopyVpn() {
  const ip = props.network?.vpn_ip
  if (!ip) return
  try {
    await navigator.clipboard.writeText(ip)
    vpnCopied.value = true
    setTimeout(() => {
      vpnCopied.value = false
    }, 2000)
  } catch {
    // 忽略剪贴板写入异常
  }
}

async function onCopyLan() {
  const ip = props.network?.lan_ip
  if (!ip) return
  try {
    await navigator.clipboard.writeText(ip)
    lanCopied.value = true
    setTimeout(() => {
      lanCopied.value = false
    }, 2000)
  } catch {
    // 忽略剪贴板写入异常
  }
}
</script>

<template>
  <div class="network-bar" data-testid="network-bar">
    <div class="net-item">
      <span class="net-label">VPN IP：</span>
      <span v-if="network?.vpn_ip" class="st-mono net-val" data-testid="vpn-ip">
        {{ network.vpn_ip }}
      </span>
      <span v-else class="net-missing" data-testid="vpn-ip-missing">未检测到</span>
      <Button
        v-if="network?.vpn_ip"
        size="sm"
        data-testid="copy-vpn-btn"
        class="copy-btn"
        @click="onCopyVpn"
      >
        {{ vpnCopied ? '已复制' : '复制' }}
      </Button>
    </div>

    <div class="net-divider" aria-hidden="true"></div>

    <div class="net-item">
      <span class="net-label">局域网 IP：</span>
      <span v-if="network?.lan_ip" class="st-mono net-val" data-testid="lan-ip">
        {{ network.lan_ip }}
      </span>
      <span v-else class="net-missing" data-testid="lan-ip-missing">未检测到</span>
      <Tag v-if="network?.on_lan" class="ml-1" data-testid="on-lan-tag">局域网在线</Tag>
      <Button
        v-if="network?.lan_ip"
        size="sm"
        data-testid="copy-lan-btn"
        class="copy-btn"
        @click="onCopyLan"
      >
        {{ lanCopied ? '已复制' : '复制' }}
      </Button>
    </div>
  </div>
</template>

<style scoped>
.network-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 16px;
  background: var(--bg-window);
  border: 1px solid var(--line);
  border-radius: var(--radius-group);
  margin-bottom: 12px;
  font-size: var(--text-base);
}
.net-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.net-label {
  color: var(--mute);
  font-weight: 500;
}
.net-val {
  font-weight: 600;
  color: var(--fg);
}
.net-missing {
  color: var(--mute);
  font-style: normal;
}
.net-divider {
  width: 1px;
  height: 16px;
  background: var(--line);
}
.copy-btn {
  padding: 0 8px;
  height: 22px;
  font-size: 11px;
}
.ml-1 {
  margin-left: 4px;
}
</style>
