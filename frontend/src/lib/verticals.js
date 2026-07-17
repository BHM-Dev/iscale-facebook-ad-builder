export const VERTICAL_FILTERS = [
  { id: 'all', label: 'All Verticals' },
  { id: 'commercial_insurance', label: 'Commercial Insurance' },
  { id: 'auto_insurance', label: 'Auto Insurance' },
  { id: 'home_services', label: 'Home Services' },
  { id: 'personal_loans', label: 'Personal Loans' },
  { id: 'debt_relief', label: 'Debt Relief' },
];

const VERTICAL_KEYWORDS = {
  commercial_insurance: [
    'business', 'commercial', 'liability', 'bop', 'contractor', 'trucking',
    'restaurant', 'salon', 'coverage', 'workers comp'
  ],
  auto_insurance: [
    'auto', 'car', 'driver', 'vehicle', 'insurance quote'
  ],
  home_services: [
    'home', 'gutter', 'painting', 'floor', 'flooring', 'roof', 'mold',
    'patio', 'fence', 'tree', 'contractor'
  ],
  personal_loans: [
    'loan', 'personal loan', 'cash', 'borrow', 'credit', 'finance'
  ],
  debt_relief: [
    'debt', 'relief', 'settlement', 'consolidation'
  ],
};

function collectBrandText(brand) {
  const products = Array.isArray(brand?.products) ? brand.products : [];
  const profiles = Array.isArray(brand?.profiles) ? brand.profiles : [];
  return [
    brand?.name,
    brand?.description,
    brand?.vertical,
    brand?.vertical_id,
    ...products.flatMap(product => [product?.name, product?.description, product?.vertical]),
    ...profiles.flatMap(profile => [profile?.name, profile?.description, profile?.vertical]),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

export function inferBrandVertical(brand) {
  const explicit = brand?.vertical_id || brand?.verticalId || brand?.vertical?.id || brand?.vertical;
  if (typeof explicit === 'string') {
    const normalized = explicit.toLowerCase().replace(/\s+/g, '_');
    if (VERTICAL_FILTERS.some(vertical => vertical.id === normalized)) return normalized;
  }

  const text = collectBrandText(brand);
  for (const [verticalId, keywords] of Object.entries(VERTICAL_KEYWORDS)) {
    if (keywords.some(keyword => text.includes(keyword))) return verticalId;
  }
  return null;
}

export function filterBrandsByVertical(brands, verticalId) {
  if (!verticalId || verticalId === 'all') return brands;
  return brands.filter(brand => inferBrandVertical(brand) === verticalId);
}
