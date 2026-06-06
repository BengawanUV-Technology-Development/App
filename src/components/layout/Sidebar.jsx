const navItems = [
  { id: "dashboard", label: "Flight Data" },
  { id: "logs", label: "Messages" },
];

function Sidebar({ activeView, onNavigate }) {
  return (
    <aside className="sidebar" aria-label="Primary navigation">
      <div className="sidebar-brand">
        <span className="brand-mark">BUV</span>
        <strong className="brand-text">Ground Control</strong>
      </div>
      <nav className="nav-list">
        {navItems.map((item) => (
          <button
            key={item.id}
            className={`nav-item ${activeView === item.id ? "is-active" : ""}`}
            type="button"
            onClick={() => onNavigate(item.id)}
            aria-current={activeView === item.id ? "page" : undefined}
          >
            <span className="nav-label">{item.label}</span>
          </button>
        ))}
      </nav>
    </aside>
  );
}

export default Sidebar;
