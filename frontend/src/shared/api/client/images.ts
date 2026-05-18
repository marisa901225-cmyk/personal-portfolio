import type { RequestFn } from './core';
import type {
    BackendAnimeImageUpscaleResponse,
    BackendComfyUIImageGenerationResponse,
    BackendServerGeneratedImageDataResponse,
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
        output_width?: number;
        output_height?: number;
        upscale_model?: string;
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

export const fetchServerGeneratedImageData = (
    request: RequestFn,
    path: string,
): Promise<BackendServerGeneratedImageDataResponse> =>
    request<BackendServerGeneratedImageDataResponse>(`/api/images/generated/data?path=${encodeURIComponent(path)}`, {
        method: 'GET',
    });
