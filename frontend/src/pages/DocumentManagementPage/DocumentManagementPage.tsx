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
  SegmentedControl,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { TbAlertCircle, TbDatabase, TbFileCheck, TbLoader2 } from "react-icons/tb";

import {
  documentService,
  type DocumentInfo,
  type DocumentScope,
  type DocumentStatus,
} from "@/services/documentService";
import { DocumentTable } from "./DocumentTable";
import { UploadArea } from "./UploadArea";
import classes from "./DocumentManagementPage.module.css";

const ACTIVE_PIPELINE_STATUSES: DocumentStatus[] = [
  "pending",
  "normalizing",
  "processing",
  "embedding",
];

const isActivePipelineStatus = (status: DocumentStatus) =>
  ACTIVE_PIPELINE_STATUSES.includes(status);

export default function DocumentManagementPage() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [activeScope, setActiveScope] = useState<DocumentScope>("library");
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [activeUploadCount, setActiveUploadCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [documentToDelete, setDocumentToDelete] = useState<DocumentInfo | null>(
    null,
  );
  const [isDeleting, setIsDeleting] = useState(false);

  const fetchDocuments = async (
    scope: DocumentScope,
    showLoading = true,
  ) => {
    try {
      if (showLoading) setLoading(true);
      const data = await documentService.getDocuments(scope);
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
    void fetchDocuments(activeScope);
  }, [activeScope]);

  const hasInProgressDocuments = useMemo(
    () =>
      activeUploadCount > 0 ||
      documents.some((doc) => isActivePipelineStatus(doc.status)),
    [activeUploadCount, documents],
  );

  useEffect(() => {
    if (!hasInProgressDocuments) {
      return;
    }

    const interval = window.setInterval(() => {
      void fetchDocuments(activeScope, false);
    }, 2500);

    return () => window.clearInterval(interval);
  }, [activeScope, hasInProgressDocuments]);

  const handleDrop = async (files: File[]) => {
    if (files.length === 0) return;

    setUploading(true);
    setActiveUploadCount((count) => count + files.length);
    setError(null);

    let pendingClientUploads = files.length;
    try {
      for (const file of files) {
        await documentService.uploadDocument(file, { scope: "library" });
        pendingClientUploads -= 1;
        setActiveUploadCount((count) => Math.max(0, count - 1));
        if (activeScope === "library") {
          void fetchDocuments("library", false);
        }
      }
      if (activeScope !== "library") {
        setActiveScope("library");
      } else {
        await fetchDocuments("library", false);
      }
    } catch (err) {
      console.error("Upload failed", err);
      setError("Failed to upload document(s).");
    } finally {
      if (pendingClientUploads > 0) {
        setActiveUploadCount((count) =>
          Math.max(0, count - pendingClientUploads),
        );
      }
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
      await fetchDocuments(activeScope, false);
    } catch (err) {
      console.error("Delete failed", err);
      setError("Failed to delete document.");
    } finally {
      setIsDeleting(false);
    }
  };

  const stats = useMemo(() => {
    const ready = documents.filter((doc) => doc.status === "ready").length;
    const processing =
      activeUploadCount +
      documents.filter((doc) => isActivePipelineStatus(doc.status)).length;
    const failed = documents.filter((doc) => doc.status === "failed").length;
    return { total: documents.length, ready, processing, failed };
  }, [activeUploadCount, documents]);

  const scopeLabel = activeScope === "library" ? "library" : "session";
  const totalLabel =
    activeScope === "library" ? "Total library docs" : "Total session docs";
  const readyHint =
    activeScope === "library"
      ? "Documents available to the assistant now."
      : "Session uploads available to the assistant now.";
  const processingHint =
    activeScope === "library"
      ? "Counts browser uploads plus jobs moving through normalization and indexing."
      : "Counts uploaded session files plus jobs moving through normalization and indexing.";
  const totalHint =
    activeScope === "library"
      ? "Includes ready, processing, and failed library documents."
      : "Includes ready, processing, and failed session uploads.";
  const showLibraryActivity = loading || hasInProgressDocuments;
  const documentPanelCopy =
    activeScope === "library"
      ? "Review permanent library uploads, remove outdated material, and monitor processing health."
      : "Review temporary conversation attachments that were uploaded from chat sessions.";

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
              <Text className={classes.statHint}>{readyHint}</Text>
            </Paper>
            <Paper className={classes.statCard} radius="xl">
              <Text className={classes.statLabel}>Processing</Text>
              <div className={classes.metricRow}>
                <Text className={classes.statValue}>{stats.processing}</Text>
                {stats.processing > 0 ? (
                  <Loader
                    size="sm"
                    color="var(--app-accent-primary)"
                    className={classes.metricStatus}
                  />
                ) : (
                  <TbLoader2
                    className={`${classes.statIconMuted} ${classes.metricStatus}`}
                    size={18}
                  />
                )}
              </div>
              <Text className={classes.statHint}>{processingHint}</Text>
            </Paper>
            <Paper className={classes.statCard} radius="xl">
              <Text className={classes.statLabel}>{totalLabel}</Text>
              <Text className={classes.statValue}>{stats.total}</Text>
              <Text className={classes.statHint}>{totalHint}</Text>
            </Paper>
          </SimpleGrid>

          <SimpleGrid cols={{ base: 1, lg: 3 }} spacing="lg">
            <Paper className={classes.uploadPanel} radius="xl">
              <Stack gap="md">
                <div className={classes.sectionHeader}>
                  <div className={classes.sectionHeaderCopy}>
                    <Title order={3} className={classes.sectionTitle}>
                      Upload documents
                    </Title>
                    <Text className={classes.sectionCopy}>
                      Add HR policies, benefits guides, and utility-space
                      reference documents to the shared library.
                    </Text>
                  </div>
                  {uploading ? (
                    <Loader
                      size="sm"
                      color="var(--app-accent-primary)"
                      className={classes.sectionHeaderStatus}
                    />
                  ) : (
                    <TbFileCheck
                      size={18}
                      className={`${classes.sectionIcon} ${classes.sectionHeaderStatus}`}
                    />
                  )}
                </div>
                <UploadArea onDrop={handleDrop} loading={uploading} />
              </Stack>
            </Paper>

            <Paper className={classes.libraryPanel} radius="xl">
              <Stack gap="md" className={classes.libraryPanelBody}>
                <div className={classes.sectionHeader}>
                  <div className={classes.sectionHeaderCopy}>
                    <Title order={3} className={classes.sectionTitle}>
                      {activeScope === "library"
                        ? "Library documents"
                        : "Session uploads"}
                    </Title>
                    <Text className={classes.sectionCopy}>
                      {documentPanelCopy}
                    </Text>
                  </div>
                  {showLibraryActivity ? (
                    <TbLoader2
                      size={18}
                      className={`${classes.sectionIcon} ${classes.sectionHeaderStatus} ${classes.spinningStatus}`}
                      aria-label={`Refreshing ${scopeLabel} documents`}
                    />
                  ) : null}
                </div>

                <SegmentedControl
                  value={activeScope}
                  onChange={(value) => setActiveScope(value as DocumentScope)}
                  data={[
                    { label: "Permanent uploads", value: "library" },
                    { label: "Session uploads", value: "session" },
                  ]}
                  classNames={{
                    root: classes.scopeControl,
                    indicator: classes.scopeControlIndicator,
                    label: classes.scopeControlLabel,
                  }}
                />
                <div className={classes.libraryListViewport}>
                  <DocumentTable
                    documents={documents}
                    scope={activeScope}
                    onDeleteClick={(doc) => {
                      setDocumentToDelete(doc);
                      setDeleteModalOpen(true);
                    }}
                  />
                </div>
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
