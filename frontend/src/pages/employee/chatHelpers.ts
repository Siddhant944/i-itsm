/**
 * Services ranked by how many words of their name the reporter used (whole words, three
 * letters or more, so "VPN" and "Fee" count), then by name: the likely one is one tap away.
 */
export function rankServices<T extends { name: string }>(
  services: readonly T[],
  text: string,
): T[] {
  const said = new Set(text.toLowerCase().match(/[a-z0-9-]+/g) ?? []);
  const score = (s: T) =>
    (s.name.toLowerCase().match(/[a-z0-9-]+/g) ?? []).filter(
      (word) => word.length >= 3 && said.has(word),
    ).length;
  return [...services].sort((a, b) => score(b) - score(a) || a.name.localeCompare(b.name));
}
