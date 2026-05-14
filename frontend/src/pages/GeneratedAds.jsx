import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import React, { useState, useEffect, useMemo } from 'react';
import { Download, Trash2, Search, Filter, CheckSquare, Square, FileDown, ExternalLink, FileText, Image, LayoutGrid, List, Film, Rocket, X, Zap, AlertTriangle } from 'lucide-react';
import { useBrands } from '../context/BrandContext';
import { useNavigate } from 'react-router-dom';
import PushToMetaModal from '../components/PushToMetaModal';
import BatchPushModal from '../components/BatchPushModal';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

export default function GeneratedAds() {
    // Force rebuild
    const { brands } = useBrands();
    const { showError, showWarning, showSuccess } = useToast();
    const { authFetch } = useAuth();
    const navigate = useNavigate();
    const [ads, setAds] = useState([]);
    const [loading, setLoading] = useState(true);
    const [selectedBundles, setSelectedBundles] = useState(new Set());
    // Track bundle IDs whose thumbnails failed to load in the browser
    const [brokenBundles, setBrokenBundles] = useState(new Set());
    const [searchTerm, setSearchTerm] = useState('');
    const [selectedBrand, setSelectedBrand] = useState('');
    const [viewMode, setViewMode] = useState(() => {
        try {
            console.log('Initializing GeneratedAds viewMode');
            return localStorage.getItem('generatedAdsViewMode') || 'grid';
        } catch (e) {
            console.error('Error accessing localStorage:', e);
            return 'grid';
        }
    });

    // Modal state
    const [selectedBundleId, setSelectedBundleId] = useState(null);
    const [viewedImage, setViewedImage] = useState(null);
    const [imgError, setImgError] = useState(false);
    const [deleteConfirmation, setDeleteConfirmation] = useState({ show: false, bundleId: null, bundleAds: [] });

    // Push to Campaign modal state (single ad)
    const [pushModal, setPushModal] = useState({ show: false, ad: null });
    // Bulk push modal state (multi-select)
    const [bulkPushOpen, setBulkPushOpen] = useState(false);

    const openPushModal = (ad) => {
        setPushModal({ show: true, ad });
    };

    // Build BatchPushModal items from currently selected bundles
    const buildBulkPushItems = () => {
        const seen = new Set();
        return ads
            .filter(ad => selectedBundles.has(ad.ad_bundle_id || `legacy_${ad.id}`) && ad.image_url)
            .reduce((acc, ad) => {
                const bundleId = ad.ad_bundle_id || `legacy_${ad.id}`;
                if (!seen.has(bundleId)) {
                    seen.add(bundleId);
                    acc.push({
                        key: `lib_${ad.id}`,
                        imageUrl: ad.image_url,
                        headline: ad.headline || '',
                        body: ad.body || '',
                        cta: ad.cta || 'LEARN_MORE',
                        variantName: ad.headline ? ad.headline.slice(0, 30) : `Ad ${ad.id}`,
                        sizeLabel: ad.size_name || '—',
                    });
                }
                return acc;
            }, []);
    };

    useEffect(() => {
        fetchAds();
    }, [selectedBrand]);

    const fetchAds = async () => {
        try {
            setLoading(true);
            const params = new URLSearchParams();
            if (selectedBrand) params.append('brand_id', selectedBrand);

            const response = await authFetch(`${API_URL}/generated-ads?${params}`);
            if (response.ok) {
                const data = await response.json();
                setAds(Array.isArray(data) ? data : []);
            } else {
                setAds([]);
            }
        } catch (error) {
            console.error('Error fetching ads:', error);
            setAds([]);
        } finally {
            setLoading(false);
        }
    };

    // Group ads by bundle
    const bundles = useMemo(() => {
        const groups = {};
        ads.forEach(ad => {
            const bundleId = ad.ad_bundle_id || `legacy_${ad.id}`;
            if (!groups[bundleId]) {
                groups[bundleId] = [];
            }
            groups[bundleId].push(ad);
        });

        // Convert to array and sort by created_at (newest first)
        return Object.values(groups).sort((a, b) => {
            const dateA = new Date(a[0].created_at);
            const dateB = new Date(b[0].created_at);
            return dateB - dateA;
        });
    }, [ads]);

    // Filter bundles
    const filteredBundles = useMemo(() => {
        return bundles.filter(bundle => {
            // Check if any ad in the bundle matches the search term
            const matchesSearch = bundle.some(ad =>
                (ad.headline?.toLowerCase() || '').includes(searchTerm.toLowerCase()) ||
                (ad.body?.toLowerCase() || '').includes(searchTerm.toLowerCase()) ||
                (ad.cta?.toLowerCase() || '').includes(searchTerm.toLowerCase())
            );
            return searchTerm === '' || matchesSearch;
        });
    }, [bundles, searchTerm]);

    const toggleSelectBundle = (bundleId, e) => {
        e.stopPropagation();
        const newSelected = new Set(selectedBundles);
        if (newSelected.has(bundleId)) {
            newSelected.delete(bundleId);
        } else {
            newSelected.add(bundleId);
        }
        setSelectedBundles(newSelected);
    };

    const toggleSelectAll = () => {
        if (selectedBundles.size === filteredBundles.length) {
            setSelectedBundles(new Set());
        } else {
            const allBundleIds = filteredBundles.map(b => b[0].ad_bundle_id || `legacy_${b[0].id}`);
            setSelectedBundles(new Set(allBundleIds));
        }
    };

    const handleDelete = (bundleId, e) => {
        e.stopPropagation();

        console.log('Delete clicked for bundle:', bundleId);

        // Find all ads in this bundle
        const bundleAds = ads.filter(ad => (ad.ad_bundle_id || `legacy_${ad.id}`) === bundleId);

        // Show confirmation modal
        setDeleteConfirmation({
            show: true,
            bundleId,
            bundleAds
        });
    };

    const confirmDelete = async () => {
        const { bundleId, bundleAds } = deleteConfirmation;

        // Close modal immediately
        setDeleteConfirmation({ show: false, bundleId: null, bundleAds: [] });

        console.log(`Deleting ${bundleAds.length} ads from bundle ${bundleId}`);

        try {
            // Delete all ads in the bundle
            const deletePromises = bundleAds.map(ad => {
                console.log(`Deleting ad ${ad.id}`);
                return authFetch(`${API_URL}/generated-ads/${ad.id}`, {
                    method: 'DELETE'
                }).then(response => {
                    if (!response.ok) {
                        throw new Error(`Failed to delete ad ${ad.id}`);
                    }
                    return response.json();
                });
            });

            await Promise.all(deletePromises);

            console.log('All ads deleted successfully');

            // Show success message first
            showSuccess(`Successfully deleted ${bundleAds.length} ad${bundleAds.length > 1 ? 's' : ''}`);

            // Remove deleted ads from local state (instead of refetching)
            setAds(prevAds => prevAds.filter(ad => !bundleAds.find(deletedAd => deletedAd.id === ad.id)));

            // Remove from selected bundles
            setSelectedBundles(prev => {
                const newSet = new Set(prev);
                newSet.delete(bundleId);
                return newSet;
            });

            // Close modal if open
            if (selectedBundleId === bundleId) {
                setSelectedBundleId(null);
            }
        } catch (error) {
            console.error('Error deleting bundle:', error);
            showError(`Failed to delete ad bundle: ${error.message}`);
        }
    };

    const cancelDelete = () => {
        console.log('Delete cancelled by user');
        setDeleteConfirmation({ show: false, bundleId: null, bundleAds: [] });
    };

    const handleExportCSV = async () => {
        if (selectedBundles.size === 0) {
            showWarning('Please select ads to export');
            return;
        }

        // Get all ad IDs from selected bundles
        const selectedAdIds = ads
            .filter(ad => selectedBundles.has(ad.ad_bundle_id || `legacy_${ad.id}`))
            .map(ad => ad.id);

        try {
            const response = await authFetch(`${API_URL}/generated-ads/export-csv`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids: selectedAdIds })
            });

            if (!response.ok) throw new Error('Export failed');

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `generated-ads-${Date.now()}.csv`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (error) {
            console.error('Error exporting:', error);
            showError('Failed to export ads');
        }
    };

    const handleViewModeChange = (mode) => {
        setViewMode(mode);
        localStorage.setItem('generatedAdsViewMode', mode);
    };

    // Mark a bundle's thumbnail as broken (image failed to load in browser)
    const markBroken = (bundleId) => {
        setBrokenBundles(prev => new Set([...prev, bundleId]));
    };

    // Delete all bundles whose thumbnails failed to load
    const handleClearBroken = async () => {
        const toDelete = [...brokenBundles];
        if (toDelete.length === 0) return;
        for (const bundleId of toDelete) {
            const bundleAds = ads.filter(ad => (ad.ad_bundle_id || `legacy_${ad.id}`) === bundleId);
            try {
                await Promise.all(bundleAds.map(ad =>
                    authFetch(`${API_URL}/generated-ads/${ad.id}`, { method: 'DELETE' })
                ));
                setAds(prev => prev.filter(ad => !bundleAds.find(d => d.id === ad.id)));
            } catch (e) {
                console.error('Failed to delete broken bundle', bundleId, e);
            }
        }
        setBrokenBundles(new Set());
        showSuccess(`Removed ${toDelete.length} broken ad${toDelete.length !== 1 ? 's' : ''}`);
    };

    // Store selected images in localStorage and navigate to campaign builder
    const handleUseInCampaignBuilder = () => {
        const selectedAds = ads.filter(ad =>
            selectedBundles.has(ad.ad_bundle_id || `legacy_${ad.id}`) && ad.image_url
        );
        // Dedupe by bundle — pick the square/first image per bundle
        const seen = new Set();
        const pending = [];
        selectedAds.forEach(ad => {
            const bundleId = ad.ad_bundle_id || `legacy_${ad.id}`;
            if (!seen.has(bundleId)) {
                seen.add(bundleId);
                pending.push({
                    id: ad.id,
                    imageUrl: ad.image_url,
                    name: ad.headline || `Library Ad ${ad.id}`,
                    headline: ad.headline || '',
                    body: ad.body || '',
                    cta: ad.cta || 'LEARN_MORE'
                });
            }
        });
        localStorage.setItem('pendingLibraryImages', JSON.stringify(pending));
        navigate('/facebook-campaigns');
    };

    // Convert size_name → short ratio label (e.g. "Square" → "1×1", "Story" → "9×16")
    const sizeRatio = (ad) => {
        const name = (ad.size_name || '').toLowerCase();
        if (name.includes('story')) return '9×16';
        if (name.includes('portrait')) return '4×5';
        if (name.includes('square')) return '1×1';
        // Fall back to parsing dimensions string e.g. "1080x1920"
        const dims = ad.dimensions || '';
        const m = dims.match(/(\d+)\s*[x×]\s*(\d+)/i);
        if (m) {
            const w = parseInt(m[1]), h = parseInt(m[2]);
            if (h > w * 1.6) return '9×16';
            if (h > w * 1.1) return '4×5';
            return '1×1';
        }
        return ad.size_name || dims || '—';
    };

    // Modal Helpers
    const openModal = (bundle) => {
        const bundleId = bundle[0].ad_bundle_id || `legacy_${bundle[0].id}`;
        setSelectedBundleId(bundleId);
        // Default to square image or first image
        const squareImg = bundle.find(ad => ad.size_name?.includes('Square')) || bundle[0];
        setViewedImage(squareImg);
        setImgError(false);
    };

    const currentBundle = selectedBundleId
        ? bundles.find(b => (b[0].ad_bundle_id || `legacy_${b[0].id}`) === selectedBundleId)
        : null;

    console.log('Rendering GeneratedAds', { brands, adsCount: ads.length, viewMode });

    return (
        <div className="max-w-7xl mx-auto">
            {/* Header */}
            <div className="mb-8 flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
                        <Image size={32} className="text-amber-600" />
                        Generated Ads
                    </h1>
                    <p className="text-gray-600 mt-1">View and manage all your AI-generated ad creatives</p>
                </div>

                {/* View Toggle */}
                <div className="flex items-center bg-white border border-gray-200 rounded-lg p-1 shadow-sm">
                    <button
                        onClick={() => handleViewModeChange('list')}
                        className={`p-2 rounded-md transition-colors ${viewMode === 'list' ? 'bg-purple-100 text-purple-600' : 'text-gray-400 hover:text-gray-600'}`}
                        title="List View"
                    >
                        <List size={20} />
                    </button>
                    <button
                        onClick={() => handleViewModeChange('grid')}
                        className={`p-2 rounded-md transition-colors ${viewMode === 'grid' ? 'bg-purple-100 text-purple-600' : 'text-gray-400 hover:text-gray-600'}`}
                        title="Grid View"
                    >
                        <LayoutGrid size={20} />
                    </button>
                </div>
            </div>

            {/* Filters and Actions */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-6">
                <div className="flex flex-col md:flex-row gap-4 mb-4">
                    {/* Search */}
                    <div className="flex-1 relative">
                        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={20} />
                        <input
                            type="text"
                            placeholder="Search ads..."
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                            className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-600 focus:border-transparent"
                        />
                    </div>

                    {/* Brand Filter */}
                    <div className="relative">
                        <Filter className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" size={20} />
                        <select
                            value={selectedBrand}
                            onChange={(e) => setSelectedBrand(e.target.value)}
                            className="pl-10 pr-8 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-600 focus:border-transparent appearance-none bg-white"
                        >
                            <option value="">All Brands</option>
                            {brands.map(brand => (
                                <option key={brand.id} value={brand.id}>{brand.name}</option>
                            ))}
                        </select>
                    </div>
                </div>

                {/* Broken image cleanup notice */}
                {brokenBundles.size > 0 && (
                    <div className="flex items-center gap-3 p-3 bg-red-50 border border-red-200 rounded-lg mb-3">
                        <AlertTriangle size={16} className="text-red-500 flex-shrink-0" />
                        <span className="text-sm text-red-800 flex-1">
                            {brokenBundles.size} bundle{brokenBundles.size !== 1 ? 's' : ''} failed to load
                        </span>
                        <button
                            onClick={handleClearBroken}
                            className="flex items-center gap-2 px-3 py-1.5 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors text-sm font-medium"
                        >
                            <Trash2 size={14} />
                            Remove {brokenBundles.size} Broken
                        </button>
                    </div>
                )}

                {/* Batch Actions */}
                {selectedBundles.size > 0 && (
                    <div className="flex items-center gap-3 p-3 bg-purple-50 border border-purple-200 rounded-lg">
                        <span className="text-sm font-medium text-purple-900">
                            {selectedBundles.size} bundle{selectedBundles.size > 1 ? 's' : ''} selected
                        </span>
                        <div className="flex-1"></div>
                        <button
                            onClick={() => {
                                const items = buildBulkPushItems();
                                if (items.length === 0) {
                                    showError('No images available to push. Selected ads may still be generating or have failed.');
                                } else {
                                    setBulkPushOpen(true);
                                }
                            }}
                            className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors text-sm font-medium"
                        >
                            <Rocket size={16} />
                            Push to Meta
                        </button>
                        <button
                            onClick={handleUseInCampaignBuilder}
                            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
                        >
                            <Zap size={16} />
                            Campaign Builder
                        </button>
                        <button
                            onClick={handleExportCSV}
                            className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors text-sm font-medium"
                        >
                            <FileDown size={16} />
                            Export CSV
                        </button>
                        <button
                            onClick={() => setSelectedBundles(new Set())}
                            className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition-colors text-sm font-medium"
                        >
                            Clear
                        </button>
                    </div>
                )}
            </div>

            {/* Ads Content */}
            {
                loading ? (
                    <div className="text-center py-12">
                        <div className="w-16 h-16 border-4 border-purple-200 border-t-purple-600 rounded-full animate-spin mx-auto"></div>
                        <p className="text-gray-600 mt-4">Loading ads...</p>
                    </div>
                ) : filteredBundles.length === 0 ? (
                    <div className="text-center py-12 bg-white rounded-xl shadow-sm border border-gray-200">
                        <p className="text-gray-600">No ads found. Generate some ads to get started!</p>
                    </div>
                ) : viewMode === 'grid' ? (
                    // GRID VIEW
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                        {filteredBundles.map(bundle => {
                            const mainAd = bundle.find(ad => ad.size_name?.includes('Square')) || bundle[0];
                            const bundleId = bundle[0].ad_bundle_id || `legacy_${bundle[0].id}`;
                            const isSelected = selectedBundles.has(bundleId);
                            const isBroken = brokenBundles.has(bundleId);
                            const isVideo = mainAd.media_type === 'video';
                            const mediaUrl = isVideo ? (mainAd.thumbnail_url || mainAd.video_url) : mainAd.image_url;

                            return (
                                <div
                                    key={bundleId}
                                    onClick={() => !isBroken && openModal(bundle)}
                                    className={`group bg-white rounded-xl shadow-sm border-2 transition-all hover:shadow-lg cursor-pointer overflow-hidden ${
                                        isBroken ? 'border-red-300 opacity-60' :
                                        isSelected ? 'border-purple-600 ring-2 ring-purple-200' : 'border-gray-200 hover:border-purple-300'
                                    }`}
                                >
                                    {/* Media with overlays */}
                                    <div className="relative aspect-square bg-gray-100">
                                        {isBroken ? (
                                            <div className="w-full h-full flex flex-col items-center justify-center text-red-400 gap-2">
                                                <AlertTriangle size={32} />
                                                <span className="text-xs font-medium text-red-500">Failed to load</span>
                                            </div>
                                        ) : isVideo ? (
                                            <video
                                                src={mainAd.video_url}
                                                poster={mainAd.thumbnail_url}
                                                className="w-full h-full object-cover"
                                                muted
                                                playsInline
                                                onMouseEnter={(e) => e.target.play()}
                                                onMouseLeave={(e) => { e.target.pause(); e.target.currentTime = 0; }}
                                            />
                                        ) : (
                                            <img
                                                src={mediaUrl}
                                                alt={mainAd.headline}
                                                className="w-full h-full object-cover"
                                                onError={() => markBroken(bundleId)}
                                            />
                                        )}

                                        {/* Media Type Badge */}
                                        {isVideo && !isBroken && (
                                            <div className="absolute top-3 right-12 bg-purple-600/90 backdrop-blur-sm text-white px-2 py-1 rounded-lg text-xs font-medium flex items-center gap-1">
                                                <Film size={12} /> Video
                                            </div>
                                        )}

                                        {/* Select Checkbox */}
                                        <button
                                            onClick={(e) => toggleSelectBundle(bundleId, e)}
                                            className="absolute top-3 left-3 p-2 bg-white/90 backdrop-blur-sm rounded-lg shadow-md hover:bg-white transition-colors"
                                        >
                                            {isSelected ? (
                                                <CheckSquare className="text-purple-600" size={20} />
                                            ) : (
                                                <Square className="text-gray-400" size={20} />
                                            )}
                                        </button>

                                        {/* Delete Button — visible on group hover (CSS group class on card) */}
                                        <button
                                            onClick={(e) => handleDelete(bundleId, e)}
                                            className="absolute top-3 right-3 p-2 bg-red-500/90 backdrop-blur-sm text-white rounded-lg shadow-md hover:bg-red-600 transition-all opacity-0 group-hover:opacity-100"
                                            title="Delete Bundle"
                                        >
                                            <Trash2 size={16} />
                                        </button>
                                    </div>

                                    {/* Dimension strip — below image on white background, always readable */}
                                    {!isBroken && (
                                        <div className="flex items-center justify-center gap-1.5 px-3 py-2 border-t border-gray-100 bg-white">
                                            {bundle.map((ad, i) => (
                                                <span
                                                    key={i}
                                                    className="text-xs font-semibold text-gray-600 bg-gray-100 rounded px-2 py-0.5 tracking-wide"
                                                >
                                                    {sizeRatio(ad)}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                ) : (
                    // LIST VIEW
                    <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
                        <table className="w-full text-left">
                            <thead className="bg-gray-50 border-b border-gray-200">
                                <tr>
                                    <th className="px-6 py-3 w-12">
                                        <button
                                            onClick={toggleSelectAll}
                                            className="text-gray-400 hover:text-gray-600"
                                        >
                                            {selectedBundles.size === filteredBundles.length && filteredBundles.length > 0 ? (
                                                <CheckSquare size={20} className="text-amber-600" />
                                            ) : (
                                                <Square size={20} />
                                            )}
                                        </button>
                                    </th>
                                    <th className="px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Ad Creative</th>
                                    <th className="px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Headline</th>
                                    <th className="px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Body</th>
                                    <th className="px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">Created</th>
                                    <th className="px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-200">
                                {filteredBundles.map(bundle => {
                                    const mainAd = bundle.find(ad => ad.size_name?.includes('Square')) || bundle[0];
                                    const bundleId = bundle[0].ad_bundle_id || `legacy_${bundle[0].id}`;
                                    const isSelected = selectedBundles.has(bundleId);
                                    const isVideo = mainAd.media_type === 'video';

                                    return (
                                        <tr
                                            key={bundleId}
                                            onClick={() => openModal(bundle)}
                                            className={`hover:bg-gray-50 cursor-pointer transition-colors ${isSelected ? 'bg-amber-50' : ''}`}
                                        >
                                            <td className="px-6 py-4">
                                                <button
                                                    onClick={(e) => toggleSelectBundle(bundleId, e)}
                                                    className="text-gray-400 hover:text-gray-600"
                                                >
                                                    {isSelected ? (
                                                        <CheckSquare size={20} className="text-amber-600" />
                                                    ) : (
                                                        <Square size={20} />
                                                    )}
                                                </button>
                                            </td>
                                            <td className="px-6 py-4">
                                                <div className="flex items-center gap-3">
                                                    <div className="h-12 w-12 rounded-lg overflow-hidden bg-gray-100 border border-gray-200 flex-shrink-0 relative">
                                                        {isVideo ? (
                                                            <>
                                                                <video
                                                                    src={mainAd.video_url}
                                                                    poster={mainAd.thumbnail_url}
                                                                    className="h-full w-full object-cover"
                                                                    muted
                                                                />
                                                                <div className="absolute bottom-0 right-0 bg-purple-600 text-white p-0.5 rounded-tl">
                                                                    <Film size={10} />
                                                                </div>
                                                            </>
                                                        ) : (
                                                            <img
                                                                src={mainAd.image_url}
                                                                alt="Thumbnail"
                                                                className="h-full w-full object-cover"
                                                            />
                                                        )}
                                                    </div>
                                                    <div className="flex gap-1 flex-wrap">
                                                        {bundle.map((ad, i) => (
                                                            <span key={i} className="text-xs font-semibold text-gray-600 bg-gray-100 px-2 py-0.5 rounded tracking-wide">
                                                                {sizeRatio(ad)}
                                                            </span>
                                                        ))}
                                                    </div>
                                                </div>
                                            </td>
                                            <td className="px-6 py-4">
                                                <p className="text-sm font-medium text-gray-900 line-clamp-1">{mainAd.headline || 'Untitled Ad'}</p>
                                            </td>
                                            <td className="px-6 py-4 max-w-xs">
                                                <p className="text-sm text-gray-500 line-clamp-1">{mainAd.body}</p>
                                            </td>
                                            <td className="px-6 py-4 whitespace-nowrap">
                                                <span className="text-sm text-gray-500">{new Date(mainAd.created_at).toLocaleDateString()}</span>
                                            </td>
                                            <td className="px-6 py-4 text-right">
                                                <div className="flex items-center justify-end gap-2">
                                                    <button
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            openModal(bundle);
                                                        }}
                                                        className="p-2 text-gray-400 hover:text-amber-600 hover:bg-amber-50 rounded-lg transition-colors"
                                                        title="View Details"
                                                    >
                                                        <ExternalLink size={18} />
                                                    </button>
                                                    <button
                                                        onClick={(e) => handleDelete(bundleId, e)}
                                                        className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                                                        title="Delete Bundle"
                                                    >
                                                        <Trash2 size={18} />
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )
            }

            {/* Select All (if ads exist) */}
            {
                filteredBundles.length > 0 && (
                    <div className="mt-6 flex justify-center">
                        <button
                            onClick={toggleSelectAll}
                            className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium"
                        >
                            {selectedBundles.size === filteredBundles.length ? (
                                <>
                                    <CheckSquare className="text-amber-600" size={16} />
                                    Deselect All
                                </>
                            ) : (
                                <>
                                    <Square className="text-gray-400" size={16} />
                                    Select All ({filteredBundles.length})
                                </>
                            )}
                        </button>
                    </div>
                )
            }

            {/* Details Modal */}
            {
                selectedBundleId && currentBundle && viewedImage && (
                    <div
                        className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4"
                        onClick={() => setSelectedBundleId(null)}
                    >
                        <div
                            className="bg-white rounded-2xl shadow-2xl max-w-5xl w-full max-h-[90vh] overflow-y-auto"
                            onClick={(e) => e.stopPropagation()}
                        >
                            {/* Modal Header */}
                            <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between rounded-t-2xl z-10">
                                <h3 className="text-xl font-bold text-gray-900">Ad Bundle Details</h3>
                                <button
                                    onClick={() => setSelectedBundleId(null)}
                                    className="w-8 h-8 rounded-full hover:bg-gray-100 flex items-center justify-center transition-colors"
                                >
                                    <span className="text-2xl text-gray-500">×</span>
                                </button>
                            </div>

                            {/* Modal Content */}
                            <div className="p-6">
                                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                    {/* Media Preview Section */}
                                    <div className="space-y-4">
                                        {/* Main Media — aspect ratio adapts to format */}
                                        {(() => {
                                            const sizeName = (viewedImage.size_name || '').toLowerCase();
                                            const dims = viewedImage.dimensions || '';
                                            const isStory = sizeName.includes('story') || /1080.?x.?1920/i.test(dims);
                                            const isPortrait = sizeName.includes('portrait') || /1080.?x.?1350/i.test(dims);
                                            const aspectClass = isStory ? 'aspect-[9/16]' : isPortrait ? 'aspect-[4/5]' : 'aspect-square';
                                            return (
                                        <div className={`bg-gray-100 rounded-xl overflow-hidden ${aspectClass} flex items-center justify-center relative`}>
                                            {imgError ? (
                                                <div className="p-8 text-center text-red-500 bg-red-50">
                                                    <p className="font-bold mb-2">Failed to load media</p>
                                                </div>
                                            ) : viewedImage.media_type === 'video' ? (
                                                <video
                                                    src={viewedImage.video_url}
                                                    poster={viewedImage.thumbnail_url}
                                                    className="w-full h-full object-contain"
                                                    controls
                                                    onError={() => setImgError(true)}
                                                />
                                            ) : (
                                                <img
                                                    src={viewedImage.image_url}
                                                    alt="Selected Ad"
                                                    className="w-full h-full object-contain"
                                                    onError={() => setImgError(true)}
                                                />
                                            )}
                                            {viewedImage.media_type === 'video' && (
                                                <div className="absolute top-3 right-3 bg-purple-600/90 backdrop-blur-sm text-white px-2 py-1 rounded-lg text-xs font-medium flex items-center gap-1">
                                                    <Film size={12} /> Video
                                                </div>
                                            )}
                                        </div>
                                            );
                                        })()}

                                        {/* Bundle Thumbnails */}
                                        {currentBundle.length > 1 && (
                                            <div>
                                                <p className="text-sm font-medium text-gray-700 mb-2">Available Sizes:</p>
                                                <div className="flex gap-2 overflow-x-auto pb-2">
                                                    {currentBundle.map((ad, idx) => {
                                                        const isAdVideo = ad.media_type === 'video';
                                                        return (
                                                            <button
                                                                key={idx}
                                                                onClick={() => {
                                                                    setViewedImage(ad);
                                                                    setImgError(false);
                                                                }}
                                                                className={`relative w-20 h-20 rounded-lg overflow-hidden border-2 transition-all flex-shrink-0 ${viewedImage.id === ad.id
                                                                    ? 'border-amber-600 ring-2 ring-amber-200'
                                                                    : 'border-gray-200 hover:border-amber-300'
                                                                    }`}
                                                            >
                                                                {isAdVideo ? (
                                                                    <video
                                                                        src={ad.video_url}
                                                                        poster={ad.thumbnail_url}
                                                                        className="w-full h-full object-cover"
                                                                        muted
                                                                    />
                                                                ) : (
                                                                    <img
                                                                        src={ad.image_url}
                                                                        alt={ad.size_name}
                                                                        className="w-full h-full object-cover"
                                                                    />
                                                                )}
                                                                {isAdVideo && (
                                                                    <div className="absolute top-1 right-1 bg-purple-600 text-white p-0.5 rounded">
                                                                        <Film size={8} />
                                                                    </div>
                                                                )}
                                                                <div className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[10px] py-0.5 text-center truncate px-1">
                                                                    {(ad.size_name || '').split(' ')[0]}
                                                                </div>
                                                            </button>
                                                        );
                                                    })}
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    {/* Details Panel */}
                                    <div className="space-y-6">
                                        {/* Ad Copy */}
                                        <div className="bg-amber-50 p-5 rounded-xl border border-amber-200">
                                            <h4 className="font-bold text-gray-900 mb-4 flex items-center gap-2">
                                                <FileText size={20} className="text-amber-600" />
                                                Ad Copy
                                            </h4>
                                            <div className="space-y-3">
                                                <div>
                                                    <label className="text-xs font-medium text-amber-700 uppercase">Headline</label>
                                                    <p className="font-bold text-gray-900 mt-1">{viewedImage.headline}</p>
                                                </div>
                                                <div>
                                                    <label className="text-xs font-medium text-amber-700 uppercase">Body Text</label>
                                                    <p className="text-gray-700 text-sm whitespace-pre-line mt-1">{viewedImage.body}</p>
                                                </div>
                                                <div>
                                                    <label className="text-xs font-medium text-amber-700 uppercase">Call to Action</label>
                                                    <div className="mt-1">
                                                        <span className="inline-block px-3 py-1 bg-amber-600 text-white rounded-full text-sm font-medium">
                                                            {viewedImage.cta}
                                                        </span>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>

                                        {/* Media Details */}
                                        <div className="bg-gray-50 p-5 rounded-xl border border-gray-200">
                                            <h4 className="font-bold text-gray-900 mb-4 flex items-center gap-2">
                                                {viewedImage.media_type === 'video' ? (
                                                    <Film size={20} className="text-purple-600" />
                                                ) : (
                                                    <Image size={20} className="text-gray-600" />
                                                )}
                                                {viewedImage.media_type === 'video' ? 'Video Details' : 'Image Details'}
                                            </h4>
                                            <div className="space-y-2 text-sm">
                                                <div className="flex justify-between">
                                                    <span className="text-gray-500">Type:</span>
                                                    <span className="font-medium text-gray-900 capitalize">{viewedImage.media_type || 'image'}</span>
                                                </div>
                                                <div className="flex justify-between">
                                                    <span className="text-gray-500">Size:</span>
                                                    <span className="font-medium text-gray-900">{viewedImage.size_name}</span>
                                                </div>
                                                <div className="flex justify-between">
                                                    <span className="text-gray-500">Dimensions:</span>
                                                    <span className="font-medium text-gray-900">{viewedImage.dimensions}</span>
                                                </div>
                                                <div className="flex justify-between">
                                                    <span className="text-gray-500">Created:</span>
                                                    <span className="font-medium text-gray-900">{new Date(viewedImage.created_at).toLocaleString()}</span>
                                                </div>
                                                {viewedImage.video_id && (
                                                    <div className="flex justify-between">
                                                        <span className="text-gray-500">FB Video ID:</span>
                                                        <span className="font-medium text-gray-900 text-xs">{viewedImage.video_id}</span>
                                                    </div>
                                                )}
                                            </div>
                                        </div>

                                        {/* Push to Meta Button */}
                                        {viewedImage.media_type !== 'video' && (
                                            <button
                                                onClick={() => openPushModal(viewedImage)}
                                                className="w-full py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-bold flex items-center justify-center gap-2 transition-colors mb-2"
                                            >
                                                <Rocket size={20} />
                                                Push to Meta
                                            </button>
                                        )}

                                        {/* Download Button */}
                                        <a
                                            href={viewedImage.media_type === 'video' ? viewedImage.video_url : viewedImage.image_url}
                                            download={`ad-${viewedImage.size_name || 'media'}-${Date.now()}.${viewedImage.media_type === 'video' ? 'mp4' : 'png'}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="w-full py-3 bg-amber-600 text-white rounded-lg hover:bg-amber-700 font-bold flex items-center justify-center gap-2 transition-colors"
                                        >
                                            <Download size={20} />
                                            Download {viewedImage.media_type === 'video' ? 'Video' : 'Image'}
                                        </a>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                )
            }

            {/* Delete Confirmation Modal */}
            {
                deleteConfirmation.show && (
                    <div
                        className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4"
                        onClick={cancelDelete}
                    >
                        <div
                            className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6"
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="flex items-center gap-3 mb-4">
                                <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center flex-shrink-0">
                                    <Trash2 className="text-red-600" size={24} />
                                </div>
                                <div>
                                    <h3 className="text-xl font-bold text-gray-900">Delete Ad Bundle?</h3>
                                    <p className="text-sm text-gray-500">This action cannot be undone</p>
                                </div>
                            </div>

                            <p className="text-gray-700 mb-6">
                                Are you sure you want to delete this bundle with <strong>{deleteConfirmation.bundleAds.length} ad{deleteConfirmation.bundleAds.length > 1 ? 's' : ''}</strong>?
                                All ad creatives will be permanently removed.
                            </p>

                            <div className="flex gap-3">
                                <button
                                    onClick={cancelDelete}
                                    className="flex-1 px-4 py-3 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors font-medium"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={confirmDelete}
                                    className="flex-1 px-4 py-3 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors font-medium flex items-center justify-center gap-2"
                                >
                                    <Trash2 size={18} />
                                    Yes, Delete
                                </button>
                            </div>
                        </div>
                    </div>
                )
            }

            {/* Single-ad Push to Meta Modal */}
            {pushModal.show && pushModal.ad && (
                <PushToMetaModal
                    imageUrl={pushModal.ad.image_url}
                    initialHeadline={pushModal.ad.headline || ''}
                    initialBody={pushModal.ad.body || ''}
                    initialCta={pushModal.ad.cta || 'LEARN_MORE'}
                    initialWebsiteUrl={localStorage.getItem('lastUsedWebsiteUrl') || ''}
                    initialCampaignId={localStorage.getItem('lastUsedCampaignId') || ''}
                    onClose={() => setPushModal({ show: false, ad: null })}
                />
            )}

            {/* Bulk Push to Meta Modal */}
            {bulkPushOpen && (
                <BatchPushModal
                    items={buildBulkPushItems()}
                    onClose={() => setBulkPushOpen(false)}
                    preselectedCampaignId={localStorage.getItem('lastUsedCampaignId') || ''}
                    preselectedWebsiteUrl={localStorage.getItem('lastUsedWebsiteUrl') || ''}
                />
            )}
        </div>
    );
}
