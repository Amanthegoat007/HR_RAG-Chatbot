import { ActionIcon, TextInput } from '@mantine/core';
import { TbX } from 'react-icons/tb';

interface ChatSearchProps {
    query: string;
    onQueryChange: (query: string) => void;
    onClear: () => void;
}

export const ChatSearch = ({ query, onQueryChange, onClear }: ChatSearchProps) => {
    return (
        <TextInput
            placeholder="Search chats..."
            size="xs"
            variant="filled"
            autoFocus
            value={query}
            onChange={(e) => onQueryChange(e.currentTarget.value)}
            rightSection={
                <ActionIcon
                    size="xs"
                    variant="subtle"
                    color="gray"
                    onClick={onClear}
                >
                    <TbX size={14} />
                </ActionIcon>
            }
            styles={{
            root: { padding: '0 8px' },
            input: {
                border: 'none',
                borderBottom: '1px solid var(--mantine-color-gray-4)',
                borderRadius: 0,
                backgroundColor: 'transparent',

                '&:focus': {
                borderBottom: '2px solid var(--mantine-color-brand-filled)',
                },
            },
            }}
        />
    );
};
