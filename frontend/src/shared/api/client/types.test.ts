import { describe, it, expect } from 'vitest';
import { isAsset, validateAssetsArray } from '../../lib/validation';

describe('Asset validation utilities', () => {
    it('validates a correct asset object', () => {
        const a = { id: '1', symbol: 'ABC', name: 'ABC Corp', quantity: 10, price: 123.45 };
        expect(isAsset(a)).toBe(true);
    });

    it('rejects an invalid asset object', () => {
        const bad = { id: 1, symbol: 'ABC', quantity: '10' };
        expect(isAsset(bad)).toBe(false);
    });

    it('validateAssetsArray accepts valid arrays', () => {
        const arr = [{ id: '1', symbol: 'A', quantity: 1 }];
        expect(() => validateAssetsArray(arr)).not.toThrow();
    });

    it('validateAssetsArray rejects invalid arrays', () => {
        const arr = [{ id: '1', symbol: 'A', quantity: '1' }];
        expect(() => validateAssetsArray(arr as unknown)).toThrow();
    });
});
