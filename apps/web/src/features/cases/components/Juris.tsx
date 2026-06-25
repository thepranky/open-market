import { jurisdictionAuthority } from "@/lib/utils";

export function Juris({
  code,
  withAuthority = false,
  className = "",
}: {
  code: string;
  withAuthority?: boolean;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <span className="font-mono text-[11px] font-semibold tracking-[0.08em] text-ink border border-line-strong rounded-[4px] px-1.5 py-[2px] leading-none">
        {code}
      </span>
      {withAuthority && (
        <span className="text-[13px] text-muted">{jurisdictionAuthority(code)}</span>
      )}
    </span>
  );
}
