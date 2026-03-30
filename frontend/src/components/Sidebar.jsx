const Sidebar = ({ children, style, className }) => (
  <aside className={['sidebar', className].filter(Boolean).join(' ')} style={style}>
    {children}
  </aside>
)

export default Sidebar
