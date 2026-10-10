/* The arbiter mark and wordmark. */

/** The mark: a board with agents of falling size waiting their turn around it. */
export function Logo() {
  return (
    <svg className="logo" viewBox="0 0 64 64" fill="currentColor" aria-hidden="true">
      <rect x="22" y="22" width="20" height="20" rx="4.5" />
      <circle cx="32" cy="11.5" r="6" />
      <circle cx="52.78" cy="20.00" r="4.8" />
      <circle cx="52.78" cy="44.00" r="4.0" />
      <circle cx="32.00" cy="56.00" r="3.3" />
      <circle cx="11.22" cy="44.00" r="2.7" />
      <circle cx="11.22" cy="20.00" r="2.2" />
    </svg>
  );
}

export interface BrandProps {
  /** "span" in the header, "h1" on the login card. */
  as?: "span" | "h1";
}

/** Mark and wordmark, as in the header. */
export function Brand({ as: Tag = "span" }: BrandProps) {
  return <Tag className="brand"><Logo />arbiter</Tag>;
}
