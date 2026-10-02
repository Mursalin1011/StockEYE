"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Picks" },
  { href: "/stocks", label: "Stocks" },
  { href: "/history", label: "History" },
  { href: "/quality", label: "Quality" },
  { href: "/backtest", label: "Backtest" },
  { href: "/casestudy", label: "Case study" },
  { href: "/settings", label: "Settings" },
];

export function NavLinks() {
  const path = usePathname();
  return (
    <nav className="flex gap-1 overflow-x-auto text-sm">
      {LINKS.map(({ href, label }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={`rounded-md px-3 py-1.5 whitespace-nowrap ${
              active ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
