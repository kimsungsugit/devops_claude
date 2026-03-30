import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './start.css'
import StartPage from './StartPage.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <StartPage />
  </StrictMode>,
)
