import React, { startTransition, useEffect, useMemo, useState } from 'react';
import { ImagePlus, Loader2, Maximize2, RefreshCcw, Sparkles, Upload } from 'lucide-react';
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

type CanvasPreset = 'square' | 'portrait' | 'landscape' | 'wide' | 'custom';
type StudioMode = 'generate' | 'upscale';

const CANVAS_PRESETS: Record<CanvasPreset, { label: string; width: number; height: number }> = {
  square: { label: '1024 정사각', width: 1024, height: 1024 },
  portrait: { label: '896 세로', width: 896, height: 1152 },
  landscape: { label: '1344 가로', width: 1344, height: 768 },
  wide: { label: '1536 와이드', width: 1536, height: 864 },
  custom: { label: '직접 입력', width: 1024, height: 1024 },
};

const clampResolution = (value: number) => Math.min(Math.max(value || 1024, 512), 1536);

const formatServerImageTime = (value: string) =>
  new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));

const STARTER_PROMPTS = [
  '비 오는 창가에서 낮잠 자는 치즈 고양이, 따뜻한 동화풍 일러스트',
  '서울 골목길 네온사인 아래 서 있는 미래적인 재킷의 여성, 시네마틱 사진풍',
  '우드톤 작업실 책상 위에 놓인 커피와 노트북, 아침 햇살, 감성 광고 비주얼',
];

export const ImageGenerationDashboard: React.FC<ImageGenerationDashboardProps> = ({
  serverUrl,
  apiToken,
  cookieAuth,
}) => {
  const [requestText, setRequestText] = useState(STARTER_PROMPTS[0]);
  const [mode, setMode] = useState<StudioMode>('generate');
  const [preset, setPreset] = useState<CanvasPreset>('square');
  const [customWidth, setCustomWidth] = useState(1024);
  const [customHeight, setCustomHeight] = useState(1024);
  const [steps, setSteps] = useState(20);
  const [seed, setSeed] = useState('');
  const [upscaleSourceDataUrl, setUpscaleSourceDataUrl] = useState('');
  const [upscaleSourceName, setUpscaleSourceName] = useState('');
  const [selectedServerImagePath, setSelectedServerImagePath] = useState('');
  const [serverImages, setServerImages] = useState<BackendServerGeneratedImage[]>([]);
  const [isLoadingServerImages, setIsLoadingServerImages] = useState(false);
  const [upscaleModel, setUpscaleModel] = useState('realesrgan-x4plus-anime');
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
  const activeImageDataUrl = upscaleResult?.image_data_url ?? result?.image_data_url ?? upscaleSourceDataUrl;
  const activeImageLabel = upscaleResult?.filename ?? result?.request ?? upscaleSourceName;

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

  const handleSelectServerImage = (image: BackendServerGeneratedImage) => {
    startTransition(() => {
      setUpscaleSourceDataUrl(image.image_data_url);
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
            E4B + COMFYUI
          </div>
          <div className="max-w-2xl">
            <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-indigo-50">
              <Sparkles size={14} />
              자연어 요청을 e4b가 ComfyUI 프롬프트로 자동 변환
            </div>
            <h2 className="text-2xl font-bold tracking-tight">이미지 생성 스튜디오</h2>
            <p className="mt-2 text-sm leading-6 text-indigo-100/90">
              장면만 적으면 e4b가 tool call로 ComfyUI를 실행하고, 결과 이미지를 바로 가져옵니다.
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
                placeholder="예: 빛바랜 필름 질감의 여름 해변, 모래 위에서 책 읽는 소녀, 따뜻한 역광"
                className="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-700 outline-none transition focus:border-indigo-400 focus:bg-white"
              />
            </div>

            <div className="flex flex-wrap gap-2">
              {STARTER_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => setRequestText(prompt)}
                  className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-indigo-300 hover:text-indigo-700"
                >
                  {prompt}
                </button>
              ))}
            </div>

            <div className="grid gap-4 sm:grid-cols-[1.4fr_0.8fr]">
              <div>
                <div className="mb-2 text-sm font-semibold text-slate-800">해상도</div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
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
                          onClick={() => handleSelectServerImage(image)}
                          className={`overflow-hidden rounded-2xl border bg-white text-left transition ${
                            selectedServerImagePath === image.relative_path
                              ? 'border-indigo-500 ring-2 ring-indigo-100'
                              : 'border-slate-200 hover:border-indigo-300'
                          }`}
                        >
                          <img
                            src={image.image_data_url}
                            alt={image.filename}
                            className="aspect-square w-full object-cover"
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
                    애니 업스케일 모델
                  </label>
                  <select
                    id="upscale-model"
                    value={upscaleModel}
                    onChange={(event) => setUpscaleModel(event.target.value)}
                    className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-700"
                  >
                    <option value="realesrgan-x4plus-anime">RealESRGAN x4plus Anime</option>
                    <option value="realesr-animevideov3">RealESRGAN AnimeVideo v3</option>
                  </select>
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
                  className="aspect-square w-full object-cover"
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
                        {result.width} × {result.height} · steps {result.steps} · cfg {result.cfg} · seed {result.seed}
                      </p>
                    </div>
                  )}
                  {upscaleResult && (
                    <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Upscale</div>
                      <p className="mt-1 text-slate-200">
                        {upscaleResult.model} · x{upscaleResult.scale}
                      </p>
                    </div>
                  )}
                    <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Pipeline</div>
                      <p className="mt-1 break-all text-slate-200">
                        {upscaleResult
                          ? `anime_upscale -> ${upscaleResult.filename}`
                          : result
                            ? `${result.llm_model} -> ${result.tool_name} -> ${result.filename}`
                            : ''}
                      </p>
                    </div>
                  </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
};
