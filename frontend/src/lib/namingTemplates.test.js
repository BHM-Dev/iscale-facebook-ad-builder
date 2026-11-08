import { describe, expect, it } from 'vitest';
import { conceptFromFilename, parseName, resolveNamingTemplate, seqFromFilename, conventionNameFromFilename } from './namingTemplates';

const date = new Date(2026, 10, 9, 12);
const campaignTemplate = '{brand_code} | {budget_type} | {objective_tag} | {wave} {niche} | {tracking} | {date:MM.DD.YYYY}';
const adsetTemplate = '{wave_code}-{niche_code} | {angle}';
const adTemplate = '{wave_code}-{niche_code}-{seq:02}-{concept}-{media}-{ratio}';

it('resolves the three real names exactly', () => {
    expect(resolveNamingTemplate(campaignTemplate, { brand_code: 'RHO v1', budget_type: 'ABO', objective_tag: '', wave: 'VEHICLE W2', niche: 'FUNERAL HOMES', tracking: 'CAPI', date }, { uppercase: true })).toBe('RHO v1 | ABO | VEHICLE W2 FUNERAL HOMES | CAPI | 11.09.2026');
    expect(resolveNamingTemplate(adsetTemplate, { wave_code: 'WW8', niche_code: 'FUN', angle: 'Fleet and crew' }, { uppercase: true })).toBe('WW8-FUN | FLEET AND CREW');
    expect(resolveNamingTemplate(adTemplate, { wave_code: 'WW8', niche_code: 'FUN', seq: 2, concept: 'HearseAndStaff', media: 'IMG', ratio: '1x1' })).toBe('WW8-FUN-02-HearseAndStaff-IMG-1x1');
});

it('drops separators belonging to empty tokens', () => {
    expect(resolveNamingTemplate('{brand_code} | {objective_tag} | {wave_code}-{niche_code}-{angle}', { brand_code: 'RHO v1', objective_tag: '', wave_code: 'WW8', niche_code: '', angle: '' })).not.toMatch(/\|\s*\||--|-$|\|$/);
});

it('preserves brand code case when uppercase is on', () => {
    expect(resolveNamingTemplate('{brand_code} | {niche}', { brand_code: 'RHO v1', niche: 'Funeral Homes' }, { uppercase: true })).toBe('RHO v1 | FUNERAL HOMES');
    expect(resolveNamingTemplate('{brand_code} | {unknown}', { brand_code: 'RHO v1' }, { uppercase: true })).toBe('RHO v1 | {unknown}');
});

it('extracts concepts from filenames', () => {
    expect(conceptFromFilename('WW8-FUN-02-HearseAndStaff-IMG-1x1.jpg')).toBe('HearseAndStaff');
    expect(conceptFromFilename('NewHearse_v2.png')).toBe('NewHearse');
});

describe('parseName', () => {
    it.each([
        ['RHO v1 | ABO | VEHICLE W2 FUNERAL HOMES | CAPI | 11.09.2026', campaignTemplate],
        ['WW8-FUN | FLEET AND CREW', adsetTemplate],
        ['WW8-FUN-02-HearseAndStaff-IMG-1x1', adTemplate],
    ])('round-trips %s', (name, template) => expect(parseName(name, template)).not.toBeNull());
    it('accepts generated copy-variant and duplicate suffixes', () => {
        expect(parseName('WW8-FUN-02-HearseAndStaff-IMG-1x1-H2B1-b', adTemplate)).not.toBeNull();
    });
    it('rejects freeform names', () => expect(parseName('Tow Owners Broad', adsetTemplate)).toBeNull());
});

describe('seqFromFilename', () => {
    it('keeps the buyer\'s own creative number', () => {
        expect(seqFromFilename('WW8-FUN-02-HearseAndStaff-IMG-1x1.jpg')).toBe(2);
        expect(seqFromFilename('VW-TREE-05-WhichTruck-IMG-1x1.jpg')).toBe(5);
        expect(seqFromFilename('HearseAndStaff.jpg')).toBeNull();
    });
});

describe('conventionNameFromFilename', () => {
    it('uses a convention-named Drive file verbatim, minus extension', () => {
        expect(conventionNameFromFilename('WW8-FUN-02-HearseAndStaff-IMG-4x5.jpg')).toBe('WW8-FUN-02-HearseAndStaff-IMG-4x5');
        expect(conventionNameFromFilename('folder/VW-TREE-05-WhichTruck-IMG-1x1_v2.png')).toBe('VW-TREE-05-WhichTruck-IMG-1x1_v2');
        expect(conventionNameFromFilename('HearseAndStaff.jpg')).toBeNull();
    });
});
