import BrandMark from '../Common/BrandMark';

export const ThinkingDots = () => (
  <span className="inline-flex items-center gap-1" aria-hidden="true">
    <span className="h-1.5 w-1.5 animate-dot rounded-full bg-accent" />
    <span className="h-1.5 w-1.5 animate-dot rounded-full bg-accent [animation-delay:160ms]" />
    <span className="h-1.5 w-1.5 animate-dot rounded-full bg-accent [animation-delay:320ms]" />
  </span>
);

const LoadingIndicator = () => {
  return (
    <div className="card mt-6 flex items-center gap-3 px-5 py-4" role="status">
      <BrandMark className="h-4 w-4 text-accent" />
      <span className="text-sm text-ink-muted">Mimir réfléchit</span>
      <ThinkingDots />
    </div>
  );
};

export default LoadingIndicator;
