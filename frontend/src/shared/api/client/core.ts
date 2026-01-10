export type RequestFn = <T>(endpoint: string, options?: RequestInit) => Promise<T>;
export type CreateHeadersFn = (withJson?: boolean) => HeadersInit;
