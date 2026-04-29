export type PublicTestSession = {
    displayName: string;
    email: string;
};

export type PublicTestProfile = PublicTestSession & {
    createdAt: string;
    updatedAt: string;
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

type VerificationStartResult =
    | {
          ok: true;
          email: string;
          expiresInSeconds: number;
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
const FREE_BOT_PASSWORD_MIN_LENGTH = 8;

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

const parseProfile = (payload: unknown): PublicTestProfile | null => {
    if (
        !payload ||
        typeof payload !== "object" ||
        typeof (payload as { displayName?: unknown }).displayName !== "string" ||
        typeof (payload as { email?: unknown }).email !== "string" ||
        typeof (payload as { createdAt?: unknown }).createdAt !== "string" ||
        typeof (payload as { updatedAt?: unknown }).updatedAt !== "string"
    ) {
        return null;
    }

    return {
        displayName: (payload as { displayName: string }).displayName.trim(),
        email: normalizeEmail((payload as { email: string }).email),
        createdAt: (payload as { createdAt: string }).createdAt,
        updatedAt: (payload as { updatedAt: string }).updatedAt
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
        throw new Error(`nerilio session request failed: ${response.status}`);
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

    const response = await fetch("/free-auth/session", {
        method: "GET",
        credentials: "include"
    });
    return await readSessionResponse(response);
};

export const isAuthenticated = async () => (await getCurrentSession()) !== null;

export const logout = async () => {
    cachedSession = null;
    await fetch("/free-auth/logout", {
        method: "POST",
        credentials: "include"
    }).catch(() => undefined);
};

export const getCurrentProfile = async (): Promise<PublicTestProfile> => {
    const response = await fetch("/free-auth/profile", {
        method: "GET",
        credentials: "include"
    });

    if (!response.ok) {
        throw new Error(`nerilio profile request failed: ${response.status}`);
    }

    const payload = (await response.json()) as { profile?: unknown };
    const profile = parseProfile(payload.profile);
    if (!profile) {
        throw new Error("nerilio profile payload was invalid");
    }

    return profile;
};

export const signUp = async ({ displayName, email, password, confirmPassword }: SignUpInput): Promise<VerificationStartResult> => {
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
    if (password.length < FREE_BOT_PASSWORD_MIN_LENGTH) {
        return { ok: false, errorKey: "authErrors.passwordTooShort" };
    }

    if (!confirmPassword) {
        return { ok: false, errorKey: "authErrors.confirmPasswordRequired" };
    }

    if (password !== confirmPassword) {
        return { ok: false, errorKey: "authErrors.passwordMismatch" };
    }

    const response = await fetch("/free-auth/signup", {
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

    const payload = (await response.json()) as {
        verificationRequired?: boolean;
        email?: string;
        expiresInSeconds?: number;
    };
    if (!payload.verificationRequired || typeof payload.email !== "string") {
        return { ok: false, errorKey: "authErrors.unexpected" };
    }

    return {
        ok: true,
        email: normalizeEmail(payload.email),
        expiresInSeconds: typeof payload.expiresInSeconds === "number" ? payload.expiresInSeconds : 0
    };
};

export const verifySignUp = async (email: string, verificationCode: string): Promise<AuthResult> => {
    const normalizedEmail = normalizeEmail(email);
    if (!normalizedEmail) {
        return { ok: false, errorKey: "authErrors.emailRequired" };
    }
    if (!verificationCode.trim()) {
        return { ok: false, errorKey: "authErrors.verificationCodeRequired" };
    }

    const response = await fetch("/free-auth/signup/verify", {
        method: "POST",
        credentials: "include",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            email: normalizedEmail,
            verificationCode: verificationCode.trim()
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

export const resendSignUpCode = async (email: string): Promise<VerificationStartResult> => {
    const normalizedEmail = normalizeEmail(email);
    if (!normalizedEmail) {
        return { ok: false, errorKey: "authErrors.emailRequired" };
    }

    const response = await fetch("/free-auth/signup/resend", {
        method: "POST",
        credentials: "include",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            email: normalizedEmail
        })
    });

    if (!response.ok) {
        return {
            ok: false,
            errorKey: await readErrorKey(response, "authErrors.unexpected")
        };
    }

    const payload = (await response.json()) as {
        verificationRequired?: boolean;
        email?: string;
        expiresInSeconds?: number;
    };
    if (!payload.verificationRequired || typeof payload.email !== "string") {
        return { ok: false, errorKey: "authErrors.unexpected" };
    }

    return {
        ok: true,
        email: normalizeEmail(payload.email),
        expiresInSeconds: typeof payload.expiresInSeconds === "number" ? payload.expiresInSeconds : 0
    };
};

export const requestPasswordReset = async (email: string): Promise<VerificationStartResult> => {
    const normalizedEmail = normalizeEmail(email);
    if (!normalizedEmail) {
        return { ok: false, errorKey: "authErrors.emailRequired" };
    }
    if (!isEmailValid(normalizedEmail)) {
        return { ok: false, errorKey: "authErrors.invalidEmail" };
    }

    const response = await fetch("/free-auth/password-reset", {
        method: "POST",
        credentials: "include",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            email: normalizedEmail
        })
    });

    if (!response.ok) {
        return {
            ok: false,
            errorKey: await readErrorKey(response, "authErrors.unexpected")
        };
    }

    const payload = (await response.json()) as {
        verificationRequired?: boolean;
        email?: string;
        expiresInSeconds?: number;
    };
    if (!payload.verificationRequired || typeof payload.email !== "string") {
        return { ok: false, errorKey: "authErrors.unexpected" };
    }

    return {
        ok: true,
        email: normalizeEmail(payload.email),
        expiresInSeconds: typeof payload.expiresInSeconds === "number" ? payload.expiresInSeconds : 0
    };
};

export const resendPasswordResetCode = async (email: string): Promise<VerificationStartResult> => {
    const normalizedEmail = normalizeEmail(email);
    if (!normalizedEmail) {
        return { ok: false, errorKey: "authErrors.emailRequired" };
    }

    const response = await fetch("/free-auth/password-reset/resend", {
        method: "POST",
        credentials: "include",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            email: normalizedEmail
        })
    });

    if (!response.ok) {
        return {
            ok: false,
            errorKey: await readErrorKey(response, "authErrors.unexpected")
        };
    }

    const payload = (await response.json()) as {
        verificationRequired?: boolean;
        email?: string;
        expiresInSeconds?: number;
    };
    if (!payload.verificationRequired || typeof payload.email !== "string") {
        return { ok: false, errorKey: "authErrors.unexpected" };
    }

    return {
        ok: true,
        email: normalizeEmail(payload.email),
        expiresInSeconds: typeof payload.expiresInSeconds === "number" ? payload.expiresInSeconds : 0
    };
};

export const verifyPasswordReset = async (
    email: string,
    verificationCode: string,
    password: string,
    confirmPassword: string
): Promise<AuthResult> => {
    const normalizedEmail = normalizeEmail(email);
    if (!normalizedEmail) {
        return { ok: false, errorKey: "authErrors.emailRequired" };
    }
    if (!verificationCode.trim()) {
        return { ok: false, errorKey: "authErrors.verificationCodeRequired" };
    }
    if (!password) {
        return { ok: false, errorKey: "authErrors.passwordRequired" };
    }
    if (password.length < FREE_BOT_PASSWORD_MIN_LENGTH) {
        return { ok: false, errorKey: "authErrors.passwordTooShort" };
    }
    if (!confirmPassword) {
        return { ok: false, errorKey: "authErrors.confirmPasswordRequired" };
    }
    if (password !== confirmPassword) {
        return { ok: false, errorKey: "authErrors.passwordMismatch" };
    }

    const response = await fetch("/free-auth/password-reset/verify", {
        method: "POST",
        credentials: "include",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            email: normalizedEmail,
            verificationCode: verificationCode.trim(),
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

    const response = await fetch("/free-auth/login", {
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

