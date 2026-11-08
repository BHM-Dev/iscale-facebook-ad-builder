import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DailyCloseCard from './DailyCloseCard';

const { authFetch } = vi.hoisted(() => ({ authFetch: vi.fn() }));
vi.mock('../lib/facebookApi', () => ({ authFetch }));
vi.mock('../context/ToastContext', () => ({ useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }));

const close = {
  day: '2026-11-06', available: true, spend: 100, revenue: 140, profit: 40, roas: 1.4, leads: 4,
  partial: true, missing_accounts: ['act_2'], mtd: { profit: 200, days_elapsed: 6, pace: 900, last_month_profit: 700 },
  movers: { up: [], down: [] },
};

describe('DailyCloseCard strip', () => {
  beforeEach(() => authFetch.mockImplementation(url => Promise.resolve({ ok: true, json: async () => url.endsWith('/latest') ? { combined: close, accounts: [] } : {} })));

  it('renders the compact summary, partial warning, and unchanged full card in the drawer', async () => {
    render(<DailyCloseCard variant="strip" accountNames={{ act_2: 'RHO 4' }} />);
    expect(await screen.findByTestId('daily-close-strip')).toHaveTextContent('Fri, Nov 6 closed');
    expect(screen.getByText(/partial: missing RHO 4/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('Details ▸'));
    expect(screen.getByRole('dialog')).toContainElement(screen.getByTestId('daily-close-card'));
    expect(authFetch).toHaveBeenCalledWith(expect.stringContaining('/daily-close/event'), expect.objectContaining({ body: expect.stringContaining('close_details_opened') }));
  });
});
