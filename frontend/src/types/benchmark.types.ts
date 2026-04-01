export type BenchmarkPreset =
  | "smoke-1"
  | "smoke-5"
  | "smoke-10"
  | "smoke-20"
  | "smoke-30"
  | "smoke-custom";
export type BenchmarkRunStatus = "queued" | "running" | "succeeded" | "failed";

export interface BenchmarkMonitoringLinks {
  grafanaUrl: string;
  prometheusUrl: string;
}

export interface BenchmarkTopError {
  error: string;
  count: number;
}

export interface BenchmarkTierSummary {
  concurrency: number;
  totalRequests: number;
  successRate: number;
  ttftP95Seconds: number | null;
  totalP95Seconds: number | null;
  throughputRps: number;
  tierStartedAtUtc: string | null;
  tierFinishedAtUtc: string | null;
  topErrors: BenchmarkTopError[];
}

export interface BenchmarkRunStatusResponse {
  jobId: string;
  preset: BenchmarkPreset;
  requestedConcurrency?: number | null;
  status: BenchmarkRunStatus;
  queuedAtUtc: string;
  startedAtUtc: string | null;
  finishedAtUtc: string | null;
  summary: BenchmarkTierSummary | null;
  error: string | null;
  summaryPath: string | null;
  resultsPath: string | null;
}

export interface BenchmarkBootstrapResponse {
  monitoring: BenchmarkMonitoringLinks;
  canRun: boolean;
  activeRun: BenchmarkRunStatusResponse | null;
  latestRun: BenchmarkRunStatusResponse | null;
}

export interface BenchmarkRunCreatedResponse {
  jobId: string;
  status: "queued" | "running";
}
