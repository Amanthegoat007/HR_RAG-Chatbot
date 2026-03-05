import { v4 as uuidv4 } from 'uuid';
 
/**
 * Generates a unique v4 UUID.
 *
 * In secure contexts (HTTPS), browsers provide `crypto.randomUUID()`.
 * This utility uses the `uuid` library to provide a consistent and reliable
 * UUID generation method across both secure and non-secure contexts.
 */
export const generateUUID = (): string => {
    return uuidv4();
};