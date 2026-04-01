import { Group, Text, Stack } from "@mantine/core";
import { Dropzone } from "@mantine/dropzone";
import { TbUpload, TbFileCheck, TbAlertCircle } from "react-icons/tb";

import classes from "./UploadArea.module.css";

interface UploadAreaProps {
  onDrop: (files: File[]) => void;
  loading?: boolean;
}

const FLOW_STEPS = ["Upload", "Processing", "Ready"];

export function UploadArea({ onDrop, loading }: UploadAreaProps) {
  return (
    <Dropzone
      onDrop={onDrop}
      maxSize={10 * 1024 ** 2}
      accept={[
        "application/pdf",
        "text/plain",
        "text/markdown",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "image/png",
        "image/jpeg",
        "image/webp",
      ]}
      loading={loading}
      className={classes.dropzone}
    >
      <Stack gap="lg" className={classes.inner}>
        <Group gap="md" wrap="nowrap" className={classes.copyGroup}>
          <div className={classes.iconShell}>
            <Dropzone.Accept>
              <TbFileCheck size={26} />
            </Dropzone.Accept>
            <Dropzone.Reject>
              <TbAlertCircle size={26} />
            </Dropzone.Reject>
            <Dropzone.Idle>
              <TbUpload size={26} />
            </Dropzone.Idle>
          </div>
          <Stack gap={6} className={classes.copyBlock}>
            <Text fw={600} className={classes.title}>
              Drag documents here or browse to upload
            </Text>
            <Text size="sm" className={classes.copy}>
              Supports PDF, DOCX, XLSX, PPTX, TXT, Markdown, and image-based
              documents up to 10MB each.
            </Text>
          </Stack>
        </Group>

        <div className={classes.metaSection}>
          <Text size="xs" fw={600} className={classes.metaLabel}>
            Intake flow
          </Text>
          <div className={classes.metaSteps}>
            {FLOW_STEPS.map((step) => (
              <span key={step} className={classes.metaStep}>
                {step}
              </span>
            ))}
          </div>
        </div>
      </Stack>
    </Dropzone>
  );
}
