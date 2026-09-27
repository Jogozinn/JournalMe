import type { SVGProps } from "react";

export type IconName =
  | "home"
  | "trades"
  | "capture"
  | "import"
  | "calendar"
  | "more"
  | "analytics"
  | "intelligence"
  | "journal"
  | "days"
  | "playbook"
  | "review"
  | "accounts"
  | "settings"
  | "plus"
  | "arrow"
  | "search"
  | "menu"
  | "panel";

const paths: Record<IconName, React.ReactNode> = {
  home: <><path d="m3 11 9-8 9 8" /><path d="M5 10v10h14V10M9 20v-6h6v6" /></>,
  trades: <><path d="M5 4v16M19 4v16M3 8h4M17 16h4M10 7v10M14 4v16" /><path d="M8 10h4M12 14h4" /></>,
  capture: <><path d="M5 7h3l1.5-2h5L16 7h3a2 2 0 0 1 2 2v9H3V9a2 2 0 0 1 2-2Z" /><circle cx="12" cy="13" r="3.5" /></>,
  import: <><path d="M5 4h9l5 5v11H5z" /><path d="M14 4v5h5" /><path d="M12 11v6M9.5 14.5 12 17l2.5-2.5" /></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M7 3v4M17 3v4M3 10h18" /></>,
  more: <><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></>,
  analytics: <><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></>,
  intelligence: <><circle cx="12" cy="12" r="3" /><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" /></>,
  journal: <><path d="M5 4h12a2 2 0 0 1 2 2v15H7a2 2 0 0 1-2-2V4Z" /><path d="M8 8h8M8 12h6" /></>,
  days: <><path d="M7 3v3M17 3v3M4 8h16v12H4z" /><path d="M8 12h3M13 12h3M8 16h3" /></>,
  playbook: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11v17H6.5A2.5 2.5 0 0 0 4 22z" /><path d="M20 5.5A2.5 2.5 0 0 0 17.5 3H13v17h4.5A2.5 2.5 0 0 1 20 22z" /></>,
  review: <><path d="M5 4h14v16H5z" /><path d="m8 10 2 2 5-5M8 16h7" /></>,
  accounts: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21h-4v-.1A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3v-4h.1A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3h4v.1A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.16.37.45.68.82.87.24.12.5.18.78.18V14h-.1A1.7 1.7 0 0 0 19.4 15Z" /></>,
  plus: <><path d="M12 5v14M5 12h14" /></>,
  arrow: <><path d="m9 18 6-6-6-6" /></>,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
  menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
  panel: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16M14 9l3 3-3 3" /></>,
};

export function Icon({
  name,
  ...props
}: { name: IconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}
