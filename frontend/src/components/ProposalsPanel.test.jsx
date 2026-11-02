import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ProposalsPanel from './ProposalsPanel';

const { authFetch, showError, showSuccess, showInfo } = vi.hoisted(() => ({ authFetch: vi.fn(), showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn() }));

vi.mock('../lib/facebookApi', () => ({ authFetch }));
vi.mock('../context/ToastContext', () => ({ useToast: () => ({ showError, showSuccess, showInfo }) }));
vi.mock('../context/CampaignContext', () => ({ useCampaign: () => ({ adAccounts: [{ id: 'act_1', name: 'RHO' }] }) }));

const proposal = (overrides = {}) => ({
    id: 'p1',
    fb_account_id: 'act_1',
    fb_adset_id: 'adset-1',
    adset_name: 'Churches - Batch 3',
    trigger_keys: ['no_revenue_spend'],
    trigger_labels: ['Spending, no revenue'],
    action: 'pause',
    action_params: { from_status: 'ACTIVE', to_status: 'PAUSED' },
    evidence: {
        why: 'Spent $64 today with no revenue in 3 days',
        days: [{ day: '2026-10-31', spend: 64, leads: 4, revenue: 0, profit: -64 }],
        totals_7d: { spend: 64, leads: 4, revenue: 0, profit: -64 },
        current: { status: 'ACTIVE', daily_budget_cents: 7500 },
    },
    status: 'open',
    created_at: new Date().toISOString(),
    ...overrides,
});

const openPayload = (rows = [proposal()]) => ({
    visible: true,
    shadow: false,
    proposals: rows,
    accounts: { act_1: { revenue_available: true } },
    dismiss_reasons: ['Revenue is lagging', 'Still testing', 'Handled it myself', 'Wrong call', 'Other'],
});

const response = (body, ok = true, status = 200) => ({ ok, status, json: async () => body });

beforeEach(() => {
    authFetch.mockReset();
    showError.mockReset();
    showSuccess.mockReset();
    showInfo.mockReset();
});

describe('ProposalsPanel', () => {
    it('is hidden when the API says proposals are not visible', async () => {
        authFetch.mockResolvedValue(response({ visible: false, proposals: [], accounts: {} }));
        render(<ProposalsPanel />);
        await waitFor(() => expect(screen.queryByTestId('proposals-panel')).not.toBeInTheDocument());
    });

    it('renders proposal cards and evidence', async () => {
        authFetch.mockResolvedValue(response(openPayload()));
        render(<ProposalsPanel />);
        expect(await screen.findByText('Churches - Batch 3')).toBeInTheDocument();
        expect(screen.getByText('Spent $64 today with no revenue in 3 days')).toBeInTheDocument();
        expect(screen.getByText('Approve — pause ad set')).toBeInTheDocument();
    });

    it('shows the stale explanation after approval', async () => {
        authFetch.mockImplementation((url, options = {}) => {
            if (url.endsWith('/events')) return Promise.resolve(response({}, true, 204));
            if (options.method === 'POST') return Promise.resolve(response({ ...proposal({ status: 'stale', status_reason: 'This ad set changed since the proposal (now PAUSED).' }) }));
            return Promise.resolve(response(openPayload()));
        });
        render(<ProposalsPanel />);
        fireEvent.click(await screen.findByText('Approve — pause ad set'));
        expect(await screen.findByText('This ad set changed since the proposal (now PAUSED).')).toBeInTheDocument();
    });

    it('shows Retry when Meta rejects an approval', async () => {
        authFetch.mockImplementation((url, options = {}) => {
            if (url.endsWith('/events')) return Promise.resolve(response({}, true, 204));
            if (options.method === 'POST') return Promise.resolve(response({ ...proposal({ status: 'failed', execution_result: { error: 'Budget was rejected.' } }) }));
            return Promise.resolve(response(openPayload()));
        });
        render(<ProposalsPanel />);
        fireEvent.click(await screen.findByText('Approve — pause ad set'));
        expect(await screen.findByText('Retry')).toBeInTheDocument();
        expect(screen.getByText(/Budget was rejected/)).toBeInTheDocument();
    });

    it('requires a reason and a note for Other before dismissing', async () => {
        authFetch.mockResolvedValue(response(openPayload()));
        render(<ProposalsPanel />);
        fireEvent.click(await screen.findByText('Dismiss ▾'));
        const dismissButton = screen.getByText('Dismiss proposal');
        expect(dismissButton).toBeDisabled();
        fireEvent.click(screen.getByText('Other'));
        expect(dismissButton).toBeDisabled();
        fireEvent.change(screen.getByPlaceholderText('What should the rule have known?'), { target: { value: 'Keep testing.' } });
        expect(dismissButton).not.toBeDisabled();
    });

    it('says so when another person already decided the proposal (409)', async () => {
        authFetch.mockImplementation((url, options = {}) => {
            if (url.endsWith('/events')) return Promise.resolve(response({}, true, 204));
            if (options.method === 'POST') return Promise.resolve(response({ detail: 'Already decided' }, false, 409));
            return Promise.resolve(response(openPayload()));
        });
        render(<ProposalsPanel />);
        fireEvent.click(await screen.findByText('Approve — pause ad set'));
        await waitFor(() => expect(showInfo).toHaveBeenCalledWith('Already handled — see History.'));
    });

    it('survives a non-JSON gateway error and reloads the list', async () => {
        let gets = 0;
        authFetch.mockImplementation((url, options = {}) => {
            if (url.endsWith('/events')) return Promise.resolve(response({}, true, 204));
            if (options.method === 'POST') return Promise.resolve({ ok: false, status: 504, json: async () => { throw new SyntaxError("Unexpected token '<'"); } });
            gets += 1;
            return Promise.resolve(response(openPayload()));
        });
        render(<ProposalsPanel />);
        fireEvent.click(await screen.findByText('Approve — pause ad set'));
        await waitFor(() => expect(showError).toHaveBeenCalledWith('Approval failed'));
        await waitFor(() => expect(gets).toBe(2));
    });

    it('confirms a successful pause', async () => {
        authFetch.mockImplementation((url, options = {}) => {
            if (url.endsWith('/events')) return Promise.resolve(response({}, true, 204));
            if (options.method === 'POST') return Promise.resolve(response(proposal({ status: 'executed' })));
            return Promise.resolve(response(openPayload()));
        });
        render(<ProposalsPanel />);
        fireEvent.click(await screen.findByText('Approve — pause ad set'));
        await waitFor(() => expect(showSuccess).toHaveBeenCalledWith('Paused Churches - Batch 3'));
    });
});
