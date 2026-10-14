import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './hooks/useAuth';
import ChatPage from './components/Chat/ChatPage';
import AdminLogin from './components/Admin/AdminLogin';
import AdminDashboard from './components/Admin/AdminDashboard';
import DocumentsList from './components/Admin/DocumentsList';
import UploadZone from './components/Admin/UploadZone';
import ConfigPanel from './components/Admin/ConfigPanel';
import StatusBar from './components/Admin/StatusBar';
import AnalyticsPanel from './components/Admin/AnalyticsPanel';
import ProtectedRoute from './components/Common/ProtectedRoute';
import Layout from './components/Common/Layout';
import NotFound from './components/Common/NotFound';

function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Route publique - Chat */}
        <Route path="/" element={
          <Layout>
            <ChatPage />
          </Layout>
        } />

        {/* Route publique - Chat (alias) */}
        <Route path="/chat" element={<Navigate to="/" replace />} />

        {/* Route de connexion admin */}
        <Route path="/admin/login" element={<AdminLogin />} />

        {/* Routes protégées admin */}
        <Route path="/admin" element={
          <ProtectedRoute>
            <Layout>
              <AdminDashboard />
            </Layout>
          </ProtectedRoute>
        }>
          <Route index element={<Navigate to="/admin/documents" replace />} />
          <Route path="documents" element={<DocumentsList />} />
          <Route path="upload" element={<UploadZone />} />
          <Route path="config" element={<ConfigPanel />} />
          <Route path="monitoring" element={<StatusBar />} />
          <Route path="analytics" element={<AnalyticsPanel />} />
        </Route>

        {/* Route par défaut pour /admin/* */}
        <Route path="/admin/*" element={<Navigate to="/admin" replace />} />

        {/* 404 */}
        <Route path="*" element={<NotFound />} />
      </Routes>
    </AuthProvider>
  );
}

export default App;