import React, { useState } from 'react';
import { Link, useLocation, Outlet, useNavigate } from 'react-router-dom';
import { LayoutDashboard, Package, Users, Video, Wand2, Settings, LogOut, Image, ShoppingBag, Target, ChevronLeft, ChevronRight, FileImage, Search, ChevronDown, UserCog, TrendingDown, Zap, Shuffle, PauseCircle, Megaphone, BookOpen, BriefcaseBusiness, DollarSign } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { useBrands } from '../context/BrandContext';
import { useCampaign } from '../context/CampaignContext';
import { VERTICAL_FILTERS } from '../lib/verticals';

// BHM mark — gradient circle with horizon lines, sized for 40×40 container
function BHMLogo({ size = 40 }) {
    return (
        <svg width={size} height={size} viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
                <linearGradient id="bhm-grad" x1="20" y1="0" x2="20" y2="40" gradientUnits="userSpaceOnUse">
                    <stop offset="0%" stopColor="#F0547A" />
                    <stop offset="100%" stopColor="#FFAA00" />
                </linearGradient>
                <clipPath id="bhm-circle">
                    <circle cx="20" cy="20" r="18" />
                </clipPath>
            </defs>
            <circle cx="20" cy="20" r="18" fill="url(#bhm-grad)" />
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
    const [expandedMenus, setExpandedMenus] = useState({ Brands: false, Research: false, Facebook: true, 'Build Creatives': true });
    const [isCollapsed, setIsCollapsed] = useState(false);

    const handleLogout = async () => {
        await logout();
        showSuccess('Logged out successfully');
        navigate('/login');
    };

    const menuItems = [
        { icon: LayoutDashboard, label: 'Dashboard', path: '/' },
        ...(hasPermission('pnl:read') ? [{ icon: DollarSign, label: 'Profit/Loss', path: '/pnl' }] : []),
        {
            icon: Search,
            label: 'Research',
            subItems: [
                { label: 'Research', path: '/research' },
                { label: 'Scrape Brand Ads', path: '/research/brand-scrapes' },
                { label: 'Settings', path: '/research/settings' }
            ]
        },
        {
            icon: Wand2,
            label: 'Build Creatives',
            subItems: [
                { label: 'Image Ad',         path: '/image-ads',       icon: Image },
                { label: 'Batch Generate',   path: '/batch-generate',  icon: Zap },
                { label: 'Build New Ad',     path: '/ad-remix',        icon: Shuffle },
                { label: 'Video Ad',         path: '/video-ads',       icon: Video },
            ]
        },
        {
            icon: ShoppingBag,
            label: 'Brands',
            subItems: [
                { label: 'Brands', path: '/brands' },
                { label: 'Products', path: '/products' },
                { label: 'Customer Profiles', path: '/profiles' }
            ]
        },
        { icon: FileImage, label: 'Ad Library', path: '/generated-ads' },
        {
            icon: Target,
            label: 'Facebook',
            subItems: [
                { label: 'Performance',      path: '/campaign-performance', icon: TrendingDown },
                { label: 'Auto-Pause Rules', path: '/auto-pause-rules',    icon: PauseCircle },
                { label: 'Campaign Builder', path: '/facebook-campaigns',  icon: Megaphone },
            ]
        },
        { icon: BookOpen, label: 'Copy Library', path: '/copy-library' },
    ];

    const toggleMenu = (label) => {
        setExpandedMenus(prev => ({
            ...prev,
            [label]: !prev[label]
        }));
    };

    const formatAccountId = (account) => {
        const rawId = account.id || account.account_id || account.accountId || '';
        return rawId.startsWith('act_') ? rawId : `act_${rawId}`;
    };

    const activeAccount = adAccounts.find(account => formatAccountId(account) === activeAccountId);

    return (
        <div className="flex h-screen bg-gray-50">
            {/* Sidebar */}
            <aside
                className={`${isCollapsed ? 'w-20' : 'w-64'} flex flex-col shadow-lg transition-all duration-300 ease-in-out relative`}
                style={{ backgroundColor: '#2D2463' }}
            >
                {/* Toggle Button */}
                <button
                    onClick={() => setIsCollapsed(!isCollapsed)}
                    className="absolute -right-3 top-9 bg-white rounded-full p-1 shadow-md z-10 text-gray-500 hover:text-gray-700"
                >
                    {isCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
                </button>

                {/* Logo / Brand */}
                <div className={`p-5 border-b border-white/10 ${isCollapsed ? 'px-4' : ''}`}>
                    <div className={`flex items-center ${isCollapsed ? 'justify-center' : ''}`}>
                        {isCollapsed ? (
                            <BHMLogo size={36} />
                        ) : (
                            <img
                                src="/bhm-logo.png"
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

                        if (item.subItems) {
                            const isExpanded = expandedMenus[item.label];
                            const isActive = item.subItems.some(sub => location.pathname === sub.path.split('?')[0]);

                            return (
                                <div key={item.label} className="space-y-0.5">
                                    <button
                                        onClick={() => {
                                            if (!isCollapsed) toggleMenu(item.label);
                                            if (item.subItems?.[0]?.path) navigate(item.subItems[0].path);
                                        }}
                                        className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-150 group ${
                                            isActive ? 'bg-white/15 text-white' : 'text-white/60 hover:bg-white/10 hover:text-white'
                                        } ${isCollapsed ? 'justify-center px-2' : ''}`}
                                        title={isCollapsed ? item.label : ''}
                                    >
                                        <Icon size={18} className="flex-shrink-0 transition-colors" />
                                        {!isCollapsed && (
                                            <>
                                                <span className="flex-1 text-left text-sm whitespace-nowrap overflow-hidden">{item.label}</span>
                                                {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                            </>
                                        )}
                                    </button>

                                    {!isCollapsed && isExpanded && (
                                        <div className="pl-9 space-y-0.5">
                                            {item.subItems.map(subItem => {
                                                const SubIcon = subItem.icon;
                                                const subPath = subItem.path.split('?')[0];
                                                const subQuery = subItem.path.includes('?') ? subItem.path.split('?')[1] : null;
                                                const isSubActive = location.pathname === subPath &&
                                                    (!subQuery || location.search === `?${subQuery}`);
                                                return (
                                                    <Link
                                                        key={subItem.path}
                                                        to={subItem.path}
                                                        className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                                                            isSubActive
                                                                ? 'text-white bg-white/15 font-medium'
                                                                : 'text-white/50 hover:text-white hover:bg-white/10'
                                                        }`}
                                                    >
                                                        {SubIcon && <SubIcon size={13} className="flex-shrink-0" />}
                                                        {subItem.label}
                                                    </Link>
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                            );
                        }

                        const isActive = location.pathname === item.path;
                        return (
                            <Link
                                key={item.path}
                                to={item.path}
                                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-150 group ${
                                    isActive ? 'bg-white/15 text-white font-medium' : 'text-white/60 hover:bg-white/10 hover:text-white'
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
                <div className="p-3 border-t border-white/10 space-y-0.5">
                    {hasRole('admin') && (
                        <Link
                            to="/users"
                            className={`flex items-center gap-3 px-3 py-2.5 w-full rounded-lg transition-colors group ${
                                location.pathname === '/users'
                                    ? 'bg-white/15 text-white font-medium'
                                    : 'text-white/60 hover:bg-white/10 hover:text-white'
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
                                ? 'bg-white/15 text-white font-medium'
                                : 'text-white/60 hover:bg-white/10 hover:text-white'
                        } ${isCollapsed ? 'justify-center px-2' : ''}`}
                        title={isCollapsed ? 'Settings' : ''}
                    >
                        <Settings size={18} className="flex-shrink-0" />
                        {!isCollapsed && <span className="text-sm whitespace-nowrap overflow-hidden">Settings</span>}
                    </Link>

                    {!isCollapsed && user && (
                        <div className="px-3 py-2.5 mt-1 bg-white/8 rounded-lg border border-white/10">
                            <div className="text-sm font-medium text-white truncate">
                                {user.name || user.email}
                            </div>
                            <div className="text-xs text-white/40 truncate">{user.email}</div>
                        </div>
                    )}

                    <button
                        onClick={handleLogout}
                        className={`flex items-center gap-3 px-3 py-2.5 w-full text-red-400 hover:bg-red-500/10 hover:text-red-300 rounded-lg transition-colors mt-1 ${isCollapsed ? 'justify-center px-2' : ''}`}
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
                        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                            <div>
                                <p className="text-sm font-semibold text-amber-900">Your session has expired</p>
                                <p className="text-sm text-amber-800">
                                    Anything on screen may be out of date, and nothing will save until you sign in.
                                    Sign in on the new tab and come back here — this page keeps whatever you were working on.
                                </p>
                            </div>
                            <button
                                onClick={() => window.open('/login', '_blank', 'noopener')}
                                className="shrink-0 rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700"
                            >
                                Sign in (new tab)
                            </button>
                        </div>
                    )}
                    {adAccounts.length > 0 && (
                        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-indigo-100 bg-white px-4 py-3 shadow-sm">
                            <div className="flex items-center gap-3">
                                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
                                    <BriefcaseBusiness size={18} />
                                </div>
                                <div>
                                    <p className="text-xs font-semibold uppercase tracking-wide text-indigo-500">Meta account</p>
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
                                    className="min-w-72 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-gray-50 disabled:text-gray-400"
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
                                                ? 'bg-indigo-600 text-white shadow-sm'
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
        </div>
    );
}
