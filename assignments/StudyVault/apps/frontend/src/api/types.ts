export type FileRecord = {
  file_id: string;
  owner_id: string;
  filename: string;
  mime_type: string;
  size: number;
  tags: string[];
  object_key: string;
  created_at: string;
};

export type DriveItem = {
  item_id: string;
  kind: "file" | "folder";
  owner_id: string;
  name: string;
  parent_folder_id: string | null;
  created_at: string;
  updated_at: string;
  trashed_at: string | null;
  purge_after: string | null;
  size: number | null;
  mime_type: string | null;
  tags: string[];
  object_key: string | null;
  path_depth: number | null;
  deleted_by_cascade: boolean;
};

export type CatalogItemsResponse = {
  parent_folder_id: string | null;
  items: DriveItem[];
};

export type ActivityRecord = {
  activity_id: string;
  owner_id: string;
  action: string;
  file_id: string;
  filename: string;
  created_at: string;
};

export type AdminUserSummary = {
  user_id: string;
  username: string;
  email: string | null;
  enabled: boolean;
  email_verified: boolean;
  roles: string[];
  created_at: string | null;
};

export type AdminPasswordResetResult = {
  user_id: string;
  username: string;
  temporary_password: string;
};

export type AdminAuditEvent = {
  event_id: string;
  event_type: string;
  category: string;
  actor_user_id: string | null;
  actor_username: string | null;
  actor_email: string | null;
  target_user_id: string | null;
  target_username: string | null;
  target_email: string | null;
  owner_username: string | null;
  owner_email: string | null;
  file_id: string | null;
  filename: string | null;
  status: string | null;
  service: string | null;
  message: string;
  metadata: Record<string, string | number | boolean | null>;
  created_at: string;
};

export type AdminServiceHealth = {
  service: string;
  status: string;
  detail: string | null;
};

export type AdminHealthSummary = {
  total_users: number;
  enabled_users: number;
  admin_users: number;
  recent_uploads: number;
  recent_downloads: number;
  recent_searches: number;
  recent_errors: number;
  services: AdminServiceHealth[];
};

export type AdminErrorRecord = {
  event_id: string;
  service: string;
  message: string;
  request_id: string | null;
  event_name: string | null;
  status: string | null;
  created_at: string;
};
