export const parseApiError = (body, fallback = 'Request failed') => {
  const detail = body?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) return detail.message || detail.detail || fallback;
  if (Array.isArray(detail)) return detail.map(item => {
    const location = Array.isArray(item?.loc) ? ` (${item.loc.slice(1).join('.')})` : '';
    return `${item?.msg || item?.detail || JSON.stringify(item)}${location}`;
  }).join('; ') || fallback;
  return body?.message || fallback;
};
