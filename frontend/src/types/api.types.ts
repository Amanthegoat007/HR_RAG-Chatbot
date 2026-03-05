export interface ErrorResponse {
  message: string;
  error?: string;
}

export interface QueuedRequest {
  resolve: (value?: unknown) => void;
  reject: (error: Error) => void;
}
