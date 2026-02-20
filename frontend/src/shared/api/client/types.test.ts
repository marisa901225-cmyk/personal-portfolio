import { describe, it, expect } from 'vitest';
import { isAsset, validateAssetsArray } from '../../lib/validation';

describe('Asset validation utilities', () => {
    it('validates a correct asset object', () => {
        const a: unknown = {
            id: 1,
            name: 'ABC Corp',
            category: '국내주식',
            currency: 'KRW',
            amount: 10,
            current_price: 123.45,
            realized_profit: 0,
            created_at: '2024-01-21T00:00:00Z',
            updated_at: '2024-01-21T00:00:00Z'
        };
        expect(isAsset(a)).toBe(true);
    });

    it('rejects an invalid asset object', () => {
        const bad = { id: 1, name: 'ABC', amount: '10' };
        expect(isAsset(bad)).toBe(false);
    });

    it('validateAssetsArray accepts valid arrays', () => {
        const arr = [{
            id: 1,
            name: 'A',
            category: 'TEST',
            currency: 'KRW',
            amount: 1,
            current_price: 100,
            realized_profit: 0,
            created_at: '',
            updated_at: ''
        }];
        expect(() => validateAssetsArray(arr)).not.toThrow();
    });

    it('validateAssetsArray rejects invalid arrays', () => {
        const arr = [{ id: 1, name: 'A', amount: '1' }];
        expect(() => validateAssetsArray(arr as unknown)).toThrow();
    });
});
