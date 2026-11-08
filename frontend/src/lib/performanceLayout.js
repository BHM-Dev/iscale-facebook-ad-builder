export function maxCplBucket(insight, maxCplEntry, maxCplAvailable = true) {
  const spend = Number(insight?.spend || 0);
  if (spend <= 0) return null;
  if (!maxCplAvailable || maxCplEntry?.max_cpl == null) return 'no_max';
  const maxCpl = Number(maxCplEntry.max_cpl);
  const leads = Number(insight?.leads || 0);
  if (leads <= 0) return spend >= maxCpl ? 'over_max' : 'under_max';
  const cpl = insight?.cpl == null ? spend / leads : Number(insight.cpl);
  return cpl > maxCpl ? 'over_max' : 'under_max';
}

export function deepLinkState(params) {
  const search = params instanceof URLSearchParams ? params : new URLSearchParams(params);
  const view = search.get('view');
  return {
    tab: search.get('tab') || 'adsets',
    statusFilter: view === 'attention' ? 'flagged'
      : view === 'top-performers' ? 'top_performers'
      : view === 'refresh-soon' ? 'refresh_soon'
      : 'all',
    nicheFilter: search.get('niche') || '',
    campaignFilter: search.get('campaign') || '',
    targetAdsetId: search.get('adsetId') || '',
    proposalsOpen: search.get('proposals') === 'open',
  };
}
