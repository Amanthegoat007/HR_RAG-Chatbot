import { Modal, Button, Text, Group, Stack } from '@mantine/core';
import { TbAlertTriangle } from 'react-icons/tb';

interface DeleteAllConversationsModalProps {
    opened: boolean;
    onClose: () => void;
    onConfirm: () => void;
    loading?: boolean;
}

export default function DeleteAllConversationsModal({
    opened,
    onClose,
    onConfirm,
    loading = false,
}: DeleteAllConversationsModalProps) {
    return (
        <Modal
            opened={opened}
            onClose={onClose}
            title="Delete all chats"
            centered
            radius="md"
            withCloseButton={!loading}
            closeOnClickOutside={!loading}
            closeOnEscape={!loading}
        >
            <Stack gap="md">
                <Group align="flex-start" wrap="nowrap">
                    <TbAlertTriangle size={32} color="var(--mantine-color-red-6)" style={{ flexShrink: 0 }} />
                    <Stack gap={4}>
                        <Text fw={500}>Are you absolutely sure?</Text>
                        <Text size="sm" c="dimmed">
                            This will permanently delete all your conversations and messages. This action cannot be undone.
                        </Text>
                    </Stack>
                </Group>

                <Group justify="flex-end" mt="md">
                    <Button variant="default" onClick={onClose} disabled={loading}>
                        Cancel
                    </Button>
                    <Button color="red" onClick={onConfirm} loading={loading}>
                        Delete all chats
                    </Button>
                </Group>
            </Stack>
        </Modal>
    );
}
