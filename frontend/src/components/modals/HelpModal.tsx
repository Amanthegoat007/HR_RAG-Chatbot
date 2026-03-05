import { Modal, Text, Stack, Box, Group, ActionIcon } from '@mantine/core';
import { TbBook, TbPointer, TbExternalLink } from 'react-icons/tb';

interface HelpModalProps {
    opened: boolean;
    onClose: () => void;
}

export default function HelpModal({ opened, onClose }: HelpModalProps) {
    return (
        <Modal
            opened={opened}
            onClose={onClose}
            title={<Text fw={700} size="lg">Help & Support</Text>}
            centered
            size="md"
            radius="lg"
            padding="xl"
        >
            <Stack gap="md">
                <Box
                    p="md"
                    style={{
                        cursor: 'pointer',
                        borderRadius: 12,
                        border: '1px solid var(--mantine-color-default-border)',
                        transition: '200ms ease'
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--mantine-color-brand-light)'}
                    onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                    onClick={() => window.open('#', '_blank')}
                >
                    <Group justify="space-between">
                        <Group gap="md">
                            <ActionIcon variant="light" color="lime" size="lg" radius="md">
                                <TbPointer size={22} />
                            </ActionIcon>
                            <Box>
                                <Text fw={600}>Interactive Tutorial</Text>
                                <Text size="xs" c="dimmed">Learn the basics and advanced features</Text>
                            </Box>
                        </Group>
                        <TbExternalLink size={18} color="var(--mantine-color-dimmed)" />
                    </Group>
                </Box>

                <Box
                    p="md"
                    style={{
                        cursor: 'pointer',
                        borderRadius: 12,
                        border: '1px solid var(--mantine-color-default-border)',
                        transition: '200ms ease'
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--mantine-color-brand-light)'}
                    onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                    onClick={() => window.open('#', '_blank')}
                >
                    <Group justify="space-between">
                        <Group gap="md">
                            <ActionIcon variant="light" color="blue" size="lg" radius="md">
                                <TbBook size={22} />
                            </ActionIcon>
                            <Box>
                                <Text fw={600}>Feature Documentation</Text>
                                <Text size="xs" c="dimmed">Detailed guides and real-world use cases</Text>
                            </Box>
                        </Group>
                        <TbExternalLink size={18} color="var(--mantine-color-dimmed)" />
                    </Group>
                </Box>

                <Box
                    mt="md"
                    p="md"
                    style={{
                        backgroundColor: 'transparent',
                        borderRadius: 12,
                        textAlign: 'center'
                    }}
                >
                    <Text size="sm" fw={500} mb={4}>Need more help?</Text>
                    <Text size="xs" color="dimmed">Contact our support team for personalized assistance.</Text>
                    <Text size="xs" fw={700} color="lime" mt={8} style={{ cursor: 'pointer' }}>support@chatbot.ai</Text>
                </Box>
            </Stack>
        </Modal>
    );
}
