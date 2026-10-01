import type { ReactNode } from "react";

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full border-collapse text-sm tabular">{children}</table>
    </div>
  );
}

export function Th({ children, right = false, title }: { children?: ReactNode; right?: boolean; title?: string }) {
  return (
    <th title={title} className={`sticky top-0 border-b border-line bg-surface-2 px-3 py-2 text-xs font-medium whitespace-nowrap text-ink-2 ${right ? "text-right" : "text-left"}`}>
      {children}
    </th>
  );
}

export function Td({ children, right = false, className = "" }: { children?: ReactNode; right?: boolean; className?: string }) {
  return <td className={`border-b border-line px-3 py-2 whitespace-nowrap ${right ? "text-right" : ""} ${className}`}>{children}</td>;
}
