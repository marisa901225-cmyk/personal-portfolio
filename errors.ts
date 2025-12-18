import { ApiError, NetworkError } from './backendClient';

export type UserErrorMessages = {
  default: string;
  unauthorized?: string;
  rateLimited?: string;
  network?: string;
};

export const isNetworkError = (error: unknown): boolean => {
  if (error instanceof NetworkError) return true;
  if (error instanceof TypeError) return true;
  return false;
};

export const isApiError = (error: unknown): error is ApiError => error instanceof ApiError;

export const isApiErrorStatus = (error: unknown, status: number): boolean =>
  error instanceof ApiError && error.status === status;

export const getUserErrorMessage = (error: unknown, messages: UserErrorMessages): string => {
  if (isApiError(error)) {
    if (isApiErrorStatus(error, 401) && messages.unauthorized) return messages.unauthorized;
    if (isApiErrorStatus(error, 429) && messages.rateLimited) return messages.rateLimited;
    return messages.default;
  }

  if (isNetworkError(error)) {
    return messages.network ?? messages.default;
  }

  return messages.default;
};

export const alertError = (context: string, error: unknown, messages: UserErrorMessages): void => {
  console.error(context, error);
  if (typeof window !== 'undefined') {
    window.alert(getUserErrorMessage(error, messages));
  }
};
