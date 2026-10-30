/**
 * Facebook Ad Builder - Frontend
 *
 * Created by Jason Akatiff
 * iSCALE.com | A4D.com
 * Telegram: @jasonakatiff
 * Email: jason@jasonakatiff.com
 */

import React from 'react';
import { lazyPage } from './lib/lazyPage';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { BrandProvider } from './context/BrandContext';
import { CampaignProvider } from './context/CampaignContext';
import { ToastProvider } from './context/ToastContext';
import PrivateRoute from './components/PrivateRoute';
import Layout from './components/Layout';
import Login from './pages/Login';
const Dashboard = lazyPage(() => import('./pages/Dashboard'));
const PerformanceBrief = lazyPage(() => import('./pages/PerformanceBrief'));
const CreateAds = lazyPage(() => import('./pages/CreateAds'));
const BrandsHub = lazyPage(() => import('./pages/BrandsHub'));
const LibrariesHub = lazyPage(() => import('./pages/LibrariesHub'));
const FacebookHub = lazyPage(() => import('./pages/FacebookHub'));
const ImageAds = lazyPage(() => import('./pages/ImageAds'));
const VideoAds = lazyPage(() => import('./pages/VideoAds'));
const Reporting = lazyPage(() => import('./pages/Reporting'));
const Brands = lazyPage(() => import('./pages/Brands'));
const Products = lazyPage(() => import('./pages/Products'));
const CustomerProfiles = lazyPage(() => import('./pages/CustomerProfiles'));
const FacebookCampaigns = lazyPage(() => import('./pages/FacebookCampaigns'));
const CampaignPerformance = lazyPage(() => import('./pages/CampaignPerformance'));
const AutoPauseRules = lazyPage(() => import('./pages/AutoPauseRules'));
const WinningAds = lazyPage(() => import('./pages/WinningAds'));
const GeneratedAds = lazyPage(() => import('./pages/GeneratedAds'));
const Research = lazyPage(() => import('./pages/Research'));
const ResearchSettings = lazyPage(() => import('./pages/ResearchSettings'));
const BrandScrapes = lazyPage(() => import('./pages/BrandScrapes'));
const AdRemix = lazyPage(() => import('./pages/AdRemix'));
const BatchGenerate = lazyPage(() => import('./pages/BatchGenerate'));
const CopyLibrary = lazyPage(() => import('./pages/CopyLibrary'));
const CreativeLibrary = lazyPage(() => import('./pages/CreativeLibrary'));
const DrivePackageHealth = lazyPage(() => import('./pages/DrivePackageHealth'));
const Pnl = lazyPage(() => import('./pages/Pnl'));
const Settings = lazyPage(() => import('./pages/Settings'));
const UserManagement = lazyPage(() => import('./pages/UserManagement'));

function DefaultLanding() {
  const { user, hasRole } = useAuth();
  if (user?.is_superuser || hasRole('admin')) return <Dashboard />;
  return <Navigate to="/campaign-performance" replace />;
}

function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <BrandProvider>
          <CampaignProvider>
            <BrowserRouter>
              <Routes>
                {/* Public routes */}
                <Route path="/login" element={<Login />} />

                {/* Protected routes */}
                <Route
                  path="/"
                  element={
                    <PrivateRoute>
                      <Layout />
                    </PrivateRoute>
                  }
                >
                  <Route index element={<DefaultLanding />} />
                  <Route path="performance-brief" element={<PerformanceBrief />} />
                  <Route path="research" element={<Research />} />
                  <Route path="pnl" element={<Pnl />} />
                  <Route path="research/brand-scrapes" element={<BrandScrapes />} />
                  <Route path="research/settings" element={<ResearchSettings />} />
                  <Route path="build-creatives" element={<CreateAds />} />
                  <Route path="brand-hub" element={<BrandsHub />} />
                  <Route path="libraries" element={<LibrariesHub />} />
                  <Route path="facebook-hub" element={<FacebookHub />} />
                  <Route path="image-ads" element={<ImageAds />} />
                  <Route path="batch-generate" element={<BatchGenerate />} />
                  <Route path="video-ads" element={<VideoAds />} />
                  <Route path="facebook-campaigns" element={<FacebookCampaigns />} />
                  <Route path="campaign-performance" element={<CampaignPerformance />} />
                  <Route path="auto-pause-rules" element={<AutoPauseRules />} />
                  <Route path="winning-ads" element={<WinningAds />} />
                  <Route path="generated-ads" element={<GeneratedAds />} />
                  <Route path="creative-library" element={<CreativeLibrary />} />
                  <Route path="drive-package-health" element={<DrivePackageHealth />} />
                  <Route path="copy-library" element={<CopyLibrary />} />
                  <Route path="brands" element={<Brands />} />
                  <Route path="products" element={<Products />} />
                  <Route path="profiles" element={<CustomerProfiles />} />
                  <Route path="ad-remix" element={<AdRemix />} />
                  <Route path="reporting" element={<Reporting />} />
                  <Route path="settings" element={<Settings />} />
                  <Route
                    path="users"
                    element={
                      <PrivateRoute requiredRole="admin">
                        <UserManagement />
                      </PrivateRoute>
                    }
                  />
                </Route>
              </Routes>
            </BrowserRouter>
          </CampaignProvider>
        </BrandProvider>
      </AuthProvider>
    </ToastProvider>
  );
}

export default App;
