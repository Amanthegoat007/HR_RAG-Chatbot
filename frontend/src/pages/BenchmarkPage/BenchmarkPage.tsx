import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Container,
  Group,
  Loader,
  NumberInput,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import {
  TbActivityHeartbeat,
  TbAlertCircle,
  TbExternalLink,
  TbPlayerPlay,
  TbRocket,
  TbUsersGroup,
} from "react-icons/tb";

import { benchmarkApi } from "@/services/api";
import type {
  BenchmarkBootstrapResponse,
  BenchmarkPreset,
  BenchmarkRunStatusResponse,
} from "@/types/benchmark.types";
import classes from "./BenchmarkPage.module.css";

const ACTIVE_STATUSES = new Set(["queued", "running"]);
const PRESET_BUTTONS: Array<{
  preset: BenchmarkPreset;
  label: string;
  icon: typeof TbPlayerPlay;
}> = [
  { preset: "smoke-1", label: "1 user", icon: TbPlayerPlay },
  { preset: "smoke-5", label: "5 users", icon: TbRocket },
  { preset: "smoke-10", label: "10 users", icon: TbUsersGroup },
  { preset: "smoke-20", label: "20 users", icon: TbUsersGroup },
  { preset: "smoke-30", label: "30 users", icon: TbUsersGroup },
];

const formatPercent = (value: number) => `${(value * 100).toFixed(1)}%`;
const formatSeconds = (value: number | null) =>
  value == null ? "n/a" : `${value.toFixed(2)}s`;
const presetLabel = (
  preset: BenchmarkPreset,
  requestedConcurrency?: number | null,
) => {
  if (preset === "smoke-custom" && requestedConcurrency) {
    return `${requestedConcurrency}-user smoke run`;
  }

  const mapped = PRESET_BUTTONS.find((item) => item.preset === preset);
  if (mapped) {
    return `${mapped.label} smoke run`;
  }

  return "Smoke run";
};

const statusColor = (status: BenchmarkRunStatusResponse["status"]) => {
  if (status === "succeeded") return "green";
  if (status === "failed") return "red";
  if (status === "running") return "teal";
  return "blue";
};

export default function BenchmarkPage() {
  const [bootstrap, setBootstrap] = useState<BenchmarkBootstrapResponse | null>(
    null,
  );
  const [activeRun, setActiveRun] = useState<BenchmarkRunStatusResponse | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [launchingPreset, setLaunchingPreset] = useState<BenchmarkPreset | null>(
    null,
  );
  const [customConcurrency, setCustomConcurrency] = useState<number | string>(10);

  const fetchBootstrap = async () => {
    try {
      const data = await benchmarkApi.fetchBootstrap();
      setBootstrap(data);
      setActiveRun(data.activeRun);
      setError(null);
    } catch (err) {
      console.error("Failed to load benchmark bootstrap", err);
      setError("Failed to load monitoring and benchmark status.");
    } finally {
      setLoading(false);
    }
  };

  const fetchRun = async (jobId: string) => {
    try {
      const data = await benchmarkApi.fetchRun(jobId);
      setActiveRun(data);
      setError(null);

      if (!ACTIVE_STATUSES.has(data.status)) {
        await fetchBootstrap();
      }
    } catch (err) {
      console.error("Failed to fetch benchmark run", err);
      setError("Failed to refresh benchmark run status.");
    } finally {
      setLaunchingPreset(null);
    }
  };

  useEffect(() => {
    void fetchBootstrap();
  }, []);

  useEffect(() => {
    const jobId = activeRun?.jobId;
    const isActive = activeRun && ACTIVE_STATUSES.has(activeRun.status);
    if (!jobId || !isActive) {
      return;
    }

    const interval = window.setInterval(() => {
      void fetchRun(jobId);
    }, 2500);

    return () => window.clearInterval(interval);
  }, [activeRun?.jobId, activeRun?.status]);

  const handleRun = async (
    preset: BenchmarkPreset,
    concurrency?: number,
  ) => {
    try {
      setLaunchingPreset(preset);
      setError(null);
      const response = await benchmarkApi.runBenchmark(preset, concurrency);
      await fetchRun(response.jobId);
    } catch (err: any) {
      console.error("Failed to launch benchmark", err);
      const detail =
        err?.response?.data?.detail || "Failed to start the smoke benchmark.";
      setError(detail);
      setLaunchingPreset(null);
    }
  };

  const monitoring = bootstrap?.monitoring;
  const latestRun = bootstrap?.latestRun;
  const currentRun = activeRun && ACTIVE_STATUSES.has(activeRun.status)
    ? activeRun
    : bootstrap?.activeRun;
  const runInFlight = Boolean(currentRun && ACTIVE_STATUSES.has(currentRun.status));
  const disableRunButtons =
    loading || runInFlight || launchingPreset !== null || !bootstrap?.canRun;
  const customConcurrencyValue =
    typeof customConcurrency === "number" ? customConcurrency : Number(customConcurrency);
  const customConcurrencyValid =
    Number.isFinite(customConcurrencyValue) &&
    customConcurrencyValue >= 1 &&
    customConcurrencyValue <= 30;

  const topError = useMemo(() => {
    const errors = latestRun?.summary?.topErrors;
    return errors && errors.length > 0 ? errors[0] : null;
  }, [latestRun]);

  return (
    <div className={classes.page}>
      <Container size="lg" className={classes.container}>
        <Stack gap="lg">
          <Paper className={classes.hero} radius="xl">
            <Stack gap="sm">
              <Badge
                variant="light"
                radius="xl"
                className={classes.heroBadge}
                leftSection={<TbActivityHeartbeat size={14} />}
              >
                Monitoring & Benchmark
              </Badge>
              <Title order={2} className={classes.heroTitle}>
                Smoke-test the live HR copilot path
              </Title>
              <Text className={classes.heroCopy}>
                Run a tiny benchmark through the real chat flow and jump straight
                into Grafana for the same window.
              </Text>
            </Stack>
          </Paper>

          {error && (
            <Alert
              color="red"
              variant="light"
              radius="lg"
              icon={<TbAlertCircle size={16} />}
              title="Benchmark status needs attention"
            >
              {error}
            </Alert>
          )}

          <SimpleGrid cols={{ base: 1, md: 3 }} spacing="lg">
            <Paper className={classes.card} radius="xl">
              <Stack gap="md">
                <div className={classes.statusRow}>
                  <Title order={3} className={classes.cardTitle}>
                    Run smoke benchmark
                  </Title>
                  {runInFlight && (
                    <span className={classes.statusIndicator}>
                      <Loader size="xs" color="var(--app-accent-primary)" />
                      {currentRun?.status === "queued" ? "Queued" : "Running"}
                    </span>
                  )}
                </div>
                <Text className={classes.cardCopy}>
                  Launch a quick benchmark through the live frontend proxy with
                  isolated benchmark-user traffic.
                </Text>
                <div className={classes.presetGrid}>
                  {PRESET_BUTTONS.map(({ preset, label, icon: Icon }) => (
                    <Button
                      key={preset}
                      radius="xl"
                      variant="light"
                      leftSection={<Icon size={16} />}
                      disabled={disableRunButtons}
                      loading={launchingPreset === preset}
                      onClick={() => void handleRun(preset)}
                    >
                      {label}
                    </Button>
                  ))}
                </div>
                <div className={classes.customRow}>
                  <NumberInput
                    min={1}
                    max={30}
                    clampBehavior="strict"
                    label="Custom users"
                    value={customConcurrency}
                    onChange={setCustomConcurrency}
                    disabled={disableRunButtons}
                    classNames={{ input: classes.customInput }}
                  />
                  <Button
                    radius="xl"
                    variant="default"
                    leftSection={<TbUsersGroup size={16} />}
                    disabled={disableRunButtons || !customConcurrencyValid}
                    loading={launchingPreset === "smoke-custom"}
                    onClick={() =>
                      void handleRun("smoke-custom", customConcurrencyValue)
                    }
                  >
                    Run custom
                  </Button>
                </div>
                {currentRun && (
                  <Text className={classes.detailText}>
                    Active preset:{" "}
                    {presetLabel(
                      currentRun.preset,
                      currentRun.requestedConcurrency,
                    )}
                  </Text>
                )}
              </Stack>
            </Paper>

            <Paper className={classes.card} radius="xl">
              <Stack gap="md">
                <Title order={3} className={classes.cardTitle}>
                  Monitoring
                </Title>
                <Text className={classes.cardCopy}>
                  Open the live dashboards to correlate latency, throughput,
                  cache behavior, and service memory during the benchmark run.
                </Text>
                <div className={classes.linkRow}>
                  <Button
                    radius="xl"
                    variant="default"
                    justify="space-between"
                    rightSection={<TbExternalLink size={16} />}
                    disabled={!monitoring}
                    onClick={() =>
                      monitoring &&
                      window.open(
                        monitoring.grafanaUrl,
                        "_blank",
                        "noopener,noreferrer",
                      )
                    }
                  >
                    Open Grafana
                  </Button>
                  <Button
                    radius="xl"
                    variant="default"
                    justify="space-between"
                    rightSection={<TbExternalLink size={16} />}
                    disabled={!monitoring}
                    onClick={() =>
                      monitoring &&
                      window.open(
                        monitoring.prometheusUrl,
                        "_blank",
                        "noopener,noreferrer",
                      )
                    }
                  >
                    Open Prometheus
                  </Button>
                </div>
              </Stack>
            </Paper>

            <Paper className={classes.card} radius="xl">
              <Stack gap="md">
                <div className={classes.statusRow}>
                  <Title order={3} className={classes.cardTitle}>
                    Last run
                  </Title>
                  {latestRun && (
                    <Badge color={statusColor(latestRun.status)} variant="light">
                      {latestRun.status}
                    </Badge>
                  )}
                </div>
                {!latestRun ? (
                  <div className={classes.emptyState}>
                    No completed smoke benchmark yet.
                  </div>
                ) : (
                  <Stack gap="md">
                    <Text className={classes.cardCopy}>
                      {presetLabel(
                        latestRun.preset,
                        latestRun.requestedConcurrency,
                      )}
                    </Text>
                    {latestRun.summary && (
                      <div className={classes.metricGrid}>
                        <div className={classes.metricTile}>
                          <Text className={classes.detailLabel}>Success</Text>
                          <Text className={classes.metricValue}>
                            {formatPercent(latestRun.summary.successRate)}
                          </Text>
                        </div>
                        <div className={classes.metricTile}>
                          <Text className={classes.detailLabel}>Throughput</Text>
                          <Text className={classes.metricValue}>
                            {latestRun.summary.throughputRps.toFixed(2)} req/s
                          </Text>
                        </div>
                        <div className={classes.metricTile}>
                          <Text className={classes.detailLabel}>TTFT P95</Text>
                          <Text className={classes.metricValue}>
                            {formatSeconds(latestRun.summary.ttftP95Seconds)}
                          </Text>
                        </div>
                        <div className={classes.metricTile}>
                          <Text className={classes.detailLabel}>Total P95</Text>
                          <Text className={classes.metricValue}>
                            {formatSeconds(latestRun.summary.totalP95Seconds)}
                          </Text>
                        </div>
                      </div>
                    )}
                    <div className={classes.detailStack}>
                      <Text className={classes.detailText}>
                        UTC window:{" "}
                        {latestRun.summary?.tierStartedAtUtc || latestRun.startedAtUtc || "n/a"}{" "}
                        to{" "}
                        {latestRun.summary?.tierFinishedAtUtc || latestRun.finishedAtUtc || "n/a"}
                      </Text>
                      {topError && (
                        <Text className={classes.detailText}>
                          Top error: {topError.error} ({topError.count})
                        </Text>
                      )}
                      {latestRun.error && (
                        <Text className={classes.detailText}>
                          Failure detail: {latestRun.error}
                        </Text>
                      )}
                    </div>
                  </Stack>
                )}
              </Stack>
            </Paper>
          </SimpleGrid>
        </Stack>
      </Container>
    </div>
  );
}
