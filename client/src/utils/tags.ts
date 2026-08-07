/** Shared upper bound on tags per entity, enforced across every tag entry UI. */
export const MAX_TAGS = 20;

/** Extract plain tag labels from a mixed `string | { label }` array, dropping blanks. */
export function getTagLabels(tags: Array<string | { label?: string | null }>): string[] {
  return tags
    .map((tag) => (typeof tag === "string" ? tag : (tag.label ?? "")))
    .filter((label) => label !== "");
}
