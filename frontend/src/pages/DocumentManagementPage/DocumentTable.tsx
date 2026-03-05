import { Table, ActionIcon, Group, Text, Tooltip } from "@mantine/core";
import { TbTrash, TbFileAlert } from "react-icons/tb";
import { DocumentStatusBadge } from "./DocumentStatusBadge";
import type { DocumentInfo } from "@/services/documentService";

interface DocumentTableProps {
  documents: DocumentInfo[];
  onDeleteClick: (doc: DocumentInfo) => void;
}

const formatBytes = (bytes: number) => {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
};

export function DocumentTable({
  documents,
  onDeleteClick,
}: DocumentTableProps) {
  if (documents.length === 0) {
    return (
      <Text c="dimmed" ta="center" py="xl">
        No documents found. Upload a document to get started.
      </Text>
    );
  }

  const rows = documents.map((doc) => (
    <Table.Tr key={doc.id}>
      <Table.Td>
        <Group gap="sm">
          <Text
            size="sm"
            fw={500}
            style={{ color: "var(--mantine-color-text)" }}
          >
            {doc.filename}
          </Text>
        </Group>
      </Table.Td>
      <Table.Td>
        <DocumentStatusBadge status={doc.status} />
        {doc.status === "failed" && doc.error_message && (
          <Tooltip label={doc.error_message}>
            <ActionIcon variant="transparent" color="red" size="sm" ml="xs">
              <TbFileAlert />
            </ActionIcon>
          </Tooltip>
        )}
      </Table.Td>
      <Table.Td>{formatBytes(doc.file_size_bytes)}</Table.Td>
      <Table.Td>{new Date(doc.uploaded_at).toLocaleDateString()}</Table.Td>
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
    <Table
      highlightOnHover
      verticalSpacing="sm"
      style={{ backgroundColor: "var(--app-surface)", borderRadius: "8px" }}
    >
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
  );
}
