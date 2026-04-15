import { useMutation } from '@tanstack/react-query';
import { useAuthStore, type AuthUser } from '@/stores/auth.store';
import { changePassword, updateProfile } from './api';
import type { ChangePasswordPayload, UpdateProfilePayload } from './types';

export function useUpdateProfile() {
  const user = useAuthStore((s) => s.user);
  const token = useAuthStore((s) => s.token);
  const setSession = useAuthStore((s) => s.setSession);

  return useMutation({
    mutationFn: (payload: UpdateProfilePayload): Promise<AuthUser> => {
      if (!user) throw new Error('Not authenticated');
      return updateProfile(payload, user);
    },
    onSuccess: (updated) => {
      if (token) setSession({ token, user: updated });
    }
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (payload: ChangePasswordPayload) => changePassword(payload)
  });
}
