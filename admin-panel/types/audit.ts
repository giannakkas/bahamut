export interface AuditLogEntry {
  id: number;
  timestamp: string;
  key: string;
  old_value: string;
  new_value: string;
  source: "user" | "system";
  user: string;
}

export interface AuditFilters {
  category: string;
  source: string;
  dateFrom?: string;
  dateTo?: string;
}
