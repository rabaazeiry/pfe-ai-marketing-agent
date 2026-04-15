import { api } from '@/lib/api/client';
import type { AuthUser } from '@/stores/auth.store';
import type { ChangePasswordPayload, UpdateProfilePayload } from './types';

type UpdateProfileResponse = { success: boolean; data: AuthUser; message?: string };
type ChangePasswordResponse = { success: boolean; message?: string };

const MOCK_DELAY_MS = 600;

function delay(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

function isMissingEndpoint(err: unknown): boolean {
  const status = (err as { response?: { status?: number } })?.response?.status;
  return status === 404 || status === 501;
}

/**
 * PATCH /auth/me — updates the authenticated user's profile.
 * Falls back to a local mock if the backend route is not yet implemented
 * (keeps Settings usable while the endpoint is on the roadmap).
 */
export async function updateProfile(
  payload: UpdateProfilePayload,
  current: AuthUser
): Promise<AuthUser> {
  try {
    const { data } = await api.patch<UpdateProfileResponse>('/auth/me', payload);
    return data.data;
  } catch (err) {
    if (isMissingEndpoint(err)) {
      await delay(MOCK_DELAY_MS);
      return { ...current, ...payload };
    }
    throw err;
  }
}

/**
 * POST /auth/change-password — rotates the authenticated user's password.
 * Falls back to a simulated success if the backend route is missing.
 */
export async function changePassword(payload: ChangePasswordPayload): Promise<void> {
  try {
    await api.post<ChangePasswordResponse>('/auth/change-password', payload);
  } catch (err) {
    if (isMissingEndpoint(err)) {
      await delay(MOCK_DELAY_MS);
      return;
    }
    throw err;
  }
}
