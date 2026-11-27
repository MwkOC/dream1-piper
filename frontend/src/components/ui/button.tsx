import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";

const styles = cva("inline-flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-40", {
  variants: { variant: {
    primary: "border-red-700 bg-red-700 text-white hover:bg-red-800",
    secondary: "border-zinc-300 bg-zinc-100 text-zinc-900 hover:bg-zinc-200 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800",
    danger: "border-red-900 bg-red-950 text-red-100 hover:bg-red-900",
  } },
  defaultVariants: { variant: "secondary" },
});

type Props = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof styles> & { asChild?: boolean };

export function Button({ variant, asChild, className, ...props }: Props) {
  const Component = asChild ? Slot : "button";
  return <Component className={`${styles({ variant })} ${className ?? ""}`} {...props} />;
}
