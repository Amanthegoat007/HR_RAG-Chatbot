export interface ChatChartProps {
  data: {
    records: Record<string, any>[];
    chart_type: "bar" | "line" | "area" | "pie";
    x_key: string;
    y_keys: string[];
    title?: string;
  };
}
