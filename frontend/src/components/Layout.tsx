import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api, User } from '../api'

export function Layout() {
  const [user, setUser] = useState<User | null>(null)

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser({ authenticated: false }))
  }, [])

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">AI PR Review</div>
        {user?.authenticated ? (
          <nav className="nav">
            <NavLink to="/dashboard">Dashboard</NavLink>
            <NavLink to="/history">History</NavLink>
            <NavLink to="/jobs">Jobs</NavLink>
            <span className="user">@{user.github_login}</span>
            <a href="/auth/logout" className="logout">Logout</a>
          </nav>
        ) : (
          <a href="/auth/login" className="login-link">Login with GitHub</a>
        )}
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  )
}