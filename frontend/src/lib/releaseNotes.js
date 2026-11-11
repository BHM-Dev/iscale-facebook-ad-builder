// "What's new" entries shown once per user at login (Steve, 2026-11-11). Newest first.
// Add an entry here in the same commit as any change the buyers will notice. Plain language,
// one or two sentences, say where to find it. `id` must only ever increase.
export const RELEASE_NOTES = [
    {
        id: 6,
        date: '2026-11-11',
        title: 'Profit/Loss by campaign',
        body: 'Profit/Loss now reads left to right as revenue − spend − costs = net profit. Below it, a "By campaign" table (All ad accounts) shows spend, revenue and gross profit for Commercial Insurance, Auto Insurance and Trusted Home Service, with monthly costs beside it. Rows with an arrow open to show each ad account.',
    },
    {
        id: 5,
        date: '2026-11-10',
        title: 'Winners in the Drive picker',
        body: 'Proven creatives now carry an amber "Winner #N" badge with estimated profit when you pick from Drive. Use the "Winners" button next to "Launch ready" to see just those, across every folder.',
    },
    {
        id: 4,
        date: '2026-11-10',
        title: 'Winning ads tab',
        body: 'Campaign Performance has a new "Winning ads" tab ranking individual creatives by estimated profit (10+ leads). Group by Concept to see which message works across niches. "Relaunch" opens Launch Ads with that Drive file selected; you pick the ad set.',
    },
    {
        id: 3,
        date: '2026-11-10',
        title: 'Budget-raise suggestions',
        body: 'The Proposals panel on Campaign Performance suggests +20% budget raises for ad sets profitable over the last 7 days. Approve applies it after a live check in Meta; Dismiss records why.',
    },
    {
        id: 2,
        date: '2026-11-08',
        title: 'Names fill themselves in',
        body: 'On Launch Ads, pick Wave and Niche (campaign) and type the Angle (ad set): campaign, ad set and ad names build in your format. Drive files already named like WW8-FUN-02-... become the ad name as-is. You can still type over any name.',
    },
    {
        id: 1,
        date: '2026-11-07',
        title: 'Campaign Performance, table first',
        body: 'Yesterday\'s close is one line at the top (Details for the full card). The line above the table shows how many ad sets are over and under Max CPL, with spend; click a count to filter. Compass and Intelligence are tabs.',
    },
];

export const LATEST_RELEASE_ID = RELEASE_NOTES.reduce((max, note) => Math.max(max, note.id), 0);

// First visit with nothing recorded: only show what shipped in the last two weeks, not the whole history.
export const FIRST_VISIT_DAYS = 14;

export function notesToShow(lastSeenId, today = new Date()) {
    if (lastSeenId != null) return RELEASE_NOTES.filter(note => note.id > lastSeenId);
    const cutoff = new Date(today.getTime() - FIRST_VISIT_DAYS * 24 * 60 * 60 * 1000);
    return RELEASE_NOTES.filter(note => new Date(`${note.date}T12:00:00Z`) >= cutoff);
}
