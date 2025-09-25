import { Bot } from 'lucide-react';

const LoadingIndicator = () => {
  return (
    <div className="flex justify-start">
      <div className="flex space-x-3 max-w-4xl">
        {/* Avatar */}
        <div className="flex-shrink-0 h-8 w-8 rounded-full bg-gray-600 text-white flex items-center justify-center">
          <Bot className="h-5 w-5" />
        </div>

        {/* Bulle de chargement */}
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-3 shadow-sm">
          <div className="flex items-center space-x-2">
            <span className="text-gray-600 text-sm">Mimir réfléchit</span>
            <div className="flex space-x-1">
              <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
              <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
              <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default LoadingIndicator;