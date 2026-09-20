/**
 * Count the ads produced by the standard creative launcher.
 * Drive creatives can carry their own copy; manually added creatives use the
 * shared headline/body arrays.
 */
export function countCreativeVariations(creativeData = {}) {
    const creatives = Array.isArray(creativeData.creatives) ? creativeData.creatives : [];
    const headlines = (creativeData.headlines || []).filter(value => value?.trim()).length;
    const bodies = (creativeData.bodies || []).filter(value => value?.trim()).length;
    // A creative "has per-creative copy" (raw truthiness, matching the
    // original inline implementation) only decides whether we're in
    // per-creative mode at all. Per-creative VALIDITY, below, always requires
    // `.trim()` — this must match Review's own missingCopy filter exactly
    // (AdCreativeStep.jsx): a non-drive row's own whitespace-only override
    // is not valid copy, so it falls back to the shared headlines/bodies
    // pool just like a row with no override at all, rather than counting as
    // one (invalid) override.
    const hasPerCreativeCopy = creatives.some(creative => (
        creative?.source === 'drive' || creative?.headline || creative?.body
    ));

    if (!hasPerCreativeCopy) {
        return { media: creatives.length, headlines, bodies, total: creatives.length * headlines * bodies, hasPerCreativeCopy: false };
    }

    let total = 0;
    let assignedHeadlineCount = 0;
    let assignedBodyCount = 0;
    creatives.forEach(creative => {
        const headlineCount = creative?.source === 'drive' || creative?.headline?.trim() ? 1 : headlines;
        const bodyCount = creative?.source === 'drive' || creative?.body?.trim() ? 1 : bodies;
        assignedHeadlineCount += headlineCount;
        assignedBodyCount += bodyCount;
        total += headlineCount * bodyCount;
    });

    return { media: creatives.length, headlines: assignedHeadlineCount, bodies: assignedBodyCount, total, hasPerCreativeCopy: true };
}
