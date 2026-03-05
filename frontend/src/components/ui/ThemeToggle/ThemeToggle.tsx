import { ActionIcon, Tooltip, useMantineColorScheme, useComputedColorScheme } from '@mantine/core';
import { TbSun, TbMoon } from 'react-icons/tb';

export default function ThemeToggle() {
    const { setColorScheme } = useMantineColorScheme();
    const computedColorScheme = useComputedColorScheme('light');

    const toggleColorScheme = () => {
        const newScheme = computedColorScheme === 'dark' ? 'light' : 'dark';
        setColorScheme(newScheme);
        localStorage.setItem('mantine-color-scheme', newScheme);
    };

    return (
        <Tooltip label={computedColorScheme === 'dark' ? 'Light mode' : 'Dark mode'}>
            <ActionIcon
                onClick={toggleColorScheme}
                variant="subtle"
                size="lg"
                radius="xl"
                aria-label="Toggle color scheme"
                style={{
                    transition: 'transform 0.2s ease',
                }}
            >
                {computedColorScheme === 'dark' ? (
                    <TbSun size={20} />
                ) : (
                    <TbMoon size={20} />
                )}
            </ActionIcon>
        </Tooltip>
    );
}
