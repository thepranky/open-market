import { cn } from "@/lib/utils";

type Tone = "brand" | "pos" | "ai" | "neg" | "seg" | "slatey";
type Variant = "soft" | "solid" | "outline";

const TONE_CLS: Record<Tone, Record<Variant, string>> = {
  brand:  { soft: "bg-brand-soft text-brand-ink",   solid: "bg-brand text-brand-fg",     outline: "border border-brand text-brand-ink" },
  pos:    { soft: "bg-pos-soft text-pos-ink",        solid: "bg-pos text-white",           outline: "border border-pos text-pos-ink" },
  ai:     { soft: "bg-ai-soft text-ai-ink",          solid: "bg-ai text-white",            outline: "border border-ai text-ai-ink" },
  neg:    { soft: "bg-neg-soft text-neg-ink",        solid: "bg-neg text-white",           outline: "border border-neg text-neg-ink" },
  seg:    { soft: "bg-seg-soft text-seg-ink",        solid: "bg-seg text-white",           outline: "border border-seg text-seg-ink" },
  slatey: { soft: "bg-slatey-soft text-slatey-ink", solid: "bg-slatey text-white",        outline: "border border-slatey text-slatey-ink" },
};

interface BadgeProps {
  children: React.ReactNode;
  className?: string;
  tone?: Tone;
  variant?: Variant;
  dot?: boolean;
}

export function Badge({ children, className, tone, variant = "soft", dot = false }: BadgeProps) {
  const toneCls = tone ? TONE_CLS[tone][variant] : "bg-slatey-soft text-slatey-ink";
  return (
    <span className={cn(
      "inline-flex items-center gap-1.5 rounded-[5px] px-2 py-[3px] text-[12px] font-medium leading-none whitespace-nowrap",
      toneCls,
      className,
    )}>
      {dot && <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: "currentColor" }} />}
      {children}
    </span>
  );
}
