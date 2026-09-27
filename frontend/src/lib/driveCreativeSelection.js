/**
 * Resolve the one destination URL shared by a launch.
 *
 * Drive copy and a launch destination are deliberately separate: an asset can
 * be missing its Drive copy but must never wipe a URL the buyer has already
 * selected for every ad in the batch.
 */
export function resolveGlobalWebsiteUrl({
    previousUrl = '',
    suggestedUrl = '',
    hasConflictingDestinations = false,
    wasManuallyEdited = false,
}) {
    if (hasConflictingDestinations) {
        return wasManuallyEdited ? previousUrl : '';
    }

    if (suggestedUrl && !wasManuallyEdited) {
        return suggestedUrl;
    }

    return previousUrl;
}
