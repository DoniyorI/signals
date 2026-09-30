/** Every SEC-derived number links to its filing (spec principle 4); always a new tab. */
export function SecLink({ href, label = "SEC filing" }: { href: string; label?: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="text-link hover:underline">
      {label}
    </a>
  );
}
