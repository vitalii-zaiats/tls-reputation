import { createApp } from 'vue'

// Fonts first: base.css names the families, fonts.css defines them.
import './assets/fonts.css'
import './assets/base.css'
import App from './App.vue'
import router from './router.js'

createApp(App).use(router).mount('#app')
