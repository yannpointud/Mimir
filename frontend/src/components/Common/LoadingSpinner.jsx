import { cn } from '../../utils/helpers';

const LoadingSpinner = ({ size = 'md', className = '' }) => {
  const sizeClasses = {
    sm: 'h-4 w-4',
    md: 'h-6 w-6',
    lg: 'h-8 w-8',
    xl: 'h-12 w-12'
  };

  return (
    <div className={cn('animate-spin rounded-full border-2 border-gray-200 border-t-primary-600', sizeClasses[size], className)}>
      <span className="sr-only">Chargement...</span>
    </div>
  );
};

export default LoadingSpinner;