const Icon = ({ name, size = 14, className }) => {
  const props = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.5,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    className,
    'aria-hidden': 'true',
  }

  switch (name) {
    case 'folder':
      return (
        <svg {...props}>
          <path d="M4 7.5a2.5 2.5 0 0 1 2.5-2.5H10l2 2h7.5a2.5 2.5 0 0 1 2.5 2.5v8a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3z" />
        </svg>
      )
    case 'folder-open':
      return (
        <svg {...props}>
          <path d="M4 8a3 3 0 0 1 3-3h3.5l2 2H20a2 2 0 0 1 2 2" />
          <path d="M3 10.5h19l-1.8 7a3 3 0 0 1-2.9 2.2H6.2A3 3 0 0 1 3.3 17z" />
        </svg>
      )
    case 'file':
      return (
        <svg {...props}>
          <path d="M7 3.5h7l4.5 4.5v12.5a2 2 0 0 1-2 2H7.5a2 2 0 0 1-2-2V5.5a2 2 0 0 1 2-2z" />
          <path d="M14 3.5V8h4.5" />
        </svg>
      )
    case 'compass':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="9.2" />
          <path d="M15.6 8.4 13 13l-4.6 2.6L11 11z" />
        </svg>
      )
    case 'chart':
      return (
        <svg {...props}>
          <path d="M4 19.5h16" />
          <path d="M7.5 16.5v-5.5" />
          <path d="M12 16.5V7.5" />
          <path d="M16.5 16.5v-8.5" />
        </svg>
      )
    case 'target':
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="8.5" />
          <circle cx="12" cy="12" r="4.5" />
          <circle cx="12" cy="12" r="1.8" />
        </svg>
      )
    case 'bot':
      return (
        <svg {...props}>
          <rect x="5" y="7.5" width="14" height="9.5" rx="2.5" />
          <path d="M9 7.5V5.5a3 3 0 0 1 6 0v2" />
          <circle cx="9.5" cy="12.2" r="1.2" />
          <circle cx="14.5" cy="12.2" r="1.2" />
        </svg>
      )
    case 'book':
      return (
        <svg {...props}>
          <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4H13a3.5 3.5 0 0 1 3.5 3.5V20H6.5A2.5 2.5 0 0 1 4 17.5z" />
          <path d="M16.5 7.5H19a2 2 0 0 1 2 2V20h-4.5" />
        </svg>
      )
    case 'flask':
      return (
        <svg {...props}>
          <path d="M9 3.5h6" />
          <path d="M10 3.5v5.2l-4.2 7.9a3.2 3.2 0 0 0 2.8 4.7h7a3.2 3.2 0 0 0 2.8-4.7L14 8.7V3.5" />
        </svg>
      )
    case 'archive':
      return (
        <svg {...props}>
          <rect x="3" y="4.5" width="18" height="5.5" rx="2" />
          <path d="M6 10v7.5a2.5 2.5 0 0 0 2.5 2.5h7A2.5 2.5 0 0 0 18 17.5V10" />
          <path d="M10 14.5h4" />
        </svg>
      )
    default:
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="9" />
        </svg>
      )
  }
}

export default Icon
