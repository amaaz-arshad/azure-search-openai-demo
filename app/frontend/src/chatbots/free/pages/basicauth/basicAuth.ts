// Free Bot access is a 30-day window owned by the backend (core/freeauth.py). Every session and
// profile response carries the countdown so the UI never computes an expiry date itself.
export type FreeSession = {
    displayName: string;
    email: string;
    expiresAt: string;
    daysRemaining: number;
};

export type FreeProfile = FreeSession & {
    createdAt: string;
    updatedAt: string;
};

// Days of notice before access ends; mirrors the admin page's warning highlight.
export const FREE_EXPIRY_WARNING_DAYS = 7;

type AuthResult =
    | {
          ok: true;
          session: FreeSession;
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
    firstName: string;
    lastName: string;
    // The company name — the form labels this field "Firmenname" / "Company name" / "Bedrijfsnaam".
    displayName: string;
    email: string;
    password: string;
    confirmPassword: string;
};

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const FREE_BOT_PASSWORD_MIN_LENGTH = 8;

const normalizeEmail = (email: string) => email.trim().toLowerCase();

const isEmailValid = (email: string) => emailPattern.test(normalizeEmail(email));

let cachedSession: FreeSession | null | undefined = undefined;

// Tolerant on purpose: an older backend (or a cached response) without the expiry fields still
// yields a usable session, it just shows no countdown.
const parseExpiry = (payload: object) => ({
    expiresAt: typeof (payload as { expiresAt?: unknown }).expiresAt === "string" ? (payload as { expiresAt: string }).expiresAt : "",
    daysRemaining: typeof (payload as { daysRemaining?: unknown }).daysRemaining === "number" ? (payload as { daysRemaining: number }).daysRemaining : 0
});

const parseSession = (payload: unknown): FreeSession | null => {
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
        email: normalizeEmail((payload as { email: string }).email),
        ...parseExpiry(payload)
    };
};

const parseProfile = (payload: unknown): FreeProfile | null => {
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
        updatedAt: (payload as { updatedAt: string }).updatedAt,
        ...parseExpiry(payload)
    };
};

const readErrorKey = async (response: Response, fallbackErrorKey: string) => {
    const payload = (await response.json().catch(() => null)) as { errorKey?: string } | null;
    return payload?.errorKey ?? fallbackErrorKey;
};

const readSessionResponse = async (response: Response): Promise<FreeSession | null> => {
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

export const getCurrentSession = async (options?: { forceRefresh?: boolean }): Promise<FreeSession | null> => {
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

export const getCurrentProfile = async (): Promise<FreeProfile> => {
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

export const signUp = async ({
    firstName,
    lastName,
    displayName,
    email,
    password,
    confirmPassword
}: SignUpInput): Promise<VerificationStartResult> => {
    const normalizedFirstName = firstName.trim();
    const normalizedLastName = lastName.trim();
    const normalizedDisplayName = displayName.trim();
    const normalizedEmail = normalizeEmail(email);

    // Same order as the backend's start_signup validation, so both ends flag the topmost empty field.
    if (!normalizedFirstName) {
        return { ok: false, errorKey: "authErrors.firstNameRequired" };
    }

    if (!normalizedLastName) {
        return { ok: false, errorKey: "authErrors.lastNameRequired" };
    }

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
            firstName: normalizedFirstName,
            lastName: normalizedLastName,
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

export const validateFreeEmail = (email: string) => isEmailValid(email);

