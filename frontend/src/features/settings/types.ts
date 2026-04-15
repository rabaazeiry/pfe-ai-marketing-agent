export type UpdateProfilePayload = {
  firstName: string;
  lastName: string;
  email: string;
};

export type ChangePasswordPayload = {
  currentPassword: string;
  newPassword: string;
};
