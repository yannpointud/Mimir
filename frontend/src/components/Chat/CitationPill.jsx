/**
 * Inline citation marker rendered as a clickable pill inside the assistant's
 * markdown answer. This is a pure button: it holds no modal state of its own
 * and instead reports the click to the owning MessageBubble via
 * `onOpenSource`. MessageBubble renders a SINGLE shared DocumentModal for all
 * of a message's citation pills, so at most one source modal can ever be open
 * at a time (no stacked overlays when a user clicks several pills in a row).
 *
 * Rendered as a native <button type="button"> (valid phrasing content inside a
 * paragraph); React default escaping is the XSS control — no
 * dangerouslySetInnerHTML. The component is only ever mounted for valid,
 * non-streaming markers (the remark plugin + MessageBubble gate that), so a
 * missing `source` is defensive only.
 *
 * @param {Object} props
 * @param {string} props.n - The citation number as displayed (bare, no brackets).
 * @param {Object} [props.source] - The source object from message.citations[n].
 * @param {Function} props.onOpenSource - Called with `source` when the pill is clicked.
 */
const CitationPill = ({ n, source, onOpenSource }) => {
  // Same filename fallback chain used by SourcesList's documentItems mapping.
  const filename = source?.filename || source?.document_name || source?.source || 'Document';

  const handleClick = () => {
    if (source?.document_id != null) {
      onOpenSource(source);
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-label={`Voir la source ${n} : ${filename}`}
      title={`Voir la source ${n} : ${filename}`}
      className="mx-0.5 inline-flex h-[19px] min-w-[19px] -translate-y-px cursor-pointer items-center justify-center rounded-md bg-accent-soft px-1 align-middle font-mono text-[11px] font-medium leading-none text-accent-ink transition-colors duration-150 hover:bg-accent hover:text-accent-on"
    >
      {n}
    </button>
  );
};

export default CitationPill;
