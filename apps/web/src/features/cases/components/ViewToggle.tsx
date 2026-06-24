"use client";

interface ViewToggleProps<T extends string> {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  size?: "sm" | "md";
  "aria-label"?: string;
}

export function ViewToggle<T extends string>({
  options,
  value,
  onChange,
  size = "sm",
  "aria-label": ariaLabel,
}: ViewToggleProps<T>) {
  const pad = size === "sm" ? "px-2.5 py-1 text-[12.5px]" : "px-3 py-1.5 text-[13.5px]";

  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="inline-flex items-center rounded-[8px] border border-line bg-canvas p-0.5"
    >
      {options.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={`rounded-[6px] font-medium whitespace-nowrap transition-colors ${pad} ${
              active
                ? "bg-surface text-ink shadow-card"
                : "text-muted hover:text-ink"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
