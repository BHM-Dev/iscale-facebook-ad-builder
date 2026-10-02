import { safeSessionStorageGet, safeSessionStorageRemove } from './safeLocalStorage';

export const LAUNCH_DRAFT_SESSION_KEY = 'campaign-launch-draft';
// Written by FacebookCampaigns (current step / furthest step / batch mode).
export const WIZARD_DRAFT_SESSION_KEY = 'campaign-wizard-state';
export const LAUNCH_RECEIPT_SESSION_KEY = 'campaign-launch-receipt';
export const AD_REMIX_DRAFT_SESSION_KEY = 'ad-remix-draft';

// A tab's saved work belongs to whoever was signed in when it was written. Called
// whenever tokens are cleared (logout, expired session) so the next user in the same
// tab never inherits an account/page/campaign, a receipt, or a remix in progress.
export const clearLaunchDraftSession = () => {
    safeSessionStorageRemove(LAUNCH_DRAFT_SESSION_KEY);
    safeSessionStorageRemove(WIZARD_DRAFT_SESSION_KEY);
    safeSessionStorageRemove(LAUNCH_RECEIPT_SESSION_KEY);
    safeSessionStorageRemove(AD_REMIX_DRAFT_SESSION_KEY);
};

// A draft is only worth restoring (or showing a banner for) if it holds real work.
export const draftHasContent = (draft) => Boolean(
    draft && (
        draft.campaignData?.name || draft.campaignData?.fbCampaignId || draft.campaignData?.id
        || draft.adsetData?.name || draft.adsetData?.fbAdsetId
        || draft.adsData?.length
        || draft.creativeData?.creatives?.length
    )
);

export const hasSavedLaunchDraft = () => {
    const stored = safeSessionStorageGet(LAUNCH_DRAFT_SESSION_KEY);
    if (!stored) return false;
    try {
        return draftHasContent(JSON.parse(stored));
    } catch {
        return false;
    }
};
