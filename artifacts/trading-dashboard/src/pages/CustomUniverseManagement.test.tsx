// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import CustomUniverseManagement from "./CustomUniverseManagement";

const mocks = vi.hoisted(() => ({
  active: vi.fn(),
  revisions: vi.fn(),
  detail: vi.fn(),
  members: vi.fn(),
  mapping: vi.fn(),
  diff: vi.fn(),
  audit: vi.fn(),
  mutation: vi.fn(),
}));

vi.mock("@/hooks/use-custom-universe-management", () => ({
  useActiveUniverse: () => mocks.active(),
  useRevisions: () => mocks.revisions(),
  useRevisionDetail: () => mocks.detail(),
  useRevisionMembers: () => mocks.members(),
  useMappingCoverage: () => mocks.mapping(),
  useRevisionDiff: () => mocks.diff(),
  useAudit: () => mocks.audit(),
  useCreateDraft: () => mocks.mutation(),
  useUpdateMember: () => mocks.mutation(),
  useValidateRevision: () => mocks.mutation(),
  useActivationRequest: () => mocks.mutation(),
  useActivateRevision: () => mocks.mutation(),
}));

vi.mock("@/hooks/use-toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

const activeRevision = {
  id: "active-v1", universe_key: "NIFTY_50", display_name: "NIFTY 50", version: 1,
  status: "ACTIVE", effective_from: "2026-08-01T00:00:00Z", effective_until: null,
  created_at: "2026-08-01T00:00:00Z", created_by: "system", approved_at: "2026-08-01T00:00:00Z",
  approved_by: "system", notes: null, exact_set_hash: "active-hash", enabled_symbol_count: 2, source_id: "baseline",
};
const draftRevision = {
  ...activeRevision, id: "draft-v2", version: 2, status: "DRAFT", approved_at: null, approved_by: null,
  exact_set_hash: "draft-hash", enabled_symbol_count: 2,
};
const members = [
  { id: "reliance", universe_id: "active-v1", symbol: "RELIANCE", exchange: "NSE", sector: "Energy", instrument_token: 1, mapping_status: "MAPPED", enabled: true, added_at: "2026-08-01T00:00:00Z", added_by: "system", removed_at: null, removed_by: null, notes: null, metadata: null },
  { id: "bad", universe_id: "active-v1", symbol: "UNMAPPED", exchange: "NSE", sector: "Other", instrument_token: null, mapping_status: "UNMAPPED", enabled: true, added_at: "2026-08-01T00:00:00Z", added_by: "system", removed_at: null, removed_by: null, notes: null, metadata: null },
];

function queryState(data: unknown) {
  return { data, isLoading: false, isSuccess: true, isError: false, error: null };
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CustomUniverseManagement />
    </QueryClientProvider>,
  );
}

function setSafeResponses() {
  mocks.active.mockReturnValue(queryState({ success: true, active_revision: activeRevision, activation: { locked: true, lock_reason: "Certification evidence is required.", production_release: "initial" } }));
  mocks.revisions.mockReturnValue(queryState({ success: true, revisions: [activeRevision, draftRevision] }));
  mocks.detail.mockReturnValue(queryState({ success: true, revision: activeRevision }));
  mocks.members.mockReturnValue(queryState({ success: true, revision: { ...activeRevision, members } }));
  mocks.mapping.mockReturnValue(queryState({ success: true, version: 1, total: 2, mapped: 1, unmapped: ["UNMAPPED"], percent: 50, complete: false, activation_mapping_complete: false }));
  mocks.diff.mockReturnValue(queryState({ success: true, left_version: 1, right_version: 2, added: ["TCS"], removed: ["UNMAPPED"], changed: [], unchanged: ["RELIANCE"] }));
  mocks.audit.mockReturnValue(queryState({ success: true, events: [] }));
  mocks.mutation.mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false, error: null });
}

describe("CustomUniverseManagement safety states", () => {
  it("keeps draft creation unavailable when the server denies access", () => {
    const denied = new ApiError("unauthorized", 401, "/universe/v1/active");
    mocks.active.mockReturnValue({ data: undefined, isLoading: false, isError: true, error: denied });
    mocks.revisions.mockReturnValue({ data: undefined, isLoading: false, isError: true, error: denied });
    mocks.detail.mockReturnValue(queryState(undefined));
    mocks.members.mockReturnValue(queryState(undefined));
    mocks.mapping.mockReturnValue(queryState(undefined));
    mocks.diff.mockReturnValue(queryState(undefined));
    mocks.audit.mockReturnValue(queryState({ success: true, events: [] }));
    mocks.mutation.mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false, error: null });

    renderPage();

    expect(screen.getByTestId("status-universe-unauthorized")).toBeTruthy();
    expect(screen.queryByTestId("button-create-draft")).toBeNull();
    expect(screen.queryByText(/admin token/i)).toBeNull();
  });

  it("waits for revision history before deciding there is no draft", () => {
    mocks.active.mockReturnValue(queryState({ success: true, active_revision: activeRevision, activation: { locked: true, lock_reason: "Certification evidence is required.", production_release: "initial" } }));
    mocks.revisions.mockReturnValue({ data: undefined, isLoading: true, isSuccess: false, isError: false, error: null });
    mocks.detail.mockReturnValue(queryState(undefined));
    mocks.members.mockReturnValue(queryState(undefined));
    mocks.mapping.mockReturnValue(queryState(undefined));
    mocks.diff.mockReturnValue(queryState(undefined));
    mocks.audit.mockReturnValue(queryState({ success: true, events: [] }));
    mocks.mutation.mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false, error: null });

    renderPage();

    expect(screen.getByTestId("status-draft-history-loading")).toBeTruthy();
    expect(screen.queryByText("No draft revision currently exists.")).toBeNull();
    expect(screen.queryByTestId("button-create-draft")).toBeNull();
  });

  it("filters members and keeps the server activation lock ahead of typed confirmation", async () => {
    setSafeResponses();
    renderPage();

    fireEvent.mouseDown(screen.getByTestId("tab-directory"), { button: 0, ctrlKey: false });
    await waitFor(() => expect(screen.getByTestId("input-directory-search")).toBeTruthy());
    fireEvent.change(screen.getByTestId("input-directory-search"), { target: { value: "reliance" } });
    expect(screen.getByText("RELIANCE")).toBeTruthy();
    expect(screen.queryByText("UNMAPPED")).toBeNull();

    fireEvent.mouseDown(screen.getByTestId("tab-overview"), { button: 0, ctrlKey: false });
    await waitFor(() => expect(screen.getByTestId("button-activate-draft")).toBeTruthy());
    fireEvent.click(screen.getByTestId("button-activate-draft"));
    expect(screen.getByText("Server Certification Lock")).toBeTruthy();
    expect(screen.getByTestId("input-activation-confirmation")).toHaveProperty("disabled", true);
    expect(screen.getByTestId("button-confirm-activation")).toHaveProperty("disabled", true);
  });
});