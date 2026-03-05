export type ChartData = {
  records: Record<string, any>[];
  chart_type: "bar" | "line" | "area" | "pie";
  x_key: string;
  y_keys: string[];
  title?: string;
};

export type TableData = {
  records: Record<string, any>[];
  caption?: string;
};

export type DataViewData = {
  records: Record<string, any>[];
  has_chart: boolean;
  has_table?: boolean;
  chart_type?: "bar" | "line" | "area" | "pie";
  x_key?: string;
  y_keys?: string[];
  title?: string;
  caption?: string;
};

export type ContentBlock = {
  type: "text" | "table" | "chart" | "data_view";
  content?: string; // for text blocks
  data?: ChartData | TableData | DataViewData; // for table/chart blocks
};

export type ParsedContent = {
  text: string;
  type: "text" | "chart" | "table" | "sql" | "error" | "data" | "blocks";
  data: ChartData | TableData | DataViewData | any | null;
  blocks?: ContentBlock[]; // For multi-block content
  extras: Record<string, any>;
};
