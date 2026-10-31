import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/inter'
import '@fontsource-variable/geist-mono'
import './styles/app.css' // 旧样式 index.css 由 app.css 以 legacy 层引入
import App from './App.tsx'
import { initTheme } from './theme'
import { BRAND } from './brand'
import { I18nProvider } from './i18n'
import { Toaster } from './components/ui/sonner'
import { TooltipProvider } from './components/ui/tooltip'

document.title = BRAND.title
initTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nProvider>
      <TooltipProvider delayDuration={200}>
        <App />
        <Toaster position="bottom-right" />
      </TooltipProvider>
    </I18nProvider>
  </StrictMode>,
)
