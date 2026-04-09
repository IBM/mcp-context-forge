type ClassValue = string | undefined | null | false | ClassValue[];

/** Joins class names, deduplicating exact duplicates. No external dep needed. */
export function cn(...classes: ClassValue[]): string {
  return [
    ...new Set(
      classes
        .flat(Infinity as 10)
        .filter(Boolean) as string[],
    ),
  ].join(" ");
}
