import { useEffect, useState } from "react";
import {
  Container,
  Title,
  Paper,
  Stack,
  Modal,
  Button,
  Group,
  Text,
  Loader,
  Alert,
} from "@mantine/core";
import { TbAlertCircle } from "react-icons/tb";
import { documentService, DocumentInfo } from "@/services/documentService";
import { DocumentTable } from "./DocumentTable";
import { UploadArea } from "./UploadArea";

export default function DocumentManagementPage() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [documentToDelete, setDocumentToDelete] = useState<DocumentInfo | null>(
    null,
  );
  const [isDeleting, setIsDeleting] = useState(false);

  const fetchDocuments = async (showLoading = true) => {
    try {
      if (showLoading) setLoading(true);
      const data = await documentService.getDocuments();
      setDocuments(data);
      setError(null);
    } catch (err) {
      console.error("Failed to fetch documents:", err);
      setError("Failed to load documents. Please try again.");
    } finally {
      if (showLoading) setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocuments();

    // Poll for updates if any document is processing or pending
    const interval = setInterval(() => {
      setDocuments((currentDocs) => {
        const needsUpdate = currentDocs.some(
          (d) => d.status === "pending" || d.status === "processing",
        );
        if (needsUpdate) {
          fetchDocuments(false);
        }
        return currentDocs;
      });
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  const handleDrop = async (files: File[]) => {
    if (files.length === 0) return;

    setUploading(true);
    setError(null);

    try {
      // Upload files sequentially for simplicity, or Promise.all for parallel
      for (const file of files) {
        await documentService.uploadDocument(file);
      }
      await fetchDocuments(false);
    } catch (err) {
      console.error("Upload failed", err);
      setError("Failed to upload document(s).");
    } finally {
      setUploading(false);
    }
  };

  const confirmDelete = async () => {
    if (!documentToDelete) return;

    setIsDeleting(true);
    try {
      await documentService.deleteDocument(documentToDelete.id);
      // Optimistic UI update: remove from local state immediately
      setDocuments((prev) => prev.filter((d) => d.id !== documentToDelete.id));
      setDeleteModalOpen(false);
      setDocumentToDelete(null);
      // Re-fetch to ensure sync with backend
      await fetchDocuments(false);
    } catch (err) {
      console.error("Delete failed", err);
      setError("Failed to delete document.");
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <Container size="xl" py="xl">
      <Stack gap="xl">
        <Title order={2} style={{ color: "var(--mantine-color-text)" }}>
          Document Management
        </Title>
        <Text c="dimmed">
          Upload and manage organizational documents. These documents will be
          processed and become available for the HR Chatbot to query.
        </Text>

        {error && (
          <Alert
            icon={<TbAlertCircle size={16} />}
            title="Error"
            color="red"
            variant="light"
          >
            {error}
          </Alert>
        )}

        <Paper
          shadow="sm"
          p="md"
          radius="md"
          withBorder
          style={{
            backgroundColor: "var(--app-surface)",
            borderColor: "var(--app-border)",
          }}
        >
          <Stack gap="md">
            <Title order={4} style={{ color: "var(--mantine-color-text)" }}>
              Upload New Documents
            </Title>
            <UploadArea onDrop={handleDrop} loading={uploading} />
          </Stack>
        </Paper>

        <Paper
          shadow="sm"
          p="md"
          radius="md"
          withBorder
          style={{
            backgroundColor: "var(--app-surface)",
            borderColor: "var(--app-border)",
          }}
        >
          <Stack gap="md">
            <Group justify="space-between" align="center">
              <Title order={4} style={{ color: "var(--mantine-color-text)" }}>
                Organization Documents
              </Title>
              {loading && (
                <Loader size="sm" color="var(--app-accent-primary)" />
              )}
            </Group>

            {!loading && (
              <DocumentTable
                documents={documents}
                onDeleteClick={(doc) => {
                  setDocumentToDelete(doc);
                  setDeleteModalOpen(true);
                }}
              />
            )}
          </Stack>
        </Paper>
      </Stack>

      <Modal
        opened={deleteModalOpen}
        onClose={() => !isDeleting && setDeleteModalOpen(false)}
        title="Confirm Deletion"
        centered
        overlayProps={{ backgroundOpacity: 0.5, blur: 4 }}
      >
        <Text size="sm" mb="xl">
          Are you sure you want to delete{" "}
          <strong>{documentToDelete?.filename}</strong>? This will remove it
          from the database and the vector store. This action cannot be undone.
        </Text>
        <Group justify="flex-end">
          <Button
            variant="subtle"
            color="gray"
            onClick={() => setDeleteModalOpen(false)}
            disabled={isDeleting}
          >
            Cancel
          </Button>
          <Button color="red" onClick={confirmDelete} loading={isDeleting}>
            Delete Document
          </Button>
        </Group>
      </Modal>
    </Container>
  );
}
