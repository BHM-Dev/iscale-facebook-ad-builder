/**
 * Count the ads produced by the standard creative launcher.
 * Drive creatives can carry their own copy; manually added creatives use the
 * shared headline/body arrays.
 */
export function countCreativeVariations(creativeData = {}) {
    const creatives = Array.isArray(creativeData.creatives) ? creativeData.creatives : [];
    const headlines = (creativeData.headlines || []).filter(value => value?.trim()).length;
    const bodies = (creativeData.bodies || []).filter(value => value?.trim()).length;
    // Match Review's manifest builder: a truthy per-creative value is an
    // override, even if it is whitespace. Review will flag that row as missing
    // copy; the counter must still describe one row, not silently expand it
    // across the shared combinations.
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
        const headlineCount = creative?.source === 'drive' || creative?.headline ? 1 : headlines;
        const bodyCount = creative?.source === 'drive' || creative?.body ? 1 : bodies;
        assignedHeadlineCount += headlineCount;
        assignedBodyCount += bodyCount;
        total += headlineCount * bodyCount;
    });

    return { media: creatives.length, headlines: assignedHeadlineCount, bodies: assignedBodyCount, total, hasPerCreativeCopy: true };
}
