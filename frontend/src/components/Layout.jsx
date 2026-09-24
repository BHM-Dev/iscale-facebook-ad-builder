import React, { useState } from 'react';
import { Link, useLocation, Outlet, useNavigate } from 'react-router-dom';
import { LayoutDashboard, Wand2, Settings, LogOut, ShoppingBag, Target, ChevronLeft, ChevronRight, UserCog, Search, Library, DollarSign, BriefcaseBusiness } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { useBrands } from '../context/BrandContext';
import { useCampaign } from '../context/CampaignContext';
import { VERTICAL_FILTERS } from '../lib/verticals';
import AskAiWidget from './AskAiWidget';

// BHM mark — flat single-color circle with horizon lines, matching
// bhm_logo_1color_blue@3x.png (#301A5B), sized for 40×40 container
function BHMLogo({ size = 40 }) {
    return (
        <svg width={size} height={size} viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
                <clipPath id="bhm-circle">
                    <circle cx="20" cy="20" r="18" />
                </clipPath>
            </defs>
            <circle cx="20" cy="20" r="18" fill="#301A5B" />
            {/* Horizon lines */}
            <g clipPath="url(#bhm-circle)" opacity="0.92">
                <rect x="8"  y="18" width="24" height="2.2" rx="1.1" fill="white" />
                <rect x="9"  y="22" width="22" height="2"   rx="1"   fill="white" opacity="0.85" />
                <rect x="11" y="26" width="18" height="1.8" rx="0.9" fill="white" opacity="0.7" />
                <rect x="13" y="29.5" width="14" height="1.5" rx="0.75" fill="white" opacity="0.55" />
            </g>
        </svg>
    );
}

export default function Layout() {
    const location = useLocation();
    const navigate = useNavigate();
    const { user, logout, hasRole, hasPermission, sessionExpired } = useAuth();
    const { showSuccess } = useToast();
    const { activeVerticalFilter, setActiveVerticalFilter } = useBrands();
    const { activeAccountId, setActiveAccountId, adAccounts, activeAccountLoading } = useCampaign();
    // Auto-collapse the nav to icons-only while in the ad launch wizard, where
    // every extra pixel of workspace width matters for reviewing 50-100 ad
    // rows at once (Steve's call, 2026-09-23). Restores on exit. Adjusted
    // during render (React's own pattern for "derive state from a prop/route
    // change," not an effect — an effect here would setState synchronously
    // inside itself, which triggers an avoidable extra render and is exactly
    // what the react-hooks/set-state-in-effect rule flags) whenever the route
    // actually changes, so a manual re-expand via the toggle mid-wizard is
    // never fought back closed on the next unrelated render.
    const LAUNCH_WIZARD_PATH = '/facebook-campaigns';
    const [isCollapsed, setIsCollapsed] = useState(() => location.pathname === LAUNCH_WIZARD_PATH);
    const [prevPath, setPrevPath] = useState(location.pathname);
    if (location.pathname !== prevPath) {
        setPrevPath(location.pathname);
        if (location.pathname === LAUNCH_WIZARD_PATH) setIsCollapsed(true);
        else if (prevPath === LAUNCH_WIZARD_PATH) setIsCollapsed(false);
    }

    const handleLogout = async () => {
        await logout();
        showSuccess('Logged out successfully');
        navigate('/login');
    };

    const menuItems = [
        { icon: LayoutDashboard, label: 'Dashboard', path: '/' },
        ...(hasPermission('pnl:read') ? [{ icon: DollarSign, label: 'Profit/Loss', path: '/pnl' }] : []),
        { icon: Search, label: 'Research', path: '/research', matchPrefixes: ['/research/'] },
        { icon: Wand2, label: 'Build Creatives', path: '/build-creatives', matchPaths: ['/image-ads', '/batch-generate', '/ad-remix', '/video-ads'] },
        { icon: ShoppingBag, label: 'Brands', path: '/brand-hub', matchPaths: ['/brands', '/products', '/profiles'] },
        { icon: Library, label: 'Libraries', path: '/libraries', matchPaths: ['/generated-ads', '/creative-library', '/copy-library'] },
        { icon: Target, label: 'Facebook', path: '/facebook-hub', matchPaths: ['/campaign-performance', '/auto-pause-rules', '/facebook-campaigns'] },
    ];

    const formatAccountId = (account) => {
        const rawId = account.id || account.account_id || account.accountId || '';
        return rawId.startsWith('act_') ? rawId : `act_${rawId}`;
    };

    const activeAccount = adAccounts.find(account => formatAccountId(account) === activeAccountId);

    return (
        <div className="flex h-screen bg-gray-50">
            {/* Sidebar */}
            <aside
                className={`${isCollapsed ? 'w-20' : 'w-64'} flex flex-col bg-white border-r border-gray-200 shadow-lg transition-all duration-300 ease-in-out relative`}
            >
                {/* Toggle Button */}
                <button
                    onClick={() => setIsCollapsed(!isCollapsed)}
                    className="absolute -right-3 top-9 bg-white border border-gray-200 rounded-full p-1 shadow-md z-10 text-gray-500 hover:text-gray-700"
                >
                    {isCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
                </button>

                {/* Logo / Brand */}
                <div className={`p-5 border-b border-gray-200 ${isCollapsed ? 'px-4' : ''}`}>
                    <div className={`flex items-center ${isCollapsed ? 'justify-center' : ''}`}>
                        {isCollapsed ? (
                            <BHMLogo size={36} />
                        ) : (
                            <img
                                src="/bhm_logo_1color_blue@3x.png"
                                alt="Bright Horizons Media"
                                className="h-8 w-auto object-contain object-left"
                            />
                        )}
                    </div>
                </div>

                {/* Navigation */}
                <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto overflow-x-hidden">
                    {menuItems.map((item) => {
                        const Icon = item.icon;

                        const isActive = location.pathname === item.path ||
                            (item.matchPaths && item.matchPaths.includes(location.pathname)) ||
                            (item.matchPrefixes && item.matchPrefixes.some(prefix => location.pathname.startsWith(prefix)));
                        return (
                            <Link
                                key={item.path}
                                to={item.path}
                                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-150 group ${
                                    isActive ? 'bg-gray-100 text-gray-900 font-medium' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                                } ${isCollapsed ? 'justify-center px-2' : ''}`}
                                title={isCollapsed ? item.label : ''}
                            >
                                <Icon size={18} className="flex-shrink-0 transition-colors" />
                                {!isCollapsed && <span className="text-sm whitespace-nowrap overflow-hidden">{item.label}</span>}
                            </Link>
                        );
                    })}
                </nav>

                {/* Bottom Section */}
                <div className="p-3 border-t border-gray-200 space-y-0.5">
                    {hasRole('admin') && (
                        <Link
                            to="/users"
                            className={`flex items-center gap-3 px-3 py-2.5 w-full rounded-lg transition-colors group ${
                                location.pathname === '/users'
                                    ? 'bg-gray-100 text-gray-900 font-medium'
                                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                            } ${isCollapsed ? 'justify-center px-2' : ''}`}
                            title={isCollapsed ? 'User Management' : ''}
                        >
                            <UserCog size={18} className="flex-shrink-0" />
                            {!isCollapsed && <span className="text-sm whitespace-nowrap overflow-hidden">User Management</span>}
                        </Link>
                    )}
                    <Link
                        to="/settings"
                        className={`flex items-center gap-3 px-3 py-2.5 w-full rounded-lg transition-colors group ${
                            location.pathname === '/settings'
                                ? 'bg-gray-100 text-gray-900 font-medium'
                                : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                        } ${isCollapsed ? 'justify-center px-2' : ''}`}
                        title={isCollapsed ? 'Settings' : ''}
                    >
                        <Settings size={18} className="flex-shrink-0" />
                        {!isCollapsed && <span className="text-sm whitespace-nowrap overflow-hidden">Settings</span>}
                    </Link>

                    {!isCollapsed && user && (
                        <div className="px-3 py-2.5 mt-1 bg-gray-50 rounded-lg border border-gray-200">
                            <div className="text-sm font-medium text-gray-900 truncate">
                                {user.name || user.email}
                            </div>
                            <div className="text-xs text-gray-500 truncate">{user.email}</div>
                        </div>
                    )}

                    <button
                        onClick={handleLogout}
                        className={`flex items-center gap-3 px-3 py-2.5 w-full text-gray-600 hover:bg-gray-100 hover:text-gray-900 rounded-lg transition-colors mt-1 ${isCollapsed ? 'justify-center px-2' : ''}`}
                        title={isCollapsed ? 'Logout' : ''}
                    >
                        <LogOut size={18} className="flex-shrink-0" />
                        {!isCollapsed && <span className="text-sm whitespace-nowrap overflow-hidden">Logout</span>}
                    </button>
                </div>
            </aside>

            {/* Main Content */}
            <main className="flex-1 overflow-y-auto bg-gray-50">
                <div className="p-5">
                    {/* A dead session is announced here rather than by redirecting to
                        the login screen: Joel works with several tabs open and unsaved
                        state, so signing back in is his call, not the app's.

                        The button opens login in a NEW tab on purpose. Navigating this
                        tab to /login unmounts CampaignProvider, and campaignData /
                        adsetData / adsData are plain useState — an in-progress bulk
                        build would be gone. Tokens live in localStorage, which is
                        shared across tabs, so signing in over there revives this tab
                        (authClient listens for the storage event and clears this
                        banner). */}
                    {sessionExpired && (
                        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-300 bg-gray-50 px-4 py-3">
                            <div>
                                <p className="text-sm font-semibold text-gray-900">Your session has expired</p>
                                <p className="text-sm text-gray-700">
                                    Anything on screen may be out of date, and nothing will save until you sign in.
                                    Sign in on the new tab and come back here — this page keeps whatever you were working on.
                                </p>
                            </div>
                            <button
                                onClick={() => window.open('/login', '_blank', 'noopener')}
                                className="shrink-0 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800"
                            >
                                Sign in (new tab)
                            </button>
                        </div>
                    )}
                    {/* This banner scopes Dashboard/P&L/performance views only (activeAccountId,
                        its own CampaignProvider state) — it does NOT affect the Facebook Campaigns
                        ad-launch wizard, which reads a completely separate `selectedAdAccount` from
                        its own nested CampaignProvider (see FacebookCampaigns.jsx). Showing both on
                        the same page reads as one "current account" control when it isn't — Steve
                        hit this directly: switching this dropdown left the wizard's own Ad Account
                        step and campaign list untouched, since they don't share state. Suppressed
                        here since Step 1 of that wizard is its own equivalent selector. */}
                    {adAccounts.length > 0 && location.pathname !== '/facebook-campaigns' && (
                        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
                            <div className="flex items-center gap-3">
                                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gray-100 text-gray-700">
                                    <BriefcaseBusiness size={18} />
                                </div>
                                <div>
                                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Meta account</p>
                                    <p className="text-sm text-gray-600">Primary data scope for performance and dashboard views.</p>
                                </div>
                            </div>
                            {adAccounts.length === 1 ? (
                                <div className="min-w-64 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm">
                                    <div className="font-medium text-gray-900 truncate">{adAccounts[0].name || formatAccountId(adAccounts[0])}</div>
                                    <div className="text-xs text-gray-500">{formatAccountId(adAccounts[0])}</div>
                                </div>
                            ) : (
                                <select
                                    value={activeAccountId}
                                    disabled={activeAccountLoading}
                                    onChange={(e) => setActiveAccountId(e.target.value)}
                                    className="min-w-72 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-900 shadow-sm focus:border-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-400 disabled:bg-gray-50 disabled:text-gray-400"
                                >
                                    {adAccounts.map(account => {
                                        const accountId = formatAccountId(account);
                                        return (
                                            <option key={accountId} value={accountId}>
                                                {account.name || accountId}
                                            </option>
                                        );
                                    })}
                                </select>
                            )}
                            {activeAccount && adAccounts.length > 1 && (
                                <p className="w-full text-right text-xs text-gray-400">{formatAccountId(activeAccount)}</p>
                            )}
                        </div>
                    )}
                    {['/image-ads', '/batch-generate', '/ad-remix', '/copy-library'].includes(location.pathname) && (
                        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
                            <div>
                                <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Vertical filter</p>
                                <p className="text-sm text-gray-600">Scopes the brand list for this workflow.</p>
                            </div>
                            <div className="flex flex-wrap gap-2">
                                {VERTICAL_FILTERS.map(vertical => (
                                    <button
                                        key={vertical.id}
                                        type="button"
                                        onClick={() => setActiveVerticalFilter(vertical.id)}
                                        className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                                            activeVerticalFilter === vertical.id
                                                ? 'bg-gray-900 text-white shadow-sm'
                                                : 'bg-gray-100 text-gray-600 hover:bg-gray-200 hover:text-gray-900'
                                        }`}
                                    >
                                        {vertical.label}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}
                    <Outlet />
                </div>
            </main>
            <AskAiWidget />
        </div>
    );
}
