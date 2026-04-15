import Keycloak from "keycloak-js";

const STUDYVAULT_ADMIN_ROLE = "studyvault_admin";
const keycloakBaseUrl = import.meta.env.VITE_KEYCLOAK_URL ?? window.location.origin;
const silentCheckSsoRedirectUri = `${window.location.origin}/silent-check-sso.html`;

const keycloak = new Keycloak({
  url: keycloakBaseUrl,
  realm: import.meta.env.VITE_KEYCLOAK_REALM ?? "studyvault",
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "studyvault-frontend",
});

type KeycloakTokenPayload = {
  email?: string;
  preferred_username?: string;
  realm_access?: {
    roles?: string[];
  };
  sub?: string;
};

export async function initializeAuth(): Promise<boolean> {
  return keycloak.init({
    onLoad: "check-sso",
    pkceMethod: "S256",
    checkLoginIframe: false,
    silentCheckSsoRedirectUri,
  });
}

export function getAccessToken(): Promise<string | undefined> {
  if (!keycloak.authenticated) {
    return Promise.resolve(undefined);
  }

  return keycloak
    .updateToken(60)
    .then(() => keycloak.token ?? undefined)
    .catch(() => keycloak.token ?? undefined);
}

export function login(): Promise<void> {
  return keycloak.login({
    redirectUri: window.location.origin,
  });
}

export function register(): Promise<void> {
  return keycloak.register({
    redirectUri: window.location.origin,
  });
}

export function logout(): Promise<void> {
  return keycloak.logout({
    redirectUri: window.location.origin,
  });
}

export function getProfileSummary(): string {
  if (!keycloak.tokenParsed) {
    return "Anonymous";
  }
  const parsed = keycloak.tokenParsed as KeycloakTokenPayload;
  return parsed.preferred_username ?? parsed.email ?? parsed.sub ?? "Authenticated user";
}

export function isAdmin(): boolean {
  if (!keycloak.tokenParsed) {
    return false;
  }
  const parsed = keycloak.tokenParsed as KeycloakTokenPayload;
  return Boolean(parsed.realm_access?.roles?.includes(STUDYVAULT_ADMIN_ROLE));
}

export function isAuthenticated(): boolean {
  return Boolean(keycloak.authenticated);
}
