export interface User {
  email: string;
  name?: string;
  given_name?: string;
  family_name?: string;
  roles: string[];
  groups: string[];
  sub: string;
}

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface AuthTokens {
  token_type: string;
  expires_in: number;
  role: string;
}

export interface LoginResponse {
  message: string;
  user: User;
  expires_in: number;
}

export interface AuthState {
  user: User | null;
  roles: string[];
  groups: string[];
  isAuthenticated: boolean;
  error: string | null;
  isInitialLoading: boolean;
  isInitialized: boolean;
}
