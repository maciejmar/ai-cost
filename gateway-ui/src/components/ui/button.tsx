import * as React from "react";
import { cn } from "@/lib/utils";

type Variant = "default" | "outline" | "ghost" | "destructive";
type Size = "default" | "sm" | "icon";

const variants: Record<Variant, string> = {
  default: "bg-primary text-primary-foreground hover:bg-primary/90",
  outline: "border border-border bg-surface hover:bg-muted",
  ghost: "hover:bg-muted",
  destructive: "bg-destructive text-white hover:bg-destructive/90",
};
const sizes: Record<Size, string> = {
  default: "h-9 px-4",
  sm: "h-8 px-3 text-xs",
  icon: "h-8 w-8",
};

export const Button = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }
>(({ className, variant = "default", size = "default", ...props }, ref) => (
  <button
    ref={ref}
    className={cn(
      "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 disabled:pointer-events-none disabled:opacity-50",
      variants[variant],
      sizes[size],
      className,
    )}
    {...props}
  />
));
Button.displayName = "Button";
