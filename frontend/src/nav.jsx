export const NAV = [
  {
    to: '/today',
    label: 'My today',
    icon: (
      <>
        <path d="M4 5h16v15H4z" />
        <path d="M4 10h16" />
        <path d="M9 14h6" />
      </>
    ),
  },
  {
    to: '/appointments',
    label: 'Appointments',
    icon: (
      <>
        <path d="M4 6h16v14H4z" />
        <path d="M8 3v4M16 3v4M4 11h16" />
      </>
    ),
  },
  {
    to: '/cases',
    label: 'Cases',
    icon: (
      <>
        <path d="M4 7h16v13H4z" />
        <path d="M9 7V4h6v3" />
      </>
    ),
  },
  {
    to: '/team',
    label: 'Team',
    icon: (
      <>
        <circle cx="9" cy="9" r="3" />
        <path d="M3 19c0-3 2.7-5 6-5s6 2 6 5" />
        <path d="M16 7a3 3 0 0 1 0 6M17 14c2.4.5 4 2.4 4 5" />
      </>
    ),
  },
  {
    to: '/contacts',
    label: 'Contacts',
    icon: (
      <>
        <path d="M6 3h11a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6z" />
        <path d="M3 7h3M3 12h3M3 17h3" />
        <circle cx="12" cy="10" r="2" />
        <path d="M9 16c0-1.7 1.3-3 3-3s3 1.3 3 3" />
      </>
    ),
  },
]
