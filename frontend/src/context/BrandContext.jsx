import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import { useAuth } from './AuthContext';
import { filterBrandsByVertical } from '../lib/verticals';

const BrandContext = createContext();
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

export const useBrands = () => {
    const context = useContext(BrandContext);
    if (!context) {
        throw new Error('useBrands must be used within a BrandProvider');
    }
    return context;
};

export const BrandProvider = ({ children }) => {
    const [brands, setBrands] = useState([]);
    const [customerProfiles, setCustomerProfiles] = useState([]);
    const [activeBrand, setActiveBrand] = useState(null);
    const [loading, setLoading] = useState(true);
    const [activeVerticalFilter, setActiveVerticalFilterState] = useState(() => (
        localStorage.getItem('adBuilder.activeVerticalFilter') || 'all'
    ));

    const { authFetch, isAuthenticated, loading: authLoading } = useAuth();

    const setActiveVerticalFilter = useCallback((verticalId) => {
        setActiveVerticalFilterState(verticalId);
        localStorage.setItem('adBuilder.activeVerticalFilter', verticalId);
    }, []);

    const filteredBrands = useMemo(
        () => filterBrandsByVertical(brands, activeVerticalFilter),
        [brands, activeVerticalFilter]
    );

    // Load data from API
    const loadData = useCallback(async () => {
        if (!isAuthenticated || authLoading) {
            setLoading(false);
            return;
        }

        try {
            const [brandsRes, profilesRes] = await Promise.all([
                authFetch(`${API_URL}/brands`),
                authFetch(`${API_URL}/profiles`)
            ]);

            if (brandsRes.ok) {
                const brandsData = await brandsRes.json();
                setBrands(Array.isArray(brandsData) ? brandsData : []);
            } else {
                setBrands([]);
            }

            if (profilesRes.ok) {
                const profilesData = await profilesRes.json();
                setCustomerProfiles(Array.isArray(profilesData) ? profilesData : []);
            } else {
                setCustomerProfiles([]);
            }
        } catch (error) {
            console.error('Error loading data:', error);
            setBrands([]);
            setCustomerProfiles([]);
        } finally {
            setLoading(false);
        }
    }, [authFetch, isAuthenticated, authLoading]);

    // Initial data load when authenticated
    useEffect(() => {
        if (authLoading) {
            // Still loading auth, wait
            return;
        }

        if (isAuthenticated) {
            loadData();
        } else {
            setBrands([]);
            setCustomerProfiles([]);
            setLoading(false);
        }
    }, [isAuthenticated, authLoading, loadData]);

    // Brand Management
    const addBrand = async (brand) => {
        const newBrand = { ...brand, id: crypto.randomUUID() };
        const res = await authFetch(`${API_URL}/brands`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(newBrand)
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `Failed to save brand (${res.status})`);
        }
        await loadData();
    };

    const updateBrand = async (id, updatedBrand) => {
        const res = await authFetch(`${API_URL}/brands/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updatedBrand)
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `Failed to update brand (${res.status})`);
        }
        await loadData();
    };

    const deleteBrand = async (id) => {
        const res = await authFetch(`${API_URL}/brands/${id}`, { method: 'DELETE' });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `Failed to delete brand (${res.status})`);
        }
        await loadData();
    };

    // Product Management (standalone - kept for compatibility)
    const addProduct = async (brandId, product) => {
        try {
            const brand = brands.find(b => b.id === brandId);
            if (brand) {
                const existing = (brand.products || []).find(
                    p => p.name.trim().toLowerCase() === product.name.trim().toLowerCase()
                );
                if (existing) {
                    throw new Error(`A product named "${existing.name}" already exists for this brand. Please use a different name.`);
                }
                const newProduct = { ...product, id: crypto.randomUUID() };
                const updatedBrand = {
                    ...brand,
                    products: [...(brand.products || []), newProduct]
                };
                await updateBrand(brandId, updatedBrand);
            }
        } catch (error) {
            console.error('Error adding product:', error);
            throw error;
        }
    };

    const updateProduct = async (brandId, productId, updatedProduct) => {
        try {
            const brand = brands.find(b => b.id === brandId);
            if (brand) {
                const updatedBrand = {
                    ...brand,
                    products: brand.products.map(p =>
                        p.id === productId ? { ...p, ...updatedProduct } : p
                    )
                };
                await updateBrand(brandId, updatedBrand);
            }
        } catch (error) {
            console.error('Error updating product:', error);
            throw error;
        }
    };

    const deleteProduct = async (brandId, productId) => {
        try {
            const brand = brands.find(b => b.id === brandId);
            if (brand) {
                const updatedBrand = {
                    ...brand,
                    products: brand.products.filter(p => p.id !== productId)
                };
                await updateBrand(brandId, updatedBrand);
            }
        } catch (error) {
            console.error('Error deleting product:', error);
            throw error;
        }
    };

    // Customer Profile Management
    const addProfile = async (profile) => {
        try {
            const newProfile = {
                ...profile,
                id: crypto.randomUUID()
            };

            // authFetch resolves with the Response rather than throwing on an auth
            // failure, so an unchecked call here would report success and then
            // silently drop the profile.
            const res = await authFetch(`${API_URL}/profiles`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(newProfile)
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `Failed to add profile (${res.status})`);
            }

            await loadData();
            return newProfile;
        } catch (error) {
            console.error('Error adding profile:', error);
            throw error;
        }
    };

    const updateProfile = async (id, updatedProfile) => {
        try {
            const res = await authFetch(`${API_URL}/profiles/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updatedProfile)
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `Failed to update profile (${res.status})`);
            }

            await loadData();
        } catch (error) {
            console.error('Error updating profile:', error);
            throw error;
        }
    };

    const deleteProfile = async (id) => {
        try {
            const res = await authFetch(`${API_URL}/profiles/${id}`, {
                method: 'DELETE'
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `Failed to delete profile (${res.status})`);
            }

            await loadData();
        } catch (error) {
            console.error('Error deleting profile:', error);
            throw error;
        }
    };

    // Profile-Brand linking (handled in brand update)
    const linkProfileToBrand = async (brandId, profileId) => {
        try {
            const brand = brands.find(b => b.id === brandId);
            if (brand && !brand.profileIds.includes(profileId)) {
                const updatedBrand = {
                    ...brand,
                    profileIds: [...brand.profileIds, profileId]
                };
                await updateBrand(brandId, updatedBrand);
            }
        } catch (error) {
            console.error('Error linking profile:', error);
            throw error;
        }
    };

    const unlinkProfileFromBrand = async (brandId, profileId) => {
        try {
            const brand = brands.find(b => b.id === brandId);
            if (brand) {
                const updatedBrand = {
                    ...brand,
                    profileIds: brand.profileIds.filter(id => id !== profileId)
                };
                await updateBrand(brandId, updatedBrand);
            }
        } catch (error) {
            console.error('Error unlinking profile:', error);
            throw error;
        }
    };

    return (
        <BrandContext.Provider value={{
            brands,
            filteredBrands,
            customerProfiles,
            activeBrand,
            setActiveBrand,
            activeVerticalFilter,
            setActiveVerticalFilter,
            loading,
            loadData,
            addBrand,
            updateBrand,
            deleteBrand,
            addProduct,
            updateProduct,
            deleteProduct,
            addProfile,
            updateProfile,
            deleteProfile,
            linkProfileToBrand,
            unlinkProfileFromBrand
        }}>
            {children}
        </BrandContext.Provider>
    );
};
