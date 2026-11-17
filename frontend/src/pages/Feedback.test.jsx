import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Feedback from './Feedback';

const { authFetch } = vi.hoisted(() => ({ authFetch: vi.fn() }));
vi.mock('../lib/facebookApi', () => ({ authFetch }));
vi.mock('../context/ToastContext', () => ({ useToast: () => ({ showError: vi.fn() }) }));

describe('Feedback empty states', () => {
    beforeEach(() => {
        authFetch.mockResolvedValue({ ok: true, status: 200, json: async () => [] });
    });

    it('names the empty view for each filter', async () => {
        render(<MemoryRouter><Feedback /></MemoryRouter>);
        expect(await screen.findByText('No open feedback.')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Done' }));
        expect(screen.getByText('No done feedback.')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: "Won't fix" }));
        expect(screen.getByText("No won't-fix feedback.")).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'All' }));
        expect(screen.getByText('No feedback yet.')).toBeInTheDocument();
    });
});
