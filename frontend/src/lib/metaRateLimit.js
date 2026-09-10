// Meta rate-limit / throttle handling, shared by every loop that writes to the
// Marketing API.
//
// Context worth keeping, because the risk is routinely misunderstood: hitting a
// Meta rate limit does NOT get an ad account banned. It returns one of the codes
// below, the call fails, and access is restored on its own — usually within the
// hour. Accounts get disabled for policy, billing and verification problems, not
// for API call volume. The real costs of hammering the API are (a) a batch that
// dies halfway and leaves a half-built campaign on the account, and (b) edits
// that reset ad sets into learning phase and raise CPL.
//
// So the goal here is not to avoid a ban. It is to avoid partial writes, and to
// let a media buyer see how much of the account's budget is already spent before
// starting a large batch.

// Application request limit reached (17), ad account limit (613), and the
// 80000-80014 custom-throttle family Meta uses for per-object rate limits.
export const RATE_LIMIT_ERROR_CODES = new Set([
    17, 613,
    80000, 80001, 80002, 80003, 80004, 80005, 80006, 80007,
    80008, 80009, 80010, 80011, 80012, 80013, 80014,
]);

// Unconditional spacing between per-item Meta calls so a large batch doesn't
// fire back-to-back. Not real exponential backoff — just enough to keep a burst
// from tripping the app-level limit. 350ms was already in production use in the
// Bulk Match Import loop before this module existed.
export const INTER_REQUEST_DELAY_MS = 350;

// Above this percentage of any Meta usage metric we tell the user before they
// start a batch, rather than letting them discover it partway through.
export const USAGE_WARN_THRESHOLD = 80;

export function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * True when an Error carries a Meta throttle code.
 *
 * Relies on `metaErrorCode` being attached by buildFacebookApiError() in
 * lib/facebookApi.js — only the endpoints that raise the backend's
 * FacebookAPIError carry it, so a plain Error from any other failure correctly
 * returns false here instead of being mistaken for a throttle.
 */
export function isRateLimitError(error) {
    return RATE_LIMIT_ERROR_CODES.has(error?.metaErrorCode);
}

/**
 * Message for a batch that stopped early because Meta throttled the account.
 *
 * Deliberately does NOT tell the user to "re-run for the remainder". This
 * wizard cannot resume: handleSubmit creates the campaign and ad sets every
 * time (nothing marks them as existing once created), so pressing Launch again
 * would build a SECOND campaign and duplicate every ad that already succeeded.
 * Saying "re-run" would be advice that silently doubles the account's objects.
 *
 * Names the ads that were not attempted, because the review list shows all of
 * them and a count alone leaves the user cross-referencing against Ads Manager
 * by hand.
 */
export function rateLimitStopMessage({ created, total, attempted, regainSeconds, notAttemptedNames = [] }) {
    const remaining = Math.max(0, total - attempted);
    const wait = Number.isFinite(regainSeconds) && regainSeconds > 0
        ? `Meta estimates about ${Math.max(1, Math.ceil(regainSeconds / 60))} minute${Math.max(1, Math.ceil(regainSeconds / 60)) === 1 ? '' : 's'} until access is restored.`
        : 'Access usually returns within the hour.';

    // Cap the list so a 100-ad batch doesn't produce an unreadable wall.
    const MAX_NAMED = 8;
    const named = notAttemptedNames.slice(0, MAX_NAMED).join(', ');
    const overflow = notAttemptedNames.length > MAX_NAMED
        ? ` and ${notAttemptedNames.length - MAX_NAMED} more`
        : '';
    const notMade = named
        ? ` Not created: ${named}${overflow}.`
        : '';

    // With nothing created there is no duplication risk yet, so the advice is
    // simply "wait" rather than "don't press Launch" — a campaign and ad sets
    // may still exist from steps 1-2, but no ads to duplicate.
    const nextStep = created > 0
        ? ` Don't press Launch again — it would create a second campaign and duplicate the ${created} that already worked.`
          + ` Add the missing ads in Ads Manager, or start a fresh batch containing only those.`
        : ` The campaign and ad sets were created but no ads were. Wait for the limit to clear before trying again,`
          + ` and delete the empty campaign first so you don't end up with two.`;

    return `Meta rate-limited this account — batch stopped. ${created} of ${total} created`
        + `${remaining ? `, ${remaining} not attempted` : ''}.${notMade} ${wait}${nextStep}`;
}

/**
 * Highest usage percentage across the metrics Meta reports, or null when usage
 * is unknown (the header is absent on some responses). Callers must treat null
 * as "no information", never as zero.
 */
export function peakUsagePercent(usage) {
    if (!usage) return null;
    const values = [usage.call_count, usage.total_cputime, usage.total_time]
        .map((v) => Number(v))
        .filter((v) => Number.isFinite(v));
    return values.length ? Math.max(...values) : null;
}
