import type { RequestFn } from './core';
import type {
    BackendAnimeImageUpscaleResponse,
    BackendComfyUIImageGenerationResponse,
    BackendServerGeneratedImagesResponse,
} from './types';

export const generateComfyUIImage = (
    request: RequestFn,
    payload: {
        request: string;
        width?: number;
        height?: number;
        seed?: number;
        steps?: number;
    },
): Promise<BackendComfyUIImageGenerationResponse> =>
    request<BackendComfyUIImageGenerationResponse>('/api/images/generate', {
        method: 'POST',
        body: JSON.stringify(payload),
    });

export const upscaleAnimeImage = (
    request: RequestFn,
    payload: {
        image_data_url: string;
        model?: string;
        scale?: number;
        target_width?: number;
        target_height?: number;
        output_format?: 'png' | 'jpg';
    },
): Promise<BackendAnimeImageUpscaleResponse> =>
    request<BackendAnimeImageUpscaleResponse>('/api/images/upscale', {
        method: 'POST',
        body: JSON.stringify(payload),
    });

export const fetchServerGeneratedImages = (
    request: RequestFn,
    limit = 24,
): Promise<BackendServerGeneratedImagesResponse> =>
    request<BackendServerGeneratedImagesResponse>(`/api/images/generated?limit=${encodeURIComponent(String(limit))}`, {
        method: 'GET',
    });
