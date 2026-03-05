import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  PieChart,
  Pie,
} from "recharts";
import { Title, Box, Text } from "@mantine/core";

import { ChatChartProps } from "./ChatChart.types";

const COLORS = [
  "#10b981", // Emerald
  "#14b8a6", // Teal
  "#6366f1", // Indigo
  "#0ea5e9", // Sky
  "#8b5cf6", // Violet
  "#047857", // Emerald Dark
];

export function ChatChart({ data }: ChatChartProps) {
  if (!data || !data.records || !data.chart_type) return null;

  const { records, chart_type, x_key, y_keys, title } = data;

  const renderChart = () => {
    switch (chart_type) {
      case "bar":
        return (
          <BarChart data={records}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={x_key} />
            <YAxis />
            <Tooltip />
            <Legend />
            {y_keys.map((key, i) => (
              <Bar key={key} dataKey={key} fill={COLORS[i % COLORS.length]} />
            ))}
          </BarChart>
        );
      case "line":
        return (
          <LineChart data={records}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={x_key} />
            <YAxis />
            <Tooltip />
            <Legend />
            {y_keys.map((key, i) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={COLORS[i % COLORS.length]}
                strokeWidth={2}
              />
            ))}
          </LineChart>
        );
      case "area":
        return (
          <AreaChart data={records}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={x_key} />
            <YAxis />
            <Tooltip />
            <Legend />
            {y_keys.map((key, i) => (
              <Area
                key={key}
                type="monotone"
                dataKey={key}
                stroke={COLORS[i % COLORS.length]}
                fill={COLORS[i % COLORS.length]}
              />
            ))}
          </AreaChart>
        );
      case "pie":
        // For pie charts, use first y_key as the value
        const valueKey = y_keys[0];
        const pieDataWithColors = records.map((entry, index) => ({
          ...entry,
          fill: COLORS[index % COLORS.length],
        }));
        return (
          <PieChart>
            <Pie
              data={pieDataWithColors}
              dataKey={valueKey}
              nameKey={x_key}
              cx="50%"
              cy="50%"
              outerRadius={80}
              label
            />
            <Tooltip />
            <Legend />
          </PieChart>
        );
      default:
        return <Text c="red">Unsupported chart type: {chart_type}</Text>;
    }
  };

  return (
    <Box style={{ width: "100%" }}>
      {/* {title && (
        <Title order={5} mb="md" ta="center">
          {title}
        </Title>
      )} */}
      <Box h={250} w="100%">
        <ResponsiveContainer width="100%" height="100%">
          {renderChart()}
        </ResponsiveContainer>
      </Box>
    </Box>
  );
}
