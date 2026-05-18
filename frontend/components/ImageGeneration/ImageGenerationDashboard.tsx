import React, { startTransition, useEffect, useMemo, useState } from 'react';
import { ImagePlus, Loader2, Maximize2, MessageCircle, RefreshCcw, Send, Sparkles, Upload } from 'lucide-react';
import {
  ApiClient,
  type BackendAnimeImageUpscaleResponse,
  type BackendComfyUIImageGenerationResponse,
  type BackendServerGeneratedImage,
} from '@/shared/api/client';
import { alertError } from '@/shared/errors';

interface ImageGenerationDashboardProps {
  serverUrl: string;
  apiToken?: string;
  cookieAuth?: boolean;
}

type CanvasPreset = 'square' | 'classicPortrait' | 'classicLandscape' | 'storyPortrait' | 'cinemaLandscape' | 'phonePortrait' | 'phoneLandscape' | 'wide' | 'custom';
type GenerationOutputPreset = 'native' | 'uhd4k';
type UpscaleResolutionPreset = 'native4x' | 'fullhd' | 'square2k' | 'uhd4k' | 'custom';
type StudioMode = 'generate' | 'upscale';
type RevisionMessage = {
  role: 'user' | 'assistant';
  text: string;
};

const CANVAS_PRESETS: Record<CanvasPreset, { label: string; width: number; height: number }> = {
  square: { label: '1:1 정사각', width: 1024, height: 1024 },
  classicPortrait: { label: '3:4 세로', width: 896, height: 1152 },
  classicLandscape: { label: '4:3 가로', width: 1152, height: 896 },
  storyPortrait: { label: '2:3 세로', width: 832, height: 1216 },
  cinemaLandscape: { label: '3:2 가로', width: 1216, height: 832 },
  phonePortrait: { label: '9:16 세로', width: 768, height: 1344 },
  phoneLandscape: { label: '16:9 가로', width: 1344, height: 768 },
  wide: { label: '21:9 와이드', width: 1536, height: 640 },
  custom: { label: '직접 입력', width: 1024, height: 1024 },
};

const UPSCALE_RESOLUTION_PRESETS: Record<UpscaleResolutionPreset, { label: string; width?: number; height?: number }> = {
  native4x: { label: '모델 x4 원본' },
  fullhd: { label: 'FHD', width: 1920, height: 1080 },
  square2k: { label: '2K 정사각', width: 2048, height: 2048 },
  uhd4k: { label: '4K UHD', width: 3840, height: 2160 },
  custom: { label: '직접 입력', width: 2048, height: 2048 },
};

const GENERATION_OUTPUT_PRESETS: Record<GenerationOutputPreset, { label: string; description: string; output_width?: number; output_height?: number }> = {
  native: { label: '기본 저장', description: '생성 해상도 그대로 저장' },
  uhd4k: { label: '4K 저장', description: '범용 RealESRGAN 노드로 3840 × 2160 출력', output_width: 3840, output_height: 2160 },
};

const GENERAL_UPSCALE_MODEL = 'RealESRGAN_x4plus.pth';

const clampResolution = (value: number) => Math.min(Math.max(value || 1024, 512), 1536);
const clampUpscaleResolution = (value: number) => Math.min(Math.max(value || 2048, 256), 4096);

const formatServerImageTime = (value: string) =>
  new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));

export const ImageGenerationDashboard: React.FC<ImageGenerationDashboardProps> = ({
  serverUrl,
  apiToken,
  cookieAuth,
}) => {
  const [requestText, setRequestText] = useState('');
  const [mode, setMode] = useState<StudioMode>('generate');
  const [preset, setPreset] = useState<CanvasPreset>('square');
  const [customWidth, setCustomWidth] = useState(1024);
  const [customHeight, setCustomHeight] = useState(1024);
  const [generationOutput, setGenerationOutput] = useState<GenerationOutputPreset>('native');
  const [upscaleResolution, setUpscaleResolution] = useState<UpscaleResolutionPreset>('native4x');
  const [upscaleCustomWidth, setUpscaleCustomWidth] = useState(2048);
  const [upscaleCustomHeight, setUpscaleCustomHeight] = useState(2048);
  const [steps, setSteps] = useState(20);
  const [seed, setSeed] = useState('');
  const [upscaleSourceDataUrl, setUpscaleSourceDataUrl] = useState('');
  const [upscaleSourceName, setUpscaleSourceName] = useState('');
  const [selectedServerImagePath, setSelectedServerImagePath] = useState('');
  const [serverImages, setServerImages] = useState<BackendServerGeneratedImage[]>([]);
  const [isLoadingServerImages, setIsLoadingServerImages] = useState(false);
  const [upscaleModel, setUpscaleModel] = useState('realesrgan-x4plus');
  const [revisionText, setRevisionText] = useState('');
  const [revisionMessages, setRevisionMessages] = useState<RevisionMessage[]>([]);
  const [result, setResult] = useState<BackendComfyUIImageGenerationResponse | null>(null);
  const [upscaleResult, setUpscaleResult] = useState<BackendAnimeImageUpscaleResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  const isReady = Boolean(serverUrl?.trim() && (apiToken || cookieAuth));
  const dimensions = useMemo(() => (
    preset === 'custom'
      ? { label: '직접 입력', width: clampResolution(customWidth), height: clampResolution(customHeight) }
      : CANVAS_PRESETS[preset]
  ), [customHeight, customWidth, preset]);
  const upscaleTarget = useMemo(() => {
    if (upscaleResolution === 'native4x') {
      return { label: '모델 x4 원본' };
    }
    if (upscaleResolution === 'custom') {
      return {
        label: '직접 입력',
        width: clampUpscaleResolution(upscaleCustomWidth),
        height: clampUpscaleResolution(upscaleCustomHeight),
      };
    }
    return UPSCALE_RESOLUTION_PRESETS[upscaleResolution];
  }, [upscaleCustomHeight, upscaleCustomWidth, upscaleResolution]);
  const generationOutputTarget = GENERATION_OUTPUT_PRESETS[generationOutput];
  const activeImageDataUrl = upscaleResult?.image_data_url ?? result?.image_data_url ?? upscaleSourceDataUrl;
  const activeImageLabel = upscaleResult?.filename ?? result?.request ?? upscaleSourceName;
  const canReviseImage = Boolean(result || requestText.trim());

  const loadServerImages = async () => {
    if (!isReady) return;
    setIsLoadingServerImages(true);
    try {
      const client = new ApiClient(serverUrl, apiToken);
      const response = await client.fetchServerGeneratedImages(24);
      startTransition(() => setServerImages(response.images));
    } catch (err) {
      alertError('Server generated image list failed', err, {
        default: '서버 생성 이미지 목록을 불러오지 못했습니다.',
        unauthorized: '인증이 만료되었거나 올바르지 않습니다.',
        network: '백엔드 서버에 연결할 수 없습니다.',
      });
      if (err instanceof Error) {
        setError(err.message);
      }
    } finally {
      setIsLoadingServerImages(false);
    }
  };

  useEffect(() => {
    if (mode === 'upscale' && isReady) {
      void loadServerImages();
    }
  }, [mode, isReady]);

  const handleUpscaleSourceChange = (file?: File) => {
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      setError('이미지 파일만 업스케일할 수 있습니다.');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const value = typeof reader.result === 'string' ? reader.result : '';
      startTransition(() => {
        setUpscaleSourceDataUrl(value);
        setUpscaleSourceName(file.name);
        setSelectedServerImagePath('');
        setUpscaleResult(null);
        setError(null);
        setMode('upscale');
      });
    };
    reader.onerror = () => setError('이미지 파일을 읽지 못했습니다.');
    reader.readAsDataURL(file);
  };

  const handleSelectServerImage = async (image: BackendServerGeneratedImage) => {
    let imageDataUrl = image.image_data_url;
    if (!imageDataUrl) {
      try {
        const client = new ApiClient(serverUrl, apiToken);
        const response = await client.fetchServerGeneratedImageData(image.relative_path);
        imageDataUrl = response.image_data_url;
      } catch (err) {
        alertError('Server generated image load failed', err, {
          default: '선택한 서버 이미지를 불러오지 못했습니다.',
          unauthorized: '인증이 만료되었거나 올바르지 않습니다.',
          network: '백엔드 서버에 연결할 수 없습니다.',
        });
        if (err instanceof Error) {
          setError(err.message);
        }
        return;
      }
    }

    startTransition(() => {
      setUpscaleSourceDataUrl(imageDataUrl);
      setUpscaleSourceName(image.filename);
      setSelectedServerImagePath(image.relative_path);
      setUpscaleResult(null);
      setError(null);
      setMode('upscale');
    });
  };

  const handleGenerate = async () => {
    if (!serverUrl?.trim()) {
      setError('먼저 서버 URL을 설정해주세요.');
      return;
    }
    if (!apiToken && !cookieAuth) {
      setError('네이버 로그인 또는 API 비밀번호가 필요합니다.');
      return;
    }
    if (!requestText.trim()) {
      setError('그리고 싶은 장면을 먼저 적어주세요.');
      return;
    }

    setIsPending(true);
    setError(null);

    try {
      const client = new ApiClient(serverUrl, apiToken);
      const response = await client.generateComfyUIImage({
        request: requestText.trim(),
        width: dimensions.width,
        height: dimensions.height,
        steps,
        seed: seed.trim() ? Number(seed.trim()) : undefined,
        output_width: generationOutputTarget.output_width,
        output_height: generationOutputTarget.output_height,
        upscale_model: generationOutput === 'uhd4k' ? GENERAL_UPSCALE_MODEL : undefined,
      });
      startTransition(() => {
        setResult(response);
        setUpscaleResult(null);
      });
    } catch (err) {
      setResult(null);
      alertError('ComfyUI image generation failed', err, {
        default: '이미지 생성에 실패했습니다. 잠시 후 다시 시도해주세요.',
        unauthorized: '인증이 만료되었거나 올바르지 않습니다. 다시 로그인하거나 API 비밀번호를 확인해주세요.',
        network: '백엔드 또는 ComfyUI 서버에 연결할 수 없습니다.',
      });
      if (err instanceof Error) {
        setError(err.message);
      }
    } finally {
      setIsPending(false);
    }
  };

  const handleRevisionGenerate = async () => {
    const revision = revisionText.trim();
    const basePrompt = result?.tool_prompt || result?.request || requestText.trim();
    if (!serverUrl?.trim()) {
      setError('먼저 서버 URL을 설정해주세요.');
      return;
    }
    if (!apiToken && !cookieAuth) {
      setError('네이버 로그인 또는 API 비밀번호가 필요합니다.');
      return;
    }
    if (!basePrompt) {
      setError('먼저 기준이 될 이미지를 생성하거나 요청 문장을 입력해주세요.');
      return;
    }
    if (!revision) {
      setError('바꾸고 싶은 내용을 채팅창에 적어주세요.');
      return;
    }

    const nextRequest = [
      '이전 이미지의 전체 구도, 카메라 거리, 화면 비율, 배경 분위기는 최대한 유지한다.',
      `기준 프롬프트: ${basePrompt}`,
      `수정 요청: ${revision}`,
      '수정 요청에 언급된 요소만 바꾸고 나머지는 가능한 한 유지한다.',
    ].join('\n');

    setIsPending(true);
    setError(null);
    setRevisionMessages((messages) => [...messages, { role: 'user', text: revision }]);

    try {
      const client = new ApiClient(serverUrl, apiToken);
      const response = await client.generateComfyUIImage({
        request: nextRequest,
        width: result?.generated_width ?? dimensions.width,
        height: result?.generated_height ?? dimensions.height,
        steps,
        output_width: result?.upscale_model ? result.width : generationOutputTarget.output_width,
        output_height: result?.upscale_model ? result.height : generationOutputTarget.output_height,
        upscale_model: result?.upscale_model ?? (generationOutput === 'uhd4k' ? GENERAL_UPSCALE_MODEL : undefined),
      });
      startTransition(() => {
        setResult(response);
        setUpscaleResult(null);
        setRevisionText('');
        setRevisionMessages((messages) => [
          ...messages,
          { role: 'assistant', text: '수정 요청을 반영해서 다시 생성했습니다.' },
        ]);
      });
    } catch (err) {
      alertError('Image revision generation failed', err, {
        default: '수정 이미지 생성에 실패했습니다. 잠시 후 다시 시도해주세요.',
        unauthorized: '인증이 만료되었거나 올바르지 않습니다. 다시 로그인하거나 API 비밀번호를 확인해주세요.',
        network: '백엔드 또는 ComfyUI 서버에 연결할 수 없습니다.',
      });
      if (err instanceof Error) {
        setError(err.message);
      }
    } finally {
      setIsPending(false);
    }
  };

  const handleUpscale = async () => {
    if (!serverUrl?.trim()) {
      setError('먼저 서버 URL을 설정해주세요.');
      return;
    }
    if (!apiToken && !cookieAuth) {
      setError('네이버 로그인 또는 API 비밀번호가 필요합니다.');
      return;
    }

    const imageDataUrl = upscaleSourceDataUrl || result?.image_data_url;
    if (!imageDataUrl) {
      setError('업스케일할 이미지를 먼저 선택해주세요.');
      return;
    }

    setIsPending(true);
    setError(null);

    try {
      const client = new ApiClient(serverUrl, apiToken);
      const response = await client.upscaleAnimeImage({
        image_data_url: imageDataUrl,
        model: upscaleModel,
        scale: 4,
        target_width: upscaleTarget.width,
        target_height: upscaleTarget.height,
        output_format: 'png',
      });
      startTransition(() => {
        setUpscaleResult(response);
      });
    } catch (err) {
      setUpscaleResult(null);
      alertError('Anime image upscale failed', err, {
        default: '업스케일에 실패했습니다. 잠시 후 다시 시도해주세요.',
        unauthorized: '인증이 만료되었거나 올바르지 않습니다. 다시 로그인하거나 API 비밀번호를 확인해주세요.',
        network: '백엔드 또는 업스케일 서버에 연결할 수 없습니다.',
      });
      if (err instanceof Error) {
        setError(err.message);
      }
    } finally {
      setIsPending(false);
    }
  };

  return (
    <section className="space-y-6">
      <div className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
        <div className="relative bg-[radial-gradient(circle_at_top_left,_rgba(99,102,241,0.20),_transparent_36%),linear-gradient(135deg,#0f172a_0%,#1e1b4b_52%,#312e81_100%)] px-6 py-7 text-white">
          <div className="absolute right-6 top-6 rounded-full border border-white/15 bg-white/10 px-3 py-1 text-[11px] font-semibold tracking-[0.18em] text-indigo-100">
            AI + COMFYUI
          </div>
          <div className="max-w-2xl">
            <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-indigo-50">
              <Sparkles size={14} />
              자연어 요청을 AI가 ComfyUI 프롬프트로 자동 변환
            </div>
            <h2 className="text-2xl font-bold tracking-tight">이미지 생성 스튜디오</h2>
            <p className="mt-2 text-sm leading-6 text-indigo-100/90">
              장면만 적으면 AI가 tool call로 ComfyUI를 실행하고, 결과 이미지를 바로 가져옵니다.
            </p>
          </div>
        </div>

        <div className="grid gap-6 px-6 py-6 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="space-y-5">
            <div className="inline-grid grid-cols-2 rounded-2xl border border-slate-200 bg-slate-100 p-1 text-sm font-semibold text-slate-600">
              <button
                type="button"
                onClick={() => setMode('generate')}
                className={`rounded-xl px-4 py-2 transition ${mode === 'generate' ? 'bg-white text-indigo-700 shadow-sm' : 'hover:text-slate-900'}`}
              >
                생성
              </button>
              <button
                type="button"
                onClick={() => setMode('upscale')}
                className={`rounded-xl px-4 py-2 transition ${mode === 'upscale' ? 'bg-white text-indigo-700 shadow-sm' : 'hover:text-slate-900'}`}
              >
                업스케일
              </button>
            </div>

            {mode === 'generate' ? (
              <>
            <div>
              <label className="mb-2 block text-sm font-semibold text-slate-800" htmlFor="image-request">
                요청 문장
              </label>
              <textarea
                id="image-request"
                value={requestText}
                onChange={(event) => setRequestText(event.target.value)}
                rows={5}
                placeholder="그리고 싶은 장면을 입력하세요."
                className="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-700 outline-none transition focus:border-indigo-400 focus:bg-white"
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-[1.4fr_0.8fr]">
              <div>
                <div className="mb-2 text-sm font-semibold text-slate-800">비율 / 해상도</div>
                <div className="grid grid-cols-3 gap-2">
                  {(Object.entries(CANVAS_PRESETS) as Array<[CanvasPreset, { label: string; width: number; height: number }]>).map(([key, value]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setPreset(key)}
                      className={`rounded-2xl border px-3 py-3 text-sm font-medium transition ${
                        preset === key
                          ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                          : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                      }`}
                    >
                      <div>{value.label}</div>
                      <div className="mt-1 text-[11px] text-slate-400">
                        {key === 'custom' ? `${dimensions.width} × ${dimensions.height}` : `${value.width} × ${value.height}`}
                      </div>
                    </button>
                  ))}
                </div>
                {preset === 'custom' && (
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <label className="text-xs font-semibold text-slate-600" htmlFor="custom-width">
                      가로
                      <input
                        id="custom-width"
                        type="number"
                        min={512}
                        max={1536}
                        step={64}
                        value={customWidth}
                        onChange={(event) => setCustomWidth(clampResolution(Number(event.target.value)))}
                        className="mt-1 w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700"
                      />
                    </label>
                    <label className="text-xs font-semibold text-slate-600" htmlFor="custom-height">
                      세로
                      <input
                        id="custom-height"
                        type="number"
                        min={512}
                        max={1536}
                        step={64}
                        value={customHeight}
                        onChange={(event) => setCustomHeight(clampResolution(Number(event.target.value)))}
                        className="mt-1 w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700"
                      />
                    </label>
                  </div>
                )}
              </div>

              <div className="space-y-4">
                <div>
                  <div className="mb-2 text-sm font-semibold text-slate-800">출력</div>
                  <div className="grid gap-2">
                    {(Object.entries(GENERATION_OUTPUT_PRESETS) as Array<[GenerationOutputPreset, { label: string; description: string }]>).map(([key, value]) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setGenerationOutput(key)}
                        className={`rounded-2xl border px-3 py-3 text-left text-sm font-medium transition ${
                          generationOutput === key
                            ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                            : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                        }`}
                      >
                        <div>{value.label}</div>
                        <div className="mt-1 text-[11px] text-slate-400">{value.description}</div>
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="mb-2 block text-sm font-semibold text-slate-800" htmlFor="image-steps">
                    스텝
                  </label>
                  <input
                    id="image-steps"
                    type="number"
                    min={8}
                    max={60}
                    value={steps}
                    onChange={(event) => setSteps(Math.min(Math.max(Number(event.target.value) || 20, 8), 60))}
                    className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-700"
                  />
                </div>
                <div>
                  <label className="mb-2 block text-sm font-semibold text-slate-800" htmlFor="image-seed">
                    시드
                  </label>
                  <input
                    id="image-seed"
                    type="text"
                    inputMode="numeric"
                    value={seed}
                    onChange={(event) => setSeed(event.target.value.replace(/[^\d]/g, ''))}
                    placeholder="비우면 랜덤"
                    className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-700"
                  />
                </div>
              </div>
            </div>

            {error && (
              <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={handleGenerate}
                disabled={!isReady || isPending}
                className={`inline-flex items-center gap-2 rounded-2xl px-5 py-3 text-sm font-semibold transition ${
                  !isReady || isPending
                    ? 'cursor-not-allowed bg-slate-100 text-slate-400'
                    : 'bg-indigo-600 text-white hover:bg-indigo-700'
                }`}
              >
                {isPending ? <Loader2 size={18} className="animate-spin" /> : <ImagePlus size={18} />}
                {isPending ? '생성 중...' : '이미지 생성'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setResult(null);
                  setError(null);
                }}
                className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-900"
              >
                <RefreshCcw size={16} />
                결과 비우기
              </button>
              {!isReady && (
                <p className="text-sm text-slate-500">서버 URL과 인증이 준비되어야 생성할 수 있습니다.</p>
              )}
            </div>
              </>
            ) : (
              <div className="space-y-5">
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-800">서버 생성 이미지</h3>
                      <p className="mt-1 text-xs text-slate-500">ComfyUI output 폴더의 최근 이미지에서 바로 선택합니다.</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void loadServerImages()}
                      disabled={!isReady || isLoadingServerImages}
                      className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-indigo-300 hover:text-indigo-700 disabled:cursor-not-allowed disabled:text-slate-400"
                    >
                      <RefreshCcw size={14} className={isLoadingServerImages ? 'animate-spin' : ''} />
                      새로고침
                    </button>
                  </div>
                  {isLoadingServerImages ? (
                    <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500">
                      서버 이미지를 불러오는 중...
                    </div>
                  ) : serverImages.length > 0 ? (
                    <div className="grid max-h-72 grid-cols-2 gap-3 overflow-y-auto pr-1 sm:grid-cols-3">
                      {serverImages.map((image) => (
                        <button
                          key={image.relative_path}
                          type="button"
                          onClick={() => void handleSelectServerImage(image)}
                          className={`overflow-hidden rounded-2xl border bg-white text-left transition ${
                            selectedServerImagePath === image.relative_path
                              ? 'border-indigo-500 ring-2 ring-indigo-100'
                              : 'border-slate-200 hover:border-indigo-300'
                          }`}
                        >
                          <img
                            src={image.thumbnail_data_url || image.image_data_url || ''}
                            alt={image.filename}
                            className="aspect-square w-full bg-slate-950 object-contain"
                            loading="lazy"
                          />
                          <div className="space-y-1 px-2.5 py-2">
                            <div className="truncate text-xs font-semibold text-slate-700">{image.filename}</div>
                            <div className="text-[11px] text-slate-400">{formatServerImageTime(image.modified_at)}</div>
                          </div>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500">
                      아직 표시할 서버 생성 이미지가 없습니다.
                    </div>
                  )}
                </div>

                <label className="flex min-h-44 cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center transition hover:border-indigo-300 hover:bg-white" htmlFor="upscale-source">
                  <Upload className="mb-3 text-indigo-500" size={28} />
                  <span className="text-sm font-semibold text-slate-800">
                    {upscaleSourceName || (result ? '현재 생성 결과 사용 가능' : '업스케일할 이미지 선택')}
                  </span>
                  <span className="mt-1 text-xs text-slate-500">PNG, JPG, WEBP</span>
                  <input
                    id="upscale-source"
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    className="sr-only"
                    onChange={(event) => handleUpscaleSourceChange(event.target.files?.[0])}
                  />
                </label>

                <div>
                  <label className="mb-2 block text-sm font-semibold text-slate-800" htmlFor="upscale-model">
                    업스케일 모델
                  </label>
                  <select
                    id="upscale-model"
                    value={upscaleModel}
                    onChange={(event) => setUpscaleModel(event.target.value)}
                    className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-700"
                  >
                    <option value="realesrgan-x4plus">ComfyUI RealESRGAN x4 범용</option>
                    <option value="realesrgan-x4plus-anime">ComfyUI RealESRGAN x4 Anime</option>
                  </select>
                </div>

                <div>
                  <div className="mb-2 text-sm font-semibold text-slate-800">업스케일 해상도</div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                    {(Object.entries(UPSCALE_RESOLUTION_PRESETS) as Array<[UpscaleResolutionPreset, { label: string; width?: number; height?: number }]>).map(([key, value]) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setUpscaleResolution(key)}
                        className={`rounded-2xl border px-3 py-3 text-sm font-medium transition ${
                          upscaleResolution === key
                            ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                            : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                        }`}
                      >
                        <div>{value.label}</div>
                        <div className="mt-1 text-[11px] text-slate-400">
                          {key === 'native4x'
                            ? '모델 결과 그대로'
                            : key === 'custom'
                              ? `${upscaleTarget.width} × ${upscaleTarget.height}`
                              : `${value.width} × ${value.height}`}
                        </div>
                      </button>
                    ))}
                  </div>
                  {upscaleResolution === 'custom' && (
                    <div className="mt-3 grid grid-cols-2 gap-2">
                      <label className="text-xs font-semibold text-slate-600" htmlFor="upscale-custom-width">
                        가로
                        <input
                          id="upscale-custom-width"
                          type="number"
                          min={256}
                          max={4096}
                          step={64}
                          value={upscaleCustomWidth}
                          onChange={(event) => setUpscaleCustomWidth(clampUpscaleResolution(Number(event.target.value)))}
                          className="mt-1 w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700"
                        />
                      </label>
                      <label className="text-xs font-semibold text-slate-600" htmlFor="upscale-custom-height">
                        세로
                        <input
                          id="upscale-custom-height"
                          type="number"
                          min={256}
                          max={4096}
                          step={64}
                          value={upscaleCustomHeight}
                          onChange={(event) => setUpscaleCustomHeight(clampUpscaleResolution(Number(event.target.value)))}
                          className="mt-1 w-full rounded-2xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700"
                        />
                      </label>
                    </div>
                  )}
                </div>

                {error && (
                  <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {error}
                  </div>
                )}

                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={handleUpscale}
                    disabled={!isReady || isPending || (!upscaleSourceDataUrl && !result)}
                    className={`inline-flex items-center gap-2 rounded-2xl px-5 py-3 text-sm font-semibold transition ${
                      !isReady || isPending || (!upscaleSourceDataUrl && !result)
                        ? 'cursor-not-allowed bg-slate-100 text-slate-400'
                        : 'bg-indigo-600 text-white hover:bg-indigo-700'
                    }`}
                  >
                    {isPending ? <Loader2 size={18} className="animate-spin" /> : <Maximize2 size={18} />}
                    {isPending ? '업스케일 중...' : '업스케일'}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setUpscaleSourceDataUrl('');
                      setUpscaleSourceName('');
                      setSelectedServerImagePath('');
                      setUpscaleResult(null);
                      setError(null);
                    }}
                    className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-900"
                  >
                    <RefreshCcw size={16} />
                    입력 비우기
                  </button>
                </div>
              </div>
            )}
          </div>

          <div className="rounded-[24px] border border-slate-200 bg-slate-950/95 p-4 text-white shadow-[0_24px_60px_-30px_rgba(15,23,42,0.9)]">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-slate-100">생성 결과</h3>
                <p className="mt-1 text-xs text-slate-400">ComfyUI 출력 이미지와 실제 사용 프롬프트</p>
              </div>
              {result && (
                <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2.5 py-1 text-[11px] font-semibold text-emerald-300">
                  READY
                </span>
              )}
            </div>

            <div className="overflow-hidden rounded-[20px] border border-white/10 bg-slate-900">
              {activeImageDataUrl ? (
                <img
                  src={activeImageDataUrl}
                  alt={activeImageLabel || '이미지 결과'}
                  className="max-h-[72vh] w-full bg-slate-950 object-contain"
                />
              ) : (
                <div className="flex aspect-square items-center justify-center bg-[linear-gradient(135deg,rgba(99,102,241,0.18),rgba(15,23,42,0.95))] p-8 text-center">
                  <div>
                    <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-white/10 text-indigo-100">
                      <ImagePlus size={24} />
                    </div>
                    <p className="text-sm font-medium text-slate-200">아직 생성된 이미지가 없습니다.</p>
                    <p className="mt-2 text-xs leading-5 text-slate-400">왼쪽에서 장면을 적고 생성 버튼을 누르면, 결과가 여기에 바로 표시됩니다.</p>
                  </div>
                </div>
              )}
            </div>

            {(result || upscaleResult) && (
              <div className="mt-4 space-y-3 text-sm">
                {result && (
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                    <div className="mb-1 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Prompt</div>
                    <p className="leading-6 text-slate-100">{result.tool_prompt}</p>
                  </div>
                )}
                <div className="grid gap-3 sm:grid-cols-2">
                  {result && (
                    <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Spec</div>
                      <p className="mt-1 text-slate-200">
                        {result.generated_width} × {result.generated_height}
                        {result.upscale_model ? ` -> ${result.width} × ${result.height}` : ''}
                        {' · '}
                        steps {result.steps} · cfg {result.cfg} · seed {result.seed}
                      </p>
                    </div>
                  )}
                  {upscaleResult && (
                    <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Upscale</div>
                      <p className="mt-1 text-slate-200">
                        {upscaleResult.model} · x{upscaleResult.scale}
                        {' · '}
                        {upscaleResult.width} × {upscaleResult.height}
                      </p>
                    </div>
                  )}
                    <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Pipeline</div>
                      <p className="mt-1 break-all text-slate-200">
                        {upscaleResult
                          ? `anime_upscale -> ${upscaleResult.filename}`
                          : result
                            ? `${result.llm_model} -> ${result.tool_name}${result.upscale_model ? ` -> ${result.upscale_model}` : ''} -> ${result.filename}`
                            : ''}
                      </p>
                    </div>
                  </div>
              </div>
            )}

            {mode === 'generate' && (
              <div className="mt-4 rounded-[22px] border border-white/10 bg-white/5 p-3">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <div className="flex h-9 w-9 items-center justify-center rounded-2xl bg-indigo-400/15 text-indigo-200">
                      <MessageCircle size={17} />
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold text-slate-100">수정 채팅</h3>
                      <p className="mt-0.5 text-[11px] text-slate-400">구도는 유지하고 바꿀 부분만 말해보세요.</p>
                    </div>
                  </div>
                  {revisionMessages.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setRevisionMessages([])}
                      className="rounded-full border border-white/10 px-2.5 py-1 text-[11px] font-medium text-slate-300 transition hover:border-white/20 hover:text-white"
                    >
                      비우기
                    </button>
                  )}
                </div>

                <div className="mb-3 max-h-36 space-y-2 overflow-y-auto pr-1">
                  {revisionMessages.length > 0 ? (
                    revisionMessages.map((message, index) => (
                      <div
                        key={`${message.role}-${index}`}
                        className={`rounded-2xl px-3 py-2 text-xs leading-5 ${
                          message.role === 'user'
                            ? 'ml-6 bg-indigo-500 text-white'
                            : 'mr-6 border border-white/10 bg-white/10 text-slate-200'
                        }`}
                      >
                        {message.text}
                      </div>
                    ))
                  ) : (
                    <div className="rounded-2xl border border-dashed border-white/10 px-3 py-3 text-xs leading-5 text-slate-400">
                      예: 인물만 은발 남성으로 바꾸고, 배경과 구도는 유지해줘.
                    </div>
                  )}
                </div>

                <div className="flex gap-2">
                  <textarea
                    value={revisionText}
                    onChange={(event) => setRevisionText(event.target.value)}
                    rows={2}
                    placeholder="바꿀 부분만 적기"
                    className="min-h-16 flex-1 resize-none rounded-2xl border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-indigo-300"
                  />
                  <button
                    type="button"
                    onClick={handleRevisionGenerate}
                    disabled={!isReady || isPending || !canReviseImage || !revisionText.trim()}
                    className={`flex h-16 w-14 items-center justify-center rounded-2xl transition ${
                      !isReady || isPending || !canReviseImage || !revisionText.trim()
                        ? 'cursor-not-allowed bg-white/5 text-slate-500'
                        : 'bg-indigo-500 text-white hover:bg-indigo-400'
                    }`}
                    aria-label="수정 생성"
                  >
                    {isPending ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
};
