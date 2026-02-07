import { Link, useLocation } from "react-router-dom";
import { cn } from "../../lib/utils";
import { MessageSquare, BarChart3, History } from "lucide-react";

const NAV_ITEMS = [
  { path: "/", label: "Chat", icon: MessageSquare },
  { path: "/dashboard", label: "Dashboard", icon: BarChart3 },
  { path: "/history", label: "History", icon: History },
];

export function Header() {
  const location = useLocation();

  return (
    <header className="h-14 border-b border-zinc-800 bg-zinc-950 flex items-center justify-between px-6">
      <div className="flex items-center gap-8">
        <Link to="/" className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-white flex items-center justify-center">
            <span className="text-zinc-900 font-bold text-sm">S</span>
          </div>
          <span className="font-semibold text-white">Sally Sells</span>
        </Link>

        <nav className="flex items-center gap-1">
          {NAV_ITEMS.map(({ path, label, icon: Icon }) => (
            <Link
              key={path}
              to={path}
              className={cn(
                "flex items-center gap-2 px-3 py-1.5 rounded-md text-sm transition-colors",
                location.pathname === path
                  ? "bg-zinc-800 text-white"
                  : "text-zinc-400 hover:text-white hover:bg-zinc-800/50"
              )}
            >
              <Icon className="w-4 h-4" />
              {label}
            </Link>
          ))}
        </nav>
      </div>

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-xs text-zinc-400">System Online</span>
        </div>
      </div>
    </header>
  );
}