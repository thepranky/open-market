"use client";

import { usePathname } from "next/navigation";

export function ConditionalFooter() {
  const pathname = usePathname();
  if (pathname !== "/") return null;

  return (
    <footer className="mt-16 border-t border-line">
      <div className="mx-auto max-w-content px-6 lg:px-8 py-8 flex flex-wrap items-center justify-between gap-4 text-[13px] text-faint">
        <div className="flex items-center gap-2">
          <span className="font-serif text-muted">Meridian</span>
          <span>·</span>
          <span>Market-definition research</span>
        </div>
        <div className="flex items-center gap-5">
          <span>EU · UK · US precedent</span>
          <span className="text-[12px]">Not legal advice.</span>
        </div>
      </div>
    </footer>
  );
}
