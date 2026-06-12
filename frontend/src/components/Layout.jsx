import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Upload, Table2, Building2, History, Users, AlertTriangle,
  Sparkles, Settings, FileDown, Mail, Megaphone, Tag, Shield, LogOut, CheckSquare, ShieldCheck, Boxes,
} from "lucide-react";
import { Toaster } from "sonner";
import { useAuth, hasRole } from "@/context/AuthContext";

// Each item declares which roles may see it.
const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testid: "nav-dashboard", end: true, roles: ["admin", "manager"] },
  { to: "/tasks", label: "Tasks", icon: CheckSquare, testid: "nav-tasks", roles: ["admin", "manager", "staff"] },
  { to: "/compliance", label: "Compliance", icon: ShieldCheck, testid: "nav-compliance", roles: ["admin", "manager"] },
  { to: "/inventory", label: "Inventory", icon: Boxes, testid: "nav-inventory", roles: ["admin", "manager", "staff"] },
  { to: "/reservations", label: "Reservations", icon: Table2, testid: "nav-reservations", roles: ["admin", "manager"] },
  { to: "/segments", label: "Segments", icon: Users, testid: "nav-segments", roles: ["admin", "manager"] },
  { to: "/scores", label: "Scores", icon: Sparkles, testid: "nav-scores", roles: ["admin", "manager"] },
  { to: "/cancellations", label: "Cancellations", icon: AlertTriangle, testid: "nav-cancellations", roles: ["admin", "manager"] },
  { to: "/campaigns", label: "Campaigns", icon: Megaphone, testid: "nav-campaigns", roles: ["admin", "manager"] },
  { to: "/reports", label: "Reports", icon: FileDown, testid: "nav-reports", roles: ["admin", "manager"] },
  { to: "/import", label: "Import", icon: Upload, testid: "nav-import", roles: ["admin", "manager"] },
  { to: "/properties", label: "Properties", icon: Building2, testid: "nav-properties", roles: ["admin", "manager"] },
  { to: "/history", label: "Import History", icon: History, testid: "nav-history", roles: ["admin", "manager"] },
];

const ADMIN_NAV = [
  { to: "/admin/users", label: "Users & roles", icon: Shield, testid: "nav-admin-users", roles: ["admin"] },
  { to: "/settings/commissions", label: "Commissions", icon: Settings, testid: "nav-settings-commissions", roles: ["admin"] },
  { to: "/settings/offers", label: "Offer library", icon: Tag, testid: "nav-settings-offers", roles: ["admin"] },
  { to: "/settings/digest", label: "Weekly digest", icon: Mail, testid: "nav-settings-digest", roles: ["admin"] },
];

const roleBadge = (role) => {
  if (role === "admin") return "text-[#D9A05B] border-[#D9A05B]/40";
  if (role === "manager") return "text-[#7AB8FF] border-[#7AB8FF]/40";
  return "text-[#8F95A3] border-[#22252F]";
};

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const visibleMain = NAV.filter((n) => hasRole(user, ...n.roles));
  const visibleAdmin = ADMIN_NAV.filter((n) => hasRole(user, ...n.roles));

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="min-h-screen bg-[#090A0E] text-[#F2F3F5] bg-grid">
      <Toaster theme="dark" position="bottom-right" richColors />
      <div className="flex">
        {/* Sidebar */}
        <aside className="hidden lg:flex flex-col w-60 min-h-screen border-r divider bg-[#0B0C11] sticky top-0 h-screen">
          <div className="px-6 py-7 border-b divider">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-md bg-brand flex items-center justify-center">
                <span className="text-black font-display text-base font-bold">S</span>
              </div>
              <div className="leading-tight">
                <div className="font-display text-[15px] font-medium">Sourcebench</div>
                <div className="text-[10px] uppercase tracking-[0.18em] text-dim">STR Analytics</div>
              </div>
            </div>
          </div>
          <nav className="px-3 py-5 flex-1 space-y-1 overflow-y-auto">
            {visibleMain.map(({ to, label, icon: Icon, testid, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                data-testid={testid}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                    isActive
                      ? "bg-[#1A1D24] text-white"
                      : "text-[#8F95A3] hover:text-white hover:bg-[#14161D]"
                  }`
                }
              >
                <Icon className="w-4 h-4" />
                <span>{label}</span>
              </NavLink>
            ))}

            {visibleAdmin.length > 0 && (
              <div className="pt-4 mt-2 border-t divider">
                <div className="px-3 pb-2 text-[10px] uppercase tracking-[0.18em] text-[#5B606B]">Admin</div>
                {visibleAdmin.map(({ to, label, icon: Icon, testid }) => (
                  <NavLink
                    key={to}
                    to={to}
                    data-testid={testid}
                    className={({ isActive }) =>
                      `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                        isActive
                          ? "bg-[#1A1D24] text-white"
                          : "text-[#8F95A3] hover:text-white hover:bg-[#14161D]"
                      }`
                    }
                  >
                    <Icon className="w-4 h-4" />
                    <span>{label}</span>
                  </NavLink>
                ))}
              </div>
            )}
          </nav>

          {/* Profile / logout */}
          {user && (
            <div className="px-3 py-3 border-t divider space-y-2" data-testid="sidebar-profile">
              <div className="px-2 py-2 rounded-md bg-[#0F1117] border border-[#22252F]">
                <div className="text-sm text-white truncate" data-testid="profile-name">{user.name}</div>
                <div className="text-[11px] text-dim truncate">{user.email}</div>
                <div className={`mt-2 inline-block text-[10px] uppercase tracking-[0.18em] border rounded px-1.5 py-0.5 ${roleBadge(user.role)}`} data-testid="profile-role">
                  {user.role}
                </div>
              </div>
              <button
                onClick={handleLogout}
                data-testid="logout-button"
                className="w-full inline-flex items-center justify-center gap-2 text-xs text-dim hover:text-white border border-[#22252F] hover:border-[#3A3F4C] rounded-md py-2 transition-colors"
              >
                <LogOut className="w-3.5 h-3.5" />
                Sign out
              </button>
            </div>
          )}
        </aside>

        {/* Main */}
        <main className="flex-1 min-w-0">
          {/* Mobile top nav */}
          <div className="lg:hidden border-b divider bg-[#0B0C11] px-4 py-3 sticky top-0 z-10">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded bg-brand flex items-center justify-center">
                  <span className="text-black font-display text-xs font-bold">S</span>
                </div>
                <span className="font-display text-sm">Sourcebench</span>
              </div>
              {user && (
                <button
                  onClick={handleLogout}
                  data-testid="m-logout-button"
                  className="text-[11px] text-dim hover:text-white inline-flex items-center gap-1"
                >
                  <LogOut className="w-3.5 h-3.5" /> Sign out
                </button>
              )}
            </div>
            <div className="flex gap-1 mt-3 overflow-x-auto -mx-1 px-1">
              {[...visibleMain, ...visibleAdmin].map(({ to, label, testid, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  data-testid={`m-${testid}`}
                  className={({ isActive }) =>
                    `px-3 py-1.5 text-xs rounded-full whitespace-nowrap border ${
                      isActive
                        ? "bg-[#1A1D24] text-white border-[#22252F]"
                        : "text-[#8F95A3] border-transparent hover:text-white"
                    }`
                  }
                >
                  {label}
                </NavLink>
              ))}
            </div>
          </div>

          <div className="px-4 sm:px-8 py-8 max-w-[1600px] mx-auto">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
