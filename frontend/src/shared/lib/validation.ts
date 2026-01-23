import { BackendAsset } from '../api/client/types';

/**
 * Asset validation utilities
 * Runtime validation for critical frontend data-parsing logic
 */

export function isAsset(obj: unknown): obj is BackendAsset {
    if (typeof obj !== 'object' || obj === null) return false;
    const o = obj as Record<string, unknown>;

    // Validate against BackendAsset interface
    return (
        typeof o.id === 'number' &&
        typeof o.name === 'string' &&
        typeof o.category === 'string' &&
        (o.currency === 'KRW' || o.currency === 'USD') &&
        typeof o.amount === 'number' &&
        typeof o.current_price === 'number' &&
        // Optional fields check (if present, must match type)
        (o.ticker === undefined || o.ticker === null || typeof o.ticker === 'string') &&
        (o.purchase_price === undefined || o.purchase_price === null || typeof o.purchase_price === 'number') &&
        typeof o.realized_profit === 'number' &&
        (o.index_group === undefined || o.index_group === null || typeof o.index_group === 'string') &&
        typeof o.created_at === 'string' &&
        typeof o.updated_at === 'string'
    );
}

export function validateAssetsArray(arr: unknown): BackendAsset[] {
    if (!Array.isArray(arr)) throw new Error('Not an array');
    const out: BackendAsset[] = [];
    for (const item of arr) {
        if (!isAsset(item)) throw new Error('Invalid asset object');
        out.push(item);
    }
    return out;
}
