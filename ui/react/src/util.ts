/** Join class names, skipping empty ones. Returns undefined when none are left, so React omits the attribute. */
export function cls(...names: Array<string | false | null | undefined>): string | undefined {
  return names.filter(Boolean).join(" ") || undefined;
}
