export type PublicTestSession = {
    displayName: string;
    email: string;
};

type AuthResult =
    | {
          ok: true;
          session: PublicTestSession;
      }
    | {
          ok: false;
          errorKey: string;
      };

type SignUpInput = {
    displayName: string;
    email: string;
    password: string;
    confirmPassword: string;
};

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const normalizeEmail = (email: string) => email.trim().toLowerCase();

const isEmailValid = (email: string) => emailPattern.test(normalizeEmail(email));

let cachedSession: PublicTestSession | null | undefined = undefined;

const parseSession = (payload: unknown): PublicTestSession | null => {
    if (
        !payload ||
        typeof payload !== "object" ||
        typeof (payload as { displayName?: unknown }).displayName !== "string" ||
        typeof (payload as { email?: unknown }).email !== "string"
    ) {
        return null;
    }

    return {
        displayName: (payload as { displayName: string }).displayName.trim(),
        email: normalizeEmail((payload as { email: string }).email)
    };
};

const readErrorKey = async (response: Response, fallbackErrorKey: string) => {
    const payload = (await response.json().catch(() => null)) as { errorKey?: string } | null;
    return payload?.errorKey ?? fallbackErrorKey;
};

const readSessionResponse = async (response: Response): Promise<PublicTestSession | null> => {
    if (response.status === 401) {
        cachedSession = null;
        return null;
    }

    if (!response.ok) {
        throw new Error(`Public Test session request failed: ${response.status}`);
    }

    const payload = (await response.json()) as { session?: unknown };
    const session = parseSession(payload.session);
    cachedSession = session;
    return session;
};

export const getCurrentSession = async (options?: { forceRefresh?: boolean }): Promise<PublicTestSession | null> => {
    if (!options?.forceRefresh && cachedSession !== undefined) {
        return cachedSession;
    }

    const response = await fetch("/public-test-auth/session", {
        method: "GET",
        credentials: "include"
    });
    return await readSessionResponse(response);
};

export const isAuthenticated = async () => (await getCurrentSession()) !== null;

export const logout = async () => {
    cachedSession = null;
    await fetch("/public-test-auth/logout", {
        method: "POST",
        credentials: "include"
    }).catch(() => undefined);
};

export const signUp = async ({ displayName, email, password, confirmPassword }: SignUpInput): Promise<AuthResult> => {
    const normalizedDisplayName = displayName.trim();
    const normalizedEmail = normalizeEmail(email);

    if (!normalizedDisplayName) {
        return { ok: false, errorKey: "authErrors.displayNameRequired" };
    }

    if (!normalizedEmail) {
        return { ok: false, errorKey: "authErrors.emailRequired" };
    }

    if (!isEmailValid(normalizedEmail)) {
        return { ok: false, errorKey: "authErrors.invalidEmail" };
    }

    if (!password) {
        return { ok: false, errorKey: "authErrors.passwordRequired" };
    }

    if (!confirmPassword) {
        return { ok: false, errorKey: "authErrors.confirmPasswordRequired" };
    }

    if (password !== confirmPassword) {
        return { ok: false, errorKey: "authErrors.passwordMismatch" };
    }

    const response = await fetch("/public-test-auth/signup", {
        method: "POST",
        credentials: "include",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            displayName: normalizedDisplayName,
            email: normalizedEmail,
            password,
            confirmPassword
        })
    });

    if (!response.ok) {
        return {
            ok: false,
            errorKey: await readErrorKey(response, "authErrors.unexpected")
        };
    }

    const payload = (await response.json()) as { session?: unknown };
    const session = parseSession(payload.session);
    if (!session) {
        return { ok: false, errorKey: "authErrors.unexpected" };
    }

    cachedSession = session;
    return { ok: true, session };
};

export const login = async (email: string, password: string): Promise<AuthResult> => {
    const normalizedEmail = normalizeEmail(email);
    if (!normalizedEmail || !password) {
        return { ok: false, errorKey: "authErrors.invalidCredentials" };
    }

    const response = await fetch("/public-test-auth/login", {
        method: "POST",
        credentials: "include",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            email: normalizedEmail,
            password
        })
    });

    if (!response.ok) {
        return {
            ok: false,
            errorKey: await readErrorKey(response, "authErrors.invalidCredentials")
        };
    }

    const payload = (await response.json()) as { session?: unknown };
    const session = parseSession(payload.session);
    if (!session) {
        return { ok: false, errorKey: "authErrors.unexpected" };
    }

    cachedSession = session;
    return { ok: true, session };
};

export const validatePublicTestEmail = (email: string) => isEmailValid(email);
