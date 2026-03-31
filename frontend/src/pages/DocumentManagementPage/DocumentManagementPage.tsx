import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Container,
  Group,
  Loader,
  Modal,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { TbAlertCircle, TbDatabase, TbFileCheck, TbLoader2 } from "react-icons/tb";

import { documentService, type DocumentInfo } from "@/services/documentService";
import { DocumentTable } from "./DocumentTable";
import { UploadArea } from "./UploadArea";
import classes from "./DocumentManagementPage.module.css";

const IN_PROGRESS_STATUSES = ["pending", "processing"];

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
      const data = await documentService.getDocuments("library");
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
    void fetchDocuments();

    const interval = window.setInterval(() => {
      const needsRefresh = documents.some((doc) =>
        IN_PROGRESS_STATUSES.includes(doc.status),
      );
      if (needsRefresh) {
        void fetchDocuments(false);
      }
    }, 2500);

    return () => window.clearInterval(interval);
  }, [documents]);

  const handleDrop = async (files: File[]) => {
    if (files.length === 0) return;

    setUploading(true);
    setError(null);

    try {
      for (const file of files) {
        await documentService.uploadDocument(file, { scope: "library" });
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
      setDocuments((prev) => prev.filter((d) => d.id !== documentToDelete.id));
      setDeleteModalOpen(false);
      setDocumentToDelete(null);
      await fetchDocuments(false);
    } catch (err) {
      console.error("Delete failed", err);
      setError("Failed to delete document.");
    } finally {
      setIsDeleting(false);
    }
  };

  const stats = useMemo(() => {
    const ready = documents.filter((doc) => doc.status === "ready").length;
    const processing = documents.filter((doc) =>
      IN_PROGRESS_STATUSES.includes(doc.status),
    ).length;
    const failed = documents.filter((doc) => doc.status === "failed").length;
    return { total: documents.length, ready, processing, failed };
  }, [documents]);

  return (
    <div className={classes.page}>
      <Container size="xl" className={classes.container}>
        <Stack gap="xl">
          <Paper className={classes.hero} radius="xl">
            <Stack gap="sm">
              <Badge
                variant="light"
                radius="xl"
                className={classes.heroBadge}
                leftSection={<TbDatabase size={14} />}
              >
                Knowledge Library
              </Badge>
              <Title order={1} className={classes.heroTitle}>
                Document intake for your HR copilot
              </Title>
              <Text className={classes.heroCopy}>
                Upload, process, and monitor organizational documents from one
                shared intake flow. Documents become searchable after
                processing completes.
              </Text>
            </Stack>
          </Paper>

          {error && (
            <Alert
              icon={<TbAlertCircle size={16} />}
              title="Something needs attention"
              color="red"
              variant="light"
              radius="lg"
            >
              {error}
            </Alert>
          )}

          <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
            <Paper className={classes.statCard} radius="xl">
              <Text className={classes.statLabel}>Ready</Text>
              <Text className={classes.statValue}>{stats.ready}</Text>
              <Text className={classes.statHint}>
                Documents available to the assistant now.
              </Text>
            </Paper>
            <Paper className={classes.statCard} radius="xl">
              <Text className={classes.statLabel}>Processing</Text>
              <Group justify="space-between" align="center">
                <Text className={classes.statValue}>{stats.processing}</Text>
                {stats.processing > 0 ? (
                  <Loader size="sm" color="var(--app-accent-primary)" />
                ) : (
                  <TbLoader2 className={classes.statIconMuted} size={18} />
                )}
              </Group>
              <Text className={classes.statHint}>
                Intake jobs moving through normalization and indexing.
              </Text>
            </Paper>
            <Paper className={classes.statCard} radius="xl">
              <Text className={classes.statLabel}>Total library docs</Text>
              <Text className={classes.statValue}>{stats.total}</Text>
              <Text className={classes.statHint}>
                Includes ready, processing, and failed documents.
              </Text>
            </Paper>
          </SimpleGrid>

          <SimpleGrid cols={{ base: 1, lg: 3 }} spacing="lg">
            <Paper className={classes.uploadPanel} radius="xl">
              <Stack gap="md">
                <Group justify="space-between" align="flex-start">
                  <div>
                    <Title order={3} className={classes.sectionTitle}>
                      Upload documents
                    </Title>
                    <Text className={classes.sectionCopy}>
                      Add HR policies, benefits guides, and utility-space
                      reference documents to the shared library.
                    </Text>
                  </div>
                  {uploading ? (
                    <Loader size="sm" color="var(--app-accent-primary)" />
                  ) : (
                    <TbFileCheck size={18} className={classes.sectionIcon} />
                  )}
                </Group>
                <UploadArea onDrop={handleDrop} loading={uploading} />
              </Stack>
            </Paper>

            <Paper className={classes.libraryPanel} radius="xl">
              <Stack gap="md">
                <Group justify="space-between" align="center">
                  <div>
                    <Title order={3} className={classes.sectionTitle}>
                      Library documents
                    </Title>
                    <Text className={classes.sectionCopy}>
                      Review status, remove outdated material, and monitor
                      processing health.
                    </Text>
                  </div>
                  {loading ? (
                    <Loader size="sm" color="var(--app-accent-primary)" />
                  ) : null}
                </Group>

                <DocumentTable
                  documents={documents}
                  onDeleteClick={(doc) => {
                    setDocumentToDelete(doc);
                    setDeleteModalOpen(true);
                  }}
                />
              </Stack>
            </Paper>
          </SimpleGrid>
        </Stack>
      </Container>

      <Modal
        opened={deleteModalOpen}
        onClose={() => !isDeleting && setDeleteModalOpen(false)}
        title="Remove document"
        centered
        overlayProps={{ backgroundOpacity: 0.45, blur: 6 }}
      >
        <Text size="sm" mb="xl">
          Remove <strong>{documentToDelete?.filename}</strong> from the library?
          This will queue deletion from storage and the vector index.
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
            Delete document
          </Button>
        </Group>
      </Modal>
    </div>
  );
}
