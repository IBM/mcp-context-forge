/** Shared upper bound on tags per entity, enforced across every tag entry UI. */
export const MAX_TAGS = 20;

/** Extract plain tag labels from a mixed `string | { label }` array. */
export function getTagLabels(tags: Array<string | { label: string }>): string[] {
  return tags.map((tag) => (typeof tag === "string" ? tag : tag.label));
}
