import { Table, Paper, ScrollArea, Button, Box } from "@mantine/core";
import { useState } from "react";
import { TbChevronDown, TbChevronUp } from "react-icons/tb";

import { ChatTableProps } from "./ChatTable.types";

export function ChatTable({ data }: ChatTableProps) {
  const [showAll, setShowAll] = useState(false);

  if (!data || !data.records || data.records.length === 0) return null;

  // Extract headers from first record
  const headers = Object.keys(data.records[0]);

  const displayRows = showAll ? data.records : data.records.slice(0, 5);
  const hasMore = data.records.length > 5;

  return (
    <Box my="sm" style={{ width: "100%", overflow: "hidden" }}>
      <ScrollArea>
        <Table striped highlightOnHover withTableBorder={false}>
          <Table.Thead>
            <Table.Tr>
              {headers.map((header) => (
                <Table.Th key={header} style={{ whiteSpace: "nowrap" }}>
                  {header}
                </Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {displayRows.map((record, rowIndex) => (
              <Table.Tr key={rowIndex}>
                {headers.map((header) => (
                  <Table.Td key={header}>{record[header] ?? ""}</Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
          {/* {data.caption && <Table.Caption>{data.caption}</Table.Caption>} */}
        </Table>
      </ScrollArea>

      {hasMore && (
        <Box
          mt="xs"
          style={{
            display: "flex",
            justifyContent: "center",
            borderTop: "1px solid var(--app-border)",
            paddingTop: "8px",
          }}
        >
          <Button
            variant="subtle"
            size="compact-xs"
            onClick={() => setShowAll(!showAll)}
            rightSection={
              showAll ? <TbChevronUp size={14} /> : <TbChevronDown size={14} />
            }
            color="brand"
          >
            {showAll ? "Show Less" : `Show All (${data.records.length} rows)`}
          </Button>
        </Box>
      )}
    </Box>
  );
}
