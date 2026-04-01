import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Agents from './pages/Agents';
import AgentForm from './pages/AgentForm';
import AgentDetail from './pages/AgentDetail';
import Sessions from './pages/Sessions';
import SessionDetail from './pages/SessionDetail';
import Tools from './pages/Tools';
import ToolForm from './pages/ToolForm';
import Settings from './pages/Settings';
import EgressAllowlist from './pages/EgressAllowlist';
import Policies from './pages/Policies';

function RequireApiKey({ children }: { children: React.ReactElement }) {
  const key = localStorage.getItem('agent_platform_api_key');
  if (!key) return <Navigate to="/settings" replace />;
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/settings" element={<Settings />} />
          <Route
            path="/"
            element={<RequireApiKey><Dashboard /></RequireApiKey>}
          />
          <Route
            path="/agents"
            element={<RequireApiKey><Agents /></RequireApiKey>}
          />
          <Route
            path="/agents/new"
            element={<RequireApiKey><AgentForm /></RequireApiKey>}
          />
          <Route
            path="/agents/:id"
            element={<RequireApiKey><AgentDetail /></RequireApiKey>}
          />
          <Route
            path="/agents/:id/edit"
            element={<RequireApiKey><AgentForm /></RequireApiKey>}
          />
          <Route
            path="/sessions"
            element={<RequireApiKey><Sessions /></RequireApiKey>}
          />
          <Route
            path="/sessions/:id"
            element={<RequireApiKey><SessionDetail /></RequireApiKey>}
          />
          <Route
            path="/tools"
            element={<RequireApiKey><Tools /></RequireApiKey>}
          />
          <Route
            path="/tools/new"
            element={<RequireApiKey><ToolForm /></RequireApiKey>}
          />
          <Route
            path="/tools/:id/edit"
            element={<RequireApiKey><ToolForm /></RequireApiKey>}
          />
          <Route
            path="/egress"
            element={<RequireApiKey><EgressAllowlist /></RequireApiKey>}
          />
          <Route
            path="/policies"
            element={<RequireApiKey><Policies /></RequireApiKey>}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
