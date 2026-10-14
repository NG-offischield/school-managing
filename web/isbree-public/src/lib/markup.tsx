/**
 * Renders the plain-text markup of the administrable pages (ADR 0032):
 * "## " starts a heading, "- " a list item, a blank line separates
 * paragraphs. No HTML is ever interpreted: React escapes every string.
 */
export type Block =
  | { type: "heading"; text: string }
  | { type: "list"; items: string[] }
  | { type: "paragraph"; text: string };

export function parseMarkup(source: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: string[] | null = null;

  const closeParagraph = () => {
    if (paragraph.length) blocks.push({ type: "paragraph", text: paragraph.join(" ") });
    paragraph = [];
  };
  const closeList = () => {
    if (list) blocks.push({ type: "list", items: list });
    list = null;
  };

  for (const raw of source.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trim();
    if (!line) {
      closeParagraph();
      closeList();
    } else if (line.startsWith("## ")) {
      closeParagraph();
      closeList();
      blocks.push({ type: "heading", text: line.slice(3).trim() });
    } else if (line.startsWith("- ")) {
      closeParagraph();
      list = list ?? [];
      list.push(line.slice(2).trim());
    } else {
      closeList();
      paragraph.push(line);
    }
  }
  closeParagraph();
  closeList();
  return blocks;
}

export function Markup({ source, className = "prose-isbree" }: { source: string; className?: string }) {
  return (
    <div className={className}>
      {parseMarkup(source).map((block, index) => {
        if (block.type === "heading") return <h2 key={index}>{block.text}</h2>;
        if (block.type === "list")
          return (
            <ul key={index}>
              {block.items.map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          );
        return <p key={index}>{block.text}</p>;
      })}
    </div>
  );
}
