import { createRouter, createWebHistory } from 'vue-router'
import TradesView from '../views/TradesView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'trades',
      component: TradesView
    },
  ]
})

export default router
