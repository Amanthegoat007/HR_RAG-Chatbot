import { createTheme, MantineThemeOverride, MantineColorsTuple } from '@mantine/core';
import { designTokens } from './designTokens';

export const theme: MantineThemeOverride = createTheme({
    primaryColor: 'brand',
    primaryShade: 5,
    colors: {
        brand: designTokens.colors.brand as any as MantineColorsTuple,
        dark: designTokens.colors.dark as any as MantineColorsTuple,
        success: designTokens.colors.success as any as MantineColorsTuple,
        warning: designTokens.colors.warning as any as MantineColorsTuple,
        error: designTokens.colors.error as any as MantineColorsTuple,
        info: designTokens.colors.info as any as MantineColorsTuple,
    },
    fontFamily: 'Inter, sans-serif',
    headings: {
        fontFamily: 'Inter, sans-serif',
        fontWeight: '700',
    },
    defaultRadius: 'md',

    // Dark mode specific colors
    black: '#1a1b1e',
    white: '#ffffff',

    components: {
        Button: {
            defaultProps: {
                radius: 'xl',
            },
            styles: {
                root: {
                    transition: `all ${designTokens.animations.medium}`,
                    '&:active': {
                        transform: 'scale(0.98)',
                    },
                },
            },
        },

        TextInput: {
            defaultProps: {
                radius: 'md',
                size: 'md',
            },
        },

        PasswordInput: {
            defaultProps: {
                radius: 'md',
                size: 'md',
            },
        },

        Textarea: {
            defaultProps: {
                radius: 'md',
            },
        },

        Paper: {
            defaultProps: {
                radius: 'lg',
            },
            styles: {
                root: {
                    transition: `all ${designTokens.animations.medium}`,
                },
            },
        },

        Modal: {
            defaultProps: {
                radius: 'lg',
            },
        },

        Card: {
            defaultProps: {
                radius: 'lg',
            },
        },

        ActionIcon: {
            styles: {
                root: {
                    transition: `all ${designTokens.animations.fast}`,
                },
            },
        },

        Tooltip: {
            defaultProps: {
                radius: 'md',
            },
        },
    },
});
