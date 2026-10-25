import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ImageGenerationStep } from './ImageAds';

const image = (n) => ({
    url: `https://cdn.example.com/ad-${n}.png`,
    size: 'Square (1:1)',
    dimensions: '1080x1080',
    adBundleId: `bundle-${n}`,
    copyHeadline: `Headline ${n}`,
    copyBody: `Body ${n}`,
    copyCta: 'Learn More',
});
const props = { wizardData: {}, selectedCopy: null, allCopies: [], onBack: vi.fn(), onRestart: vi.fn() };

describe('ImageGenerationStep hooks', () => {
    it('shows the empty state when there are no images', () => {
        render(<ImageGenerationStep {...props} generatedImages={[]} />);
        expect(screen.getByText(/No image data available/i)).toBeInTheDocument();
    });

    it('does not crash when the step stays mounted while images arrive after an empty render', () => {
        // Regression: the empty-state return used to sit above the viewedImage hooks, so going from [] to populated
        // on the SAME mounted component threw "Rendered more hooks than during the previous render".
        const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
        const { rerender, container } = render(<ImageGenerationStep {...props} generatedImages={[]} />);
        expect(() => rerender(<ImageGenerationStep {...props} generatedImages={[image(1), image(2)]} />)).not.toThrow();
        expect(screen.queryByText(/No image data available/i)).not.toBeInTheDocument();
        expect(container.querySelectorAll('img').length).toBeGreaterThanOrEqual(2);
        errors.mockRestore();
    });

    it('also survives going back to empty and populated again (null images included)', () => {
        const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
        const { rerender } = render(<ImageGenerationStep {...props} generatedImages={[image(1)]} />);
        expect(() => {
            rerender(<ImageGenerationStep {...props} generatedImages={null} />);
            rerender(<ImageGenerationStep {...props} generatedImages={[image(3)]} />);
        }).not.toThrow();
        errors.mockRestore();
    });
});
