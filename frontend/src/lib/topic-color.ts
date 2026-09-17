// The mockups' signature colour device: a topic or tag always gets the same
// pastel, derived from its name, so "rust" looks the same on the Topics page,
// on a question card and on the dashboard. Hash and palette are copied
// verbatim from design-mockups/Topics.dc.html and Questions.dc.html so the
// colours match the mockups exactly.
const TOPIC_PALETTE = ["#a8d8c4", "#fcab79", "#f5e9d4", "#f4d35e", "#d9a441"];

export function colorForTopic(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) % 997;
  }
  return TOPIC_PALETTE[Math.abs(hash) % TOPIC_PALETTE.length];
}
