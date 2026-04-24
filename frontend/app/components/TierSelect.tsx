"use client";

import type { Tier } from "@/lib/types";

interface TierSelectProps {
  value: Tier;
  onChange: (tier: Tier) => void;
  disabled?: boolean;
}

const TIERS: { value: Tier; label: string; blurb: string }[] = [
  {
    value: "beginner",
    label: "Beginner",
    blurb: "Plain-language overview · ~250 words",
  },
  {
    value: "intermediate",
    label: "Intermediate",
    blurb: "Structured summary · ~600 words",
  },
  {
    value: "expert",
    label: "Expert",
    blurb: "Technical deep-dive · ~1500 words",
  },
];

export default function TierSelect({ value, onChange, disabled }: TierSelectProps) {
  return (
    <fieldset disabled={disabled} className="w-full">
      <legend className="mb-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
        Summary depth
      </legend>
      <div
        role="radiogroup"
        className="grid grid-cols-1 gap-2 sm:grid-cols-3"
      >
        {TIERS.map((t) => {
          const selected = value === t.value;
          return (
            <button
              key={t.value}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(t.value)}
              disabled={disabled}
              className={[
                "rounded-lg border px-4 py-3 text-left transition-colors",
                "disabled:cursor-not-allowed disabled:opacity-60",
                selected
                  ? "border-zinc-900 bg-zinc-900 text-zinc-50 dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
                  : "border-zinc-300 bg-white text-zinc-900 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 dark:hover:bg-zinc-900",
              ].join(" ")}
            >
              <div className="text-sm font-semibold">{t.label}</div>
              <div
                className={[
                  "mt-1 text-xs",
                  selected
                    ? "text-zinc-300 dark:text-zinc-600"
                    : "text-zinc-500 dark:text-zinc-400",
                ].join(" ")}
              >
                {t.blurb}
              </div>
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
