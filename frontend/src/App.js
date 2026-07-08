import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import ProtectedRoute from "@/components/ProtectedRoute";
import Layout from "@/components/Layout";
import Login from "@/pages/Login";
import AdminUsers from "@/pages/AdminUsers";
import AnalyticsDashboard from "@/pages/AnalyticsDashboard";
import Import from "@/pages/Import";
import Reservations from "@/pages/Reservations";
import Properties from "@/pages/Properties";
import History from "@/pages/History";
import Segments from "@/pages/Segments";
import GuestProfile from "@/pages/GuestProfile";
import Cancellations from "@/pages/Cancellations";
import Scores from "@/pages/Scores";
import CommissionSettings from "@/pages/CommissionSettings";
import Reports from "@/pages/Reports";
import DigestSettings from "@/pages/DigestSettings";
import Campaigns from "@/pages/Campaigns";
import OffersSettings from "@/pages/OffersSettings";
import Tasks from "@/pages/Tasks";
import Compliance from "@/pages/Compliance";
import Inventory from "@/pages/Inventory";
import Reviews from "@/pages/Reviews";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            {/* Public */}
            <Route path="/login" element={<Login />} />

            {/* Authenticated routes (any role) */}
            <Route element={<ProtectedRoute />}>
              <Route path="/" element={<Layout />}>
                <Route index element={<Home />} />
                <Route path="reservations" element={<Reservations />} />
                <Route path="import" element={<Import />} />
                <Route path="properties" element={<Properties />} />
                <Route path="history" element={<History />} />
                <Route path="segments" element={<Segments />} />
                <Route path="guests/:id" element={<GuestProfile />} />
                <Route path="cancellations" element={<Cancellations />} />
                <Route path="scores" element={<Scores />} />
                <Route path="reports" element={<Reports />} />
                <Route path="campaigns" element={<Campaigns />} />
                <Route path="tasks" element={<Tasks />} />
                <Route path="compliance" element={<Compliance />} />
                <Route path="inventory" element={<Inventory />} />
                <Route path="reviews" element={<Reviews />} />

                {/* Admin-only nested routes */}
                <Route element={<ProtectedRoute roles={["admin"]} />}>
                  <Route path="settings/commissions" element={<CommissionSettings />} />
                  <Route path="settings/digest" element={<DigestSettings />} />
                  <Route path="settings/offers" element={<OffersSettings />} />
                  <Route path="admin/users" element={<AdminUsers />} />
                </Route>
              </Route>
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </div>
  );
}

export default App;

// Index landing — staff users go to /tasks because /dashboard is admin/manager only.
function Home() {
  const { user } = useAuth();
  if (user?.role === "staff") return <Navigate to="/tasks" replace />;
  return <AnalyticsDashboard />;
}
