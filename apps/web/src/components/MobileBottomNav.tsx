import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  PieChart,
  BarChart3,
  Gauge,
  Sparkles,
  MoreHorizontal,
  type LucideIcon,
} from "lucide-react";

type Tab = {
  to: string;
  end?: boolean;
  label: string;
  icon: LucideIcon;
};

const MAIN_TABS: Tab[] = [
  { to: "/", end: true, label: "Início", icon: LayoutDashboard },
  { to: "/observatorio", label: "Observ.", icon: PieChart },
  { to: "/caracterizacao", label: "Perfil", icon: BarChart3 },
  { to: "/ivs", label: "IVS", icon: Gauge },
  { to: "/assistente", label: "VigIA", icon: Sparkles },
];

type Props = {
  onMore: () => void;
  moreActive?: boolean;
};

export default function MobileBottomNav({ onMore, moreActive }: Props) {
  return (
    <nav className="mobile-bottom-nav fx-glass" aria-label="Navegação principal">
      {MAIN_TABS.map(({ to, end, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            `mobile-bottom-nav-item${isActive ? " active" : ""}`
          }
        >
          <Icon size={20} strokeWidth={2} aria-hidden />
          <span>{label}</span>
        </NavLink>
      ))}
      <button
        type="button"
        className={`mobile-bottom-nav-item mobile-bottom-nav-more${moreActive ? " active" : ""}`}
        onClick={onMore}
        aria-label="Mais opções"
      >
        <MoreHorizontal size={20} strokeWidth={2} aria-hidden />
        <span>Mais</span>
      </button>
    </nav>
  );
}
