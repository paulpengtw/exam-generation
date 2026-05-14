import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import ErrorBoundary from './components/ErrorBoundary.tsx'
import { useLangStore } from './store/langStore.ts'

// Keep <html lang> in sync with persisted language choice
useLangStore.subscribe((state) => {
  document.documentElement.lang = state.lang;
});
document.documentElement.lang = useLangStore.getState().lang;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
