export interface UseDashboardDataResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}
