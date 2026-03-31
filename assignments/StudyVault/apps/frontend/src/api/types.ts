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

export type ActivityRecord = {
  activity_id: string;
  owner_id: string;
  action: string;
  file_id: string;
  filename: string;
  created_at: string;
};
