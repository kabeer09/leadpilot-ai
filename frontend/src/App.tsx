import { Routes, Route } from 'react-router-dom'
import Layout from './layouts/Layout'
import Dashboard from './pages/Dashboard'
import Leads from './pages/Leads'
import Companies from './pages/Companies'
import CompanyProfile from './pages/CompanyProfile'
import AddWebsite from './pages/AddWebsite'
import CrawlJobs from './pages/CrawlJobs'
import Sources from './pages/Sources'
import Analytics from './pages/Analytics'
import Settings from './pages/Settings'
import LeadDetail from './pages/LeadDetail'
import Automation from './pages/Automation'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="leads" element={<Leads />} />
        <Route path="leads/:id" element={<LeadDetail />} />
        <Route path="companies" element={<Companies />} />
        <Route path="companies/:id" element={<CompanyProfile />} />
        <Route path="import" element={<AddWebsite />} />
        <Route path="jobs" element={<CrawlJobs />} />
        <Route path="sources" element={<Sources />} />
        <Route path="automation" element={<Automation />} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}
