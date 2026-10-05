<template>
  <div class="app-root">
    <Navbar />
    <router-view />
  </div>
</template>

<script setup lang="ts">
import Navbar from '@/components/Navbar.vue'
</script>

<style>
.app-root {
  min-height: 100vh;
}
</style>
