import type { RequestFn } from './core';
import type {
    BackendAnimeImageUpscaleResponse,
    BackendComfyUIImageGenerationResponse,
    BackendComfyUIImagePromptPlanResponse,
    BackendComfyUIImageToImageResponse,
    BackendServerGeneratedImageDataResponse,
    BackendServerGeneratedImagesResponse,
} from './types';

export const generateComfyUIImage = (
    request: RequestFn,
    payload: {
        request: string;
        model_type?: 'anime' | 'realistic';
        prompt_override?: string;
        negative_prompt_override?: string;
        width?: number;
        height?: number;
        seed?: number;
        steps?: number;
        cfg?: number;
        output_width?: number;
        output_height?: number;
        upscale_model?: string;
    },
): Promise<BackendComfyUIImageGenerationResponse> =>
    request<BackendComfyUIImageGenerationResponse>('/api/images/generate', {
        method: 'POST',
        body: JSON.stringify(payload),
    });

export const planComfyUIImagePrompt = (
    request: RequestFn,
    payload: {
        request: string;
        model_type?: 'anime' | 'realistic';
        width?: number;
        height?: number;
        seed?: number;
        steps?: number;
        cfg?: number;
    },
): Promise<BackendComfyUIImagePromptPlanResponse> =>
    request<BackendComfyUIImagePromptPlanResponse>('/api/images/plan-prompt', {
        method: 'POST',
        body: JSON.stringify(payload),
    });

export const imageToImageComfyUI = (
    request: RequestFn,
    payload: {
        request: string;
        image_data_url: string;
        model_type?: 'anime' | 'realistic';
        width?: number;
        height?: number;
        seed?: number;
        steps?: number;
        cfg?: number;
        denoise?: number;
    },
): Promise<BackendComfyUIImageToImageResponse> =>
    request<BackendComfyUIImageToImageResponse>('/api/images/image-to-image', {
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
