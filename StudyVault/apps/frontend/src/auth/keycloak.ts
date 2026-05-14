import Keycloak from "keycloak-js";

const STUDYVAULT_ADMIN_ROLE = "studyvault_admin";
const keycloakBaseUrl = import.meta.env.VITE_KEYCLOAK_URL ?? window.location.origin;
const keycloakRealm = import.meta.env.VITE_KEYCLOAK_REALM ?? "studyvault";
const silentCheckSsoRedirectUri = `${window.location.origin}/silent-check-sso.html`;

const keycloak = new Keycloak({
  url: keycloakBaseUrl,
  realm: keycloakRealm,
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "studyvault-frontend",
});

type KeycloakTokenPayload = {
  email?: string;
  preferred_username?: string;
  name?: string;
  given_name?: string;
  family_name?: string;
  realm_access?: {
    roles?: string[];
  };
  sub?: string;
};

export type AuthProfile = {
  displayName: string;
  email: string | null;
  username: string | null;
  avatarLabel: string;
  manageAccountUrl: string;
  changePasswordUrl: string;
};

function buildKeycloakAccountUrl(hash = ""): string {
  const baseUrl = new URL(`/realms/${keycloakRealm}/account/`, keycloakBaseUrl).toString();
  if (!hash) {
    return baseUrl;
  }
  return `${baseUrl}${hash}`;
}

function buildAuthProfile(): AuthProfile {
  if (!keycloak.tokenParsed) {
    return {
      displayName: "Anonymous",
      email: null,
      username: null,
      avatarLabel: "A",
      manageAccountUrl: buildKeycloakAccountUrl(),
      changePasswordUrl: buildKeycloakAccountUrl("#/security/signingin"),
    };
  }

  const parsed = keycloak.tokenParsed as KeycloakTokenPayload;
  const formattedName = [parsed.given_name, parsed.family_name].filter(Boolean).join(" ").trim();
  const displayName =
    parsed.preferred_username
    || parsed.name
    || formattedName
    || parsed.email
    || parsed.sub
    || "Authenticated user";

  return {
    displayName,
    email: parsed.email ?? null,
    username: parsed.preferred_username ?? parsed.sub ?? null,
    avatarLabel: displayName.slice(0, 1).toUpperCase() || "A",
    manageAccountUrl: buildKeycloakAccountUrl(),
    changePasswordUrl: buildKeycloakAccountUrl("#/security/signingin"),
  };
}

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

export function getAuthProfile(): AuthProfile {
  return buildAuthProfile();
}

export async function refreshAuthProfile(): Promise<AuthProfile> {
  if (keycloak.authenticated) {
    try {
      await keycloak.updateToken(-1);
    } catch {
      // Keep the existing parsed token data so the UI can gracefully recover.
    }
  }
  return buildAuthProfile();
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
