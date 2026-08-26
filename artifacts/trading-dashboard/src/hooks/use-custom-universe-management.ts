import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";

// ── Types ───────────────────────────────────────────────────────────────────

export interface Revision {
  id: string;
  universe_key: string;
  display_name: string;
  version: number;
  status: "ACTIVE" | "DRAFT" | "PENDING_ACTIVATION" | "CANCELLED" | "ARCHIVED" | string;
  effective_from: string | null;
  effective_until: string | null;
  created_at: string;
  created_by: string;
  approved_at: string | null;
  approved_by: string | null;
  notes: string | null;
  exact_set_hash: string | null;
  enabled_symbol_count: number;
  source_id: string | null;
  members?: Member[];
}

export interface Member {
  id: string;
  universe_id: string;
  symbol: string;
  exchange: string;
  sector: string | null;
  instrument_token: number | null;
  mapping_status: "MAPPED" | "UNMAPPED" | "INVALID" | string;
  enabled: boolean;
  added_at: string;
  added_by: string;
  removed_at: string | null;
  removed_by: string | null;
  notes: string | null;
  metadata: any | null;
}

export interface Validation {
  status: "VALIDATION_PASS" | "VALIDATION_FAIL";
  valid: boolean;
  errors: { code: string; message: string; symbol: string | null; field: string | null }[];
  mapping_coverage: { mapped: number; total: number; percent: number; complete: boolean };
  provider_compatibility: boolean;
  phase5a_compatibility: boolean;
  readiness_compatibility: boolean;
  checked_at: string;
  instrument_reference: any;
}

export interface AuditEvent {
  id: string;
  occurred_at: string;
  actor: string;
  action: string;
  universe_key: string;
  old_version: number | null;
  new_version: number | null;
  symbol: string | null;
  change_type: string | null;
  old_value: any | null;
  new_value: any | null;
  notes: string | null;
  correlation_id: string | null;
  approval_state: string | null;
}

export interface ActiveResponse {
  success: boolean;
  active_revision: Revision | null;
  activation: {
    locked: boolean;
    lock_reason: string | null;
    production_release: string;
  };
}

export interface RevisionsResponse {
  success: boolean;
  revisions: Revision[];
}

export interface RevisionDetailResponse {
  success: boolean;
  revision: Revision;
  latest_validation?: Validation;
}

export interface RevisionMembersResponse {
  success: boolean;
  revision: Revision;
}

export interface MappingCoverageResponse {
  success: boolean;
  version: number;
  total: number;
  mapped: number;
  unmapped: any[];
  percent: number;
  complete: boolean;
  latest_validation?: Validation;
  validated_mapping_coverage?: any;
  activation_mapping_complete: boolean;
}

export interface DiffResponse {
  success: boolean;
  left_version: number;
  right_version: number;
  added: string[];
  removed: string[];
  changed: string[];
  unchanged: string[];
}

export interface AuditResponse {
  success: boolean;
  events: AuditEvent[];
}

// ── Query Keys ──────────────────────────────────────────────────────────────

export const universeKeys = {
  all: ["universe-management"] as const,
  active: () => [...universeKeys.all, "active"] as const,
  revisions: () => [...universeKeys.all, "revisions"] as const,
  revision: (version: number) => [...universeKeys.all, "revision", version] as const,
  members: (version: number) => [...universeKeys.all, "revision", version, "members"] as const,
  mapping: (version: number) => [...universeKeys.all, "revision", version, "mapping"] as const,
  diff: (left: number, right: number) => [...universeKeys.all, "diff", left, right] as const,
  audit: () => [...universeKeys.all, "audit"] as const,
};

// ── Queries ─────────────────────────────────────────────────────────────────

export function useActiveUniverse() {
  return useQuery<ActiveResponse>({
    queryKey: universeKeys.active(),
    queryFn: () => apiJson("/universe/v1/active"),
  });
}

export function useRevisions() {
  return useQuery<RevisionsResponse>({
    queryKey: universeKeys.revisions(),
    queryFn: () => apiJson("/universe/v1/revisions"),
  });
}

export function useRevisionDetail(version: number, enabled = true) {
  return useQuery<RevisionDetailResponse>({
    queryKey: universeKeys.revision(version),
    queryFn: () => apiJson(`/universe/v1/revisions/${version}`),
    enabled,
  });
}

export function useRevisionMembers(version: number, enabled = true) {
  return useQuery<RevisionMembersResponse>({
    queryKey: universeKeys.members(version),
    queryFn: () => apiJson(`/universe/v1/revisions/${version}/members`),
    enabled,
  });
}

export function useMappingCoverage(version: number, enabled = true) {
  return useQuery<MappingCoverageResponse>({
    queryKey: universeKeys.mapping(version),
    queryFn: () => apiJson(`/universe/v1/revisions/${version}/mapping-coverage`),
    enabled,
  });
}

export function useRevisionDiff(leftVersion: number | null, rightVersion: number | null) {
  const enabled = leftVersion !== null && rightVersion !== null;
  return useQuery<DiffResponse>({
    queryKey: universeKeys.diff(leftVersion!, rightVersion!),
    queryFn: () => apiJson(`/universe/v1/revisions/${leftVersion}/diff/${rightVersion}`),
    enabled,
  });
}

export function useAudit(limit = 200) {
  return useQuery<AuditResponse>({
    queryKey: universeKeys.audit(),
    queryFn: () => apiJson(`/universe/v1/audit?limit=${limit}`),
  });
}

// ── Mutations ───────────────────────────────────────────────────────────────

export function useCreateDraft() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: { base_version?: number; notes?: string }) =>
      apiJson("/universe/v1/drafts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: universeKeys.all });
    },
  });
}

export function useUpdateMember() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ version, ...data }: { version: number; operation: "add" | "remove" | "restore" | "update"; symbol: string; member?: Partial<Member>; expected_hash?: string }) =>
      apiJson(`/universe/v1/drafts/${version}/members`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: universeKeys.all });
    },
  });
}

export function useValidateRevision() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (version: number) =>
      apiJson(`/universe/v1/revisions/${version}/validate`, {
        method: "POST",
      }),
    onSuccess: (_, version) => {
      queryClient.invalidateQueries({ queryKey: universeKeys.revision(version) });
    },
  });
}

export function useActivationRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ version, confirmation }: { version: number; confirmation: string }) =>
      apiJson(`/universe/v1/revisions/${version}/activation-request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: universeKeys.all });
    },
  });
}

export function useActivateRevision() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ version, confirmation }: { version: number; confirmation: string }) =>
      apiJson(`/universe/v1/revisions/${version}/activate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: universeKeys.all });
    },
  });
}
