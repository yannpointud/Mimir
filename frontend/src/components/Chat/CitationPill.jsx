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
      className="inline-flex items-center justify-center h-5 w-5 mx-0.5 rounded-full border text-xs font-semibold bg-primary-50 border-primary-200 text-primary-700 hover:bg-primary-100 hover:text-primary-800 active:bg-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-1 cursor-pointer transition-colors duration-200"
    >
      {n}
    </button>
  );
};

export default CitationPill;
