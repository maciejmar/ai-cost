import { cn } from "@/lib/utils";

type Tone = "neutral" | "good" | "warning" | "critical" | "primary";

const tones: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  good: "bg-good/10 text-good",
  warning: "bg-warning/15 text-warning",
  critical: "bg-destructive/10 text-destructive",
  primary: "bg-primary/10 text-primary",
};

export function Badge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: Tone;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[11px] font-medium", tones[tone], className)}>
      {children}
    </span>
  );
}
