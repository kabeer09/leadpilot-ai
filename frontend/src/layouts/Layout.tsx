import { Outlet, NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Users,
  Building2,
  BarChart3,
  Settings,
  Rocket,
  Globe,
  Briefcase,
  Database,
  Bot,
} from 'lucide-react'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/leads', icon: Users, label: 'Leads' },
  { to: '/companies', icon: Building2, label: 'Companies' },
  { to: '/automation', icon: Bot, label: 'Automation' },
  { to: '/import', icon: Globe, label: 'Add Website' },
  { to: '/jobs', icon: Briefcase, label: 'Crawl Jobs' },
  { to: '/sources', icon: Database, label: 'Sources' },
  { to: '/analytics', icon: BarChart3, label: 'Analytics' },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

export default function Layout() {
  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className="w-64 border-r border-gray-200 bg-white">
        <div className="flex h-16 items-center gap-2 border-b border-gray-200 px-6">
          <Rocket className="h-6 w-6 text-primary-600" />
          <span className="text-lg font-bold text-gray-900">LeadPilot AI</span>
        </div>
        <nav className="space-y-1 p-4">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-primary-50 text-primary-700'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                }`
              }
            >
              <item.icon className="h-5 w-5" />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto bg-gray-50">
        <div className="p-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
