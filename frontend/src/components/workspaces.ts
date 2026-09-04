/** The app's information architecture: six workspaces, each owning a small
 * set of pages. The command bar switches workspaces; the sub-rail switches
 * pages inside one. Routes are unchanged — this is pure navigation shape. */

export interface WsPage {
  to: string
  label: string
  end?: boolean
}

export interface Workspace {
  key: string
  label: string
  pages: WsPage[]
  /** Route prefixes (besides the pages) that belong to this workspace. */
  extra?: string[]
  creatorOnly?: boolean
  /** Money / payout workspaces are hidden from recruiters (field staff). */
  noRecruiter?: boolean
}

export const WORKSPACES: Workspace[] = [
  {
    key: 'operate',
    label: 'Operate',
    pages: [
      { to: '/', label: 'Process Payout', end: true },
      { to: '/corrections', label: 'Corrections' },
    ],
    noRecruiter: true,
  },
  {
    key: 'analytics',
    label: 'Analytics',
    pages: [{ to: '/dashboard', label: 'Dashboard' }],
    noRecruiter: true,
  },
  {
    key: 'people',
    label: 'People',
    pages: [
      { to: '/riders', label: 'Riders' },
      { to: '/inactive', label: 'Inactive' },
    ],
    extra: ['/persons'],
  },
  {
    key: 'fleet',
    label: 'Fleet',
    pages: [
      { to: '/evs', label: 'EVs' },
      { to: '/ev-rent', label: 'Rent Ledger' },
    ],
    extra: ['/raft', '/blive'],
  },
  {
    key: 'money',
    label: 'Money',
    pages: [
      { to: '/arrears', label: 'Arrears' },
      { to: '/cod', label: 'COD' },
      { to: '/payments', label: 'Payments' },
      { to: '/transactions', label: 'Transactions' },
    ],
    noRecruiter: true,
  },
  {
    key: 'admin',
    label: 'Admin',
    pages: [
      { to: '/users', label: 'Users' },
      { to: '/settings', label: 'Settings' },
    ],
    extra: ['/system'],
    noRecruiter: true,
  },
]

/** Recruiters see riders and the fleet; '/inactive' is a money view. */
const RECRUITER_HIDDEN_PAGES = new Set(['/inactive'])

/** The workspaces (and pages) a role may use. */
export function workspacesFor(role: string | undefined): Workspace[] {
  if (role !== 'recruiter') return WORKSPACES
  return WORKSPACES.filter((ws) => !ws.noRecruiter).map((ws) => ({
    ...ws,
    pages: ws.pages.filter((p) => !RECRUITER_HIDDEN_PAGES.has(p.to)),
  }))
}

/** Where a role lands after login / on a route it may not use. */
export function homeFor(role: string | undefined): string {
  return role === 'recruiter' ? '/riders' : '/'
}

/** May this role open this pathname? */
export function canVisit(role: string | undefined, pathname: string): boolean {
  if (role !== 'recruiter') return true
  const ws = workspaceFor(pathname)
  if (ws.noRecruiter) return false
  return !RECRUITER_HIDDEN_PAGES.has(pathname)
}

/** Which workspace owns this pathname. */
export function workspaceFor(pathname: string): Workspace {
  for (const ws of WORKSPACES) {
    for (const p of ws.pages) {
      if (p.end ? pathname === p.to : pathname === p.to || pathname.startsWith(p.to + '/')) {
        return ws
      }
    }
    for (const ex of ws.extra ?? []) {
      if (pathname === ex || pathname.startsWith(ex + '/')) return ws
    }
  }
  return WORKSPACES[0]
}

const WS_PREFIX = 'wsmem:'

/** Remember the exact URL you were on inside a workspace, so switching back
 * lands where you left off (not on its first page). */
export function rememberWorkspaceUrl(wsKey: string, url: string) {
  try {
    sessionStorage.setItem(WS_PREFIX + wsKey, url)
  } catch {
    /* ignore */
  }
}

export function workspaceUrl(ws: Workspace): string {
  try {
    const saved = sessionStorage.getItem(WS_PREFIX + ws.key)
    if (saved) return saved
  } catch {
    /* ignore */
  }
  return ws.pages[0].to
}
