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
  <section class="st-section" aria-label="本机网络" data-testid="network-bar">
    <div class="st-head"><h2>本机网络</h2></div>
    <div class="st-row">
      <div class="st-lbl">
        <b>VPN IP</b>
        <small>接入公司 VPN 后分配的地址</small>
      </div>
      <span v-if="network?.vpn_ip" class="st-mono net-val" data-testid="vpn-ip">
        {{ network.vpn_ip }}
      </span>
      <span v-else class="st-val" data-testid="vpn-ip-missing">未检测到</span>
      <Button v-if="network?.vpn_ip" size="sm" data-testid="copy-vpn-btn" @click="onCopyVpn">
        {{ vpnCopied ? '已复制' : '复制' }}
      </Button>
    </div>

    <div class="st-row">
      <div class="st-lbl">
        <b>局域网 IP</b>
        <small>同一网络里的其他设备用它访问本机</small>
      </div>
      <Tag v-if="network?.on_lan" data-testid="on-lan-tag">局域网在线</Tag>
      <span v-if="network?.lan_ip" class="st-mono net-val" data-testid="lan-ip">
        {{ network.lan_ip }}
      </span>
      <span v-else class="st-val" data-testid="lan-ip-missing">未检测到</span>
      <Button v-if="network?.lan_ip" size="sm" data-testid="copy-lan-btn" @click="onCopyLan">
        {{ lanCopied ? '已复制' : '复制' }}
      </Button>
    </div>
  </section>
</template>

<style scoped>
.net-val {
  font-weight: 600;
  color: var(--ink);
}
</style>
