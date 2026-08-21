import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import FullScreenLoader from './components/FullScreenLoader.jsx'
import Icon from './Icon.jsx'
import { NAV } from './nav.jsx'

const TITLES = {
  '/today': 'My today',
  '/appointments': 'Appointments',
  '/cases': 'Cases',
  '/team': 'Team',
  '/referrals/new': 'New referral',
  '/cases/new': 'New case',
}

function Layout() {
  const { pathname } = useLocation()
  const isNewReferral = pathname === '/referrals/new'
  const isCaseDetail = pathname.startsWith('/cases/')
  const title =
    TITLES[pathname] ?? (isCaseDetail ? 'Case detail' : 'OpBook360')

  return (
    <div className="shell">
      <FullScreenLoader />
      <nav className="sidenav" aria-label="Main">
        <Link to="/today" className="brand">
          <span className="brand-mark">OB</span>
          <span>
            <span className="brand-name">OpBook360</span>
            <br />
            <span className="brand-sub">Clinic workspace</span>
          </span>
        </Link>

        <div className="nav-label">Workspace</div>
        <ul className="nav-list">
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink to={item.to} className="nav-item">
                <Icon d={item.icon} />
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>

        <div className="nav-foot">
          <span className="avatar">VR</span>
          <span>
            <span className="nav-foot-name">Vigneshwaran</span>
            <br />
            <span className="nav-foot-sub">Clinic lead</span>
          </span>
        </div>
      </nav>

      <div className="main">
        <header className="topbar">
          <h1>{title}</h1>
          <div className="topbar-actions">
            {isNewReferral || isCaseDetail ? (
              <Link to="/cases" className="btn">
                Back to cases
              </Link>
            ) : (
              <Link to="/referrals/new" className="btn btn-primary">
                New referral
              </Link>
            )}
          </div>
        </header>

        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default Layout
