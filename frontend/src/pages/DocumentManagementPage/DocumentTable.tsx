import { Table, ActionIcon, Group, Text, Tooltip, ScrollArea } from "@mantine/core";
import { TbTrash, TbFileAlert } from "react-icons/tb";

import { DocumentStatusBadge } from "./DocumentStatusBadge";
import type { DocumentInfo, DocumentScope } from "@/services/documentService";
import classes from "./DocumentTable.module.css";

interface DocumentTableProps {
  documents: DocumentInfo[];
  scope: DocumentScope;
  onDeleteClick: (doc: DocumentInfo) => void;
}

const formatBytes = (bytes: number) => {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
};

export function DocumentTable({
  documents,
  scope,
  onDeleteClick,
}: DocumentTableProps) {
  if (documents.length === 0) {
    return (
      <div className={classes.emptyState}>
        <Text className={classes.emptyTitle}>No documents yet</Text>
        <Text className={classes.emptyCopy}>
          {scope === "library"
            ? "Upload a policy or reference file to start building the shared knowledge library."
            : "Session attachments from chat conversations will appear here once they finish processing."}
        </Text>
      </div>
    );
  }

  const rows = documents.map((doc) => (
    <Table.Tr key={doc.id} className={classes.row}>
      <Table.Td>
        <Group gap="sm" wrap="nowrap" align="flex-start">
          <div className={classes.fileMeta}>
            <Text size="sm" fw={600} className={classes.filename}>
              {doc.filename}
            </Text>
            <Text size="xs" className={classes.fileSubtext}>
              {doc.original_format.toUpperCase()}
              {doc.scope === "session" ? " • session upload" : ""}
              {doc.page_count ? ` • ${doc.page_count} page${doc.page_count > 1 ? "s" : ""}` : ""}
              {doc.chunk_count ? ` • ${doc.chunk_count} chunks` : ""}
            </Text>
          </div>
        </Group>
      </Table.Td>
      <Table.Td>
        <Group gap="xs" wrap="nowrap">
          <DocumentStatusBadge status={doc.status} />
          {doc.status === "failed" && doc.error_message ? (
            <Tooltip label={doc.error_message}>
              <ActionIcon variant="transparent" color="red" size="sm">
                <TbFileAlert />
              </ActionIcon>
            </Tooltip>
          ) : null}
        </Group>
      </Table.Td>
      <Table.Td className={classes.cellMuted}>{formatBytes(doc.file_size_bytes)}</Table.Td>
      <Table.Td className={`${classes.cellMuted} ${classes.uploadedCell}`}>
        {new Date(doc.uploaded_at).toLocaleDateString()}
      </Table.Td>
      <Table.Td>
        <ActionIcon
          variant="subtle"
          color="red"
          onClick={() => onDeleteClick(doc)}
          title="Delete document"
        >
          <TbTrash size={18} />
        </ActionIcon>
      </Table.Td>
    </Table.Tr>
  ));

  return (
    <ScrollArea
      type="auto"
      offsetScrollbars="x"
      scrollbarSize={8}
      className={classes.scrollArea}
    >
      <Table className={classes.table} verticalSpacing="md" horizontalSpacing="md">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Filename</Table.Th>
            <Table.Th>Status</Table.Th>
            <Table.Th>Size</Table.Th>
            <Table.Th>Uploaded</Table.Th>
            <Table.Th>Actions</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>{rows}</Table.Tbody>
      </Table>
    </ScrollArea>
  );
}
