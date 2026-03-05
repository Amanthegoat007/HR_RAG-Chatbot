import { useState } from "react";
import { Box, Button, Text, Group, Paper, Stack, Divider } from "@mantine/core";
import { TbTable, TbChartBar } from "react-icons/tb";
import { ChatTable } from "../ChatTable";
import { ChatChart } from "../ChatChart";
import type { DataViewData } from "@/utils/contentParser";

import { ChatDataViewProps } from "./ChatDataView.types";

export function ChatDataView({ data }: ChatDataViewProps) {
  const [view, setView] = useState<"chart" | "table">(
    data.has_table ? "table" : "chart",
  );

  if (!data || !data.records || data.records.length === 0) return null;

  const hasChart = data.has_chart;
  const hasTable = data.has_table !== false;
  const hasAnyViz = hasChart || hasTable;

  return (
    <Paper
      radius="lg"
      shadow="md"
      p="md"
      withBorder
      mt="md"
      style={{
        backgroundColor: "var(--app-background-module)",
        width: "100%",
        borderColor: "var(--app-border)",
      }}
    >
      {/* Header */}
      <Group justify="space-between" mb="xs">
        <Stack gap={0}>
          <Text fw={600} size="sm" c="var(--app-text-primary)">
            {data.title ?? "Data View"}
          </Text>
          {data.caption && (
            <Text size="xs" c="var(--app-text-secondary)">
              {data.caption}
            </Text>
          )}
        </Stack>

        {/* Connected Buttons - Only show if there's more than one view or if specifically requested */}
        {hasChart && hasTable && (
          <Group
            gap={0}
            style={{
              background: "var(--app-surface-hover)",
              padding: 4,
              borderRadius: 999,
            }}
          >
            <Button
              size="sm"
              leftSection={<TbTable size={14} />}
              disabled={!hasTable}
              onClick={() => setView("table")}
              variant="subtle"
              styles={{
                root: {
                  borderTopRightRadius: 0,
                  borderBottomRightRadius: 0,
                  backgroundColor:
                    view === "table"
                      ? "var(--app-accent-primary)"
                      : "transparent",
                  color: view === "table" ? "#fff" : "var(--app-text-primary)",
                  boxShadow:
                    view === "table" ? "0 2px 6px rgba(0,0,0,0.1)" : "none",

                  "&:hover": {
                    backgroundColor:
                      view === "table"
                        ? "var(--app-accent-secondary)"
                        : "var(--app-background-module)",
                  },
                  "&:disabled": {
                    backgroundColor: "transparent",
                    opacity: 0.4,
                    cursor: "not-allowed",
                  },
                },
              }}
            >
              Table
            </Button>

            <Button
              size="sm"
              leftSection={<TbChartBar size={14} />}
              disabled={!hasChart}
              onClick={() => setView("chart")}
              variant="subtle"
              styles={{
                root: {
                  borderTopLeftRadius: 0,
                  borderBottomLeftRadius: 0,
                  backgroundColor:
                    view === "chart"
                      ? "var(--app-accent-primary)"
                      : "transparent",
                  color: view === "chart" ? "#fff" : "var(--app-text-primary)",
                  boxShadow:
                    view === "chart" ? "0 2px 6px rgba(0,0,0,0.1)" : "none",

                  "&:hover": {
                    backgroundColor:
                      view === "chart"
                        ? "var(--app-accent-secondary)"
                        : "var(--app-background-module)",
                  },

                  "&:disabled": {
                    backgroundColor: "transparent",
                    opacity: 0.4,
                    cursor: "not-allowed",
                  },
                },
              }}
            >
              Chart
            </Button>
          </Group>
        )}
      </Group>

      <Divider mb="sm" />

      {/* Content */}
      {hasAnyViz ? (
        <Box>
          {view === "chart" && hasChart && (
            <ChatChart
              data={{
                records: data.records,
                chart_type: data.chart_type!,
                x_key: data.x_key!,
                y_keys: data.y_keys!,
                title: data.title,
              }}
            />
          )}

          {view === "table" && hasTable && (
            <ChatTable
              data={{
                records: data.records,
                caption: data.caption,
              }}
            />
          )}
        </Box>
      ) : (
        <Box>
          {/* If no viz, the header with title/caption is already sufficient, 
                        but we could add a subtle text block here if needed. 
                        Currently, it just shows the Paper container with the title/caption. */}
        </Box>
      )}
    </Paper>
  );
}
