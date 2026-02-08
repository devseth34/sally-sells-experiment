import { useNavigate, useLocation } from "react-router-dom";

const NAV_ITEMS = [
  { path: "/", label: "Chat" },
  { path: "/dashboard", label: "Dashboard" },
  { path: "/history", label: "History" },
];

export function Header() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <header className="h-14 border-b border-zinc-800 bg-zinc-950 flex items-center justify-between px-4">
      <div className="flex items-center gap-6">
        <span className="text-sm font-semibold text-white tracking-tight">
          Sally Sells
        </span>
        <nav className="flex items-center gap-1">
          {NAV_ITEMS.map((item) => {
            const isActive = location.pathname === item.path;
            return (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                  isActive
                    ? "bg-zinc-800 text-white"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {item.label}
              </button>
            );
          })}
        </nav>
      </div>
      <span className="text-[10px] text-zinc-600 uppercase tracking-widest">
        NEPQ Engine v1
      </span>
    </header>
  );
}