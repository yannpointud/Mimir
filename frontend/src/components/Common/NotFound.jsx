import { Link } from 'react-router-dom';
import { Home, ArrowLeft } from 'lucide-react';

const NotFound = () => {
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <div className="bg-white py-8 px-4 shadow sm:rounded-lg sm:px-10">
          <div className="text-center">
            {/* Illustration 404 */}
            <div className="mx-auto h-24 w-24 rounded-full bg-gray-100 flex items-center justify-center mb-6">
              <span className="text-4xl font-bold text-gray-400">404</span>
            </div>

            {/* Titre */}
            <h1 className="text-2xl font-bold text-gray-900 mb-2">
              Page non trouvée
            </h1>

            {/* Description */}
            <p className="text-gray-600 mb-8">
              Désolé, la page que vous recherchez n&apos;existe pas ou a été déplacée.
            </p>

            {/* Actions */}
            <div className="space-y-3">
              <Link
                to="/"
                className="w-full flex justify-center items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors duration-200"
              >
                <Home className="h-4 w-4 mr-2" />
                Retour à l&apos;accueil
              </Link>

              <button
                onClick={() => window.history.back()}
                className="w-full flex justify-center items-center px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors duration-200"
              >
                <ArrowLeft className="h-4 w-4 mr-2" />
                Page précédente
              </button>
            </div>

            {/* Liens utiles */}
            <div className="mt-8 pt-6 border-t border-gray-200">
              <p className="text-sm text-gray-500 mb-3">Liens utiles :</p>
              <div className="flex flex-col space-y-2">
                <Link
                  to="/"
                  className="text-sm text-primary-600 hover:text-primary-500"
                >
                  Assistant documentaire
                </Link>
                <Link
                  to="/admin"
                  className="text-sm text-primary-600 hover:text-primary-500"
                >
                  Administration
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default NotFound;