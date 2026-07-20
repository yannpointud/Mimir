import { visit } from 'unist-util-visit';

/**
 * Remark plugin factory that turns inline `[N]` markers into interactive
 * citation-pill nodes — but ONLY when `N` is a valid key of the `citations`
 * map. This selective transform is the correctness AND XSS-safety boundary:
 * markers whose number is absent from `citations` (hallucinated or
 * out-of-range) are left untouched as literal text, never becoming a pill or
 * a dead link.
 *
 * The transform runs at the mdast (AST) level rather than as a raw-string
 * regex replace, so `[N]` inside code spans/blocks is never mistakenly
 * converted, and the injected node maps to a plain `<citation-pill>` element
 * (React default escaping applies — no dangerouslySetInnerHTML anywhere).
 *
 * @param {Object<string, Object>} citations - `{ "1": sourceObj, ... }` map.
 * @returns {(tree: object) => void} A unified transformer.
 */
export default function remarkCitations(citations) {
  const validMap = citations || {};

  return (tree) => {
    visit(tree, 'text', (node, index, parent) => {
      if (!parent || index === null) return;

      const regex = /\[(\d+)\]/g;
      const parts = [];
      let lastIndex = 0;
      let match;
      let matched = false;

      while ((match = regex.exec(node.value)) !== null) {
        const n = match[1];
        // Neutralization: only in-map numbers become interactive pills.
        if (!(n in validMap)) continue;

        matched = true;
        if (match.index > lastIndex) {
          parts.push({ type: 'text', value: node.value.slice(lastIndex, match.index) });
        }
        parts.push({
          type: 'citationPill',
          data: { hName: 'citation-pill', hProperties: { n } },
          children: [],
        });
        lastIndex = regex.lastIndex;
      }

      if (!matched) return;
      if (lastIndex < node.value.length) {
        parts.push({ type: 'text', value: node.value.slice(lastIndex) });
      }

      parent.children.splice(index, 1, ...parts);
    });
  };
}
