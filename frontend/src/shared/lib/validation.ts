/**
 * Asset validation utilities
 * Runtime validation for critical frontend data-parsing logic
 */

export type Asset = {
    id: string;
    symbol: string;
    name?: string;
    quantity: number;
    price?: number;
};

export function isAsset(obj: unknown): obj is Asset {
    if (typeof obj !== 'object' || obj === null) return false;
    const o = obj as Record<string, unknown>;
    return (
        typeof o.id === 'string' &&
        typeof o.symbol === 'string' &&
        typeof o.quantity === 'number' &&
        (o.name === undefined || typeof o.name === 'string') &&
        (o.price === undefined || typeof o.price === 'number')
    );
}

export function validateAssetsArray(arr: unknown): Asset[] {
    if (!Array.isArray(arr)) throw new Error('Not an array');
    const out: Asset[] = [];
    for (const item of arr) {
        if (!isAsset(item)) throw new Error('Invalid asset object');
        out.push(item);
    }
    return out;
}
