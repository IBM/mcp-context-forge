import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const typographyVariants = cva("font-sans", {
  variants: {
    variant: {
      heading1: "font-heading text-xl font-semibold text-foreground",
      heading2: "font-heading text-lg font-semibold text-foreground",
      heading3: "font-heading text-base font-semibold text-foreground",
      heading4: "font-heading text-sm font-semibold text-foreground",
      heading5: "font-heading text-sm font-medium text-foreground",
      heading6: "font-heading text-xs font-medium text-foreground",
      body: "text-sm font-normal text-foreground",
      bodySmall: "text-xs font-normal text-foreground",
      caption: "text-xs text-muted-foreground",
      label: "text-sm font-medium text-foreground",
    },
  },
  defaultVariants: {
    variant: "body",
  },
});

export type TypographyVariant = NonNullable<VariantProps<typeof typographyVariants>["variant"]>;

const defaultTagByVariant: Record<TypographyVariant, React.ElementType> = {
  heading1: "h1",
  heading2: "h2",
  heading3: "h3",
  heading4: "h4",
  heading5: "h5",
  heading6: "h6",
  body: "p",
  bodySmall: "p",
  caption: "span",
  label: "label",
};

type TypographyProps<T extends React.ElementType> = VariantProps<typeof typographyVariants> & {
  /**
   * Overrides the HTML element rendered for this variant (e.g. "span", "div", "caption").
   * Use only when the variant's default tag is semantically wrong for the context
   * (e.g. a heading-styled label that must render as a `<span>` inside a `<button>`).
   * Styling is unaffected by the override — only the tag changes.
   */
  as?: T;
  className?: string;
} & React.AriaAttributes &
  Omit<React.ComponentPropsWithoutRef<T>, "as" | "className">;

/**
 * Standardised text primitive for the UI rewrite. Renders a semantic default tag per
 * `variant` (heading1-6 → h1-h6, body/bodySmall → p, caption → span, label → label) and
 * applies the matching size/weight/color classes. Pass `as` to render a different tag
 * while keeping the variant's styling — e.g. a `heading3`-styled string that must live
 * inside a `<p>` and can't itself be a block-level heading.
 *
 * @example
 * <Typography variant="heading1">Page title</Typography>
 *
 * @example
 * // Styled as heading2 but rendered as a <span> to avoid nesting a heading in a <button>
 * <Typography variant="heading2" as="span">Confirm</Typography>
 *
 * @example
 * <Typography variant="caption" className="italic">Last updated 2 minutes ago</Typography>
 */
function Typography<T extends React.ElementType = "p">({
  variant = "body",
  as,
  className,
  ...props
}: TypographyProps<T>) {
  const Comp = as ?? defaultTagByVariant[variant ?? "body"];

  return (
    <Comp
      data-slot="typography"
      data-variant={variant}
      className={cn(typographyVariants({ variant, className }))}
      {...props}
    />
  );
}

export { Typography, typographyVariants };
