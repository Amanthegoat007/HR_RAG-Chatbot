import { Group, Text, Box, useMantineTheme } from "@mantine/core";
import { TbUpload } from "react-icons/tb";
import { Dropzone } from "@mantine/dropzone";

interface UploadAreaProps {
  onDrop: (files: File[]) => void;
  loading?: boolean;
}

export function UploadArea({ onDrop, loading }: UploadAreaProps) {
  const theme = useMantineTheme();

  return (
    <Dropzone
      onDrop={onDrop}
      maxSize={10 * 1024 ** 2}
      accept={[
        "application/pdf",
        "text/plain",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
      ]}
      loading={loading}
      style={{
        border: `2px dashed var(--app-border)`,
        backgroundColor: "var(--app-surface)",
        borderRadius: theme.radius.md,
      }}
    >
      <Group
        justify="center"
        gap="xl"
        mih={120}
        style={{ pointerEvents: "none" }}
      >
        <Dropzone.Accept>
          <TbUpload
            size={40}
            color={theme.colors[theme.primaryColor][6]}
            stroke="1.5"
          />
        </Dropzone.Accept>
        <Dropzone.Reject>
          <TbUpload size={40} color={theme.colors.red[6]} stroke="1.5" />
        </Dropzone.Reject>
        <Dropzone.Idle>
          <TbUpload
            size={40}
            color="var(--mantine-color-dimmed)"
            stroke="1.5"
          />
        </Dropzone.Idle>

        <div>
          <Text size="lg" inline>
            Drag documents here or click to select files
          </Text>
          <Text size="sm" c="dimmed" inline mt={7}>
            Attach organizational files like PDF, TXT, DOCX. Files should not
            exceed 10MB.
          </Text>
        </div>
      </Group>
    </Dropzone>
  );
}
