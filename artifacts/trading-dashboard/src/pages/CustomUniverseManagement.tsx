import { useState, useMemo } from "react";
import { 
  useActiveUniverse, 
  useRevisions, 
  useRevisionDetail, 
  useRevisionMembers, 
  useMappingCoverage,
  useRevisionDiff,
  useAudit,
  useCreateDraft,
  useUpdateMember,
  useValidateRevision,
  useActivationRequest,
  useActivateRevision,
  type Member,
  type Revision
} from "@/hooks/use-custom-universe-management";
import { PageHeader } from "@/components/ds/PageHeader";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogTrigger } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api";
import { 
  Database, Plus, Trash2, RotateCcw, CheckCircle2,
  Activity, Search, ServerCog, Lock, Unlock, FileDiff, ShieldAlert,
  ArrowRightLeft
} from "lucide-react";

// Helper for date formatting
const fmtDate = (iso: string | null) => {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });
};

const isUnauthorized = (error: unknown) =>
  error instanceof ApiError && (error.status === 401 || error.status === 403);

// ── Components ──────────────────────────────────────────────────────────────

function AddSymbolDialog({ draftVersion, expectedHash }: { draftVersion: number; expectedHash?: string | null }) {
  const [open, setOpen] = useState(false);
  const [symbol, setSymbol] = useState("");
  const [exchange, setExchange] = useState("NSE");
  const [sector, setSector] = useState("");
  const { toast } = useToast();
  
  const addMutation = useUpdateMember();

  const handleAdd = () => {
    if (!symbol.trim()) {
      toast({ title: "Validation Error", description: "Symbol cannot be blank.", variant: "destructive" });
      return;
    }
    addMutation.mutate({
      version: draftVersion,
      operation: "add",
      symbol: symbol.toUpperCase(),
      member: { exchange, sector },
      expected_hash: expectedHash ?? undefined,
    }, {
      onSuccess: () => {
        toast({ title: "Symbol Added", description: `${symbol.toUpperCase()} added to draft.` });
        setSymbol("");
        setSector("");
        setOpen(false);
      },
      onError: (err: any) => {
        toast({ 
          title: "Server Validation Failed", 
          description: err.message || "Failed to add symbol. Check rules.", 
          variant: "destructive" 
        });
      }
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="default" className="gap-2" data-testid="button-add-symbol">
          <Plus size={14} /> Add Symbol
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add Symbol to Draft</DialogTitle>
          <DialogDescription>
            Propose a new instrument for inclusion. Server validation will verify mapping,
            availability, and sector mapping.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="symbol">Symbol</Label>
            <Input 
              id="symbol"
              placeholder="e.g. RELIANCE" 
              value={symbol} 
              onChange={e => setSymbol(e.target.value)} 
              data-testid="input-add-symbol"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="exchange">Exchange</Label>
            <Select value={exchange} onValueChange={setExchange}>
              <SelectTrigger id="exchange" data-testid="select-add-exchange">
                <SelectValue placeholder="Exchange" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="NSE">NSE</SelectItem>
                <SelectItem value="BSE">BSE</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="sector">Sector (Optional)</Label>
            <Input 
              id="sector"
              placeholder="e.g. Financial Services" 
              value={sector} 
              onChange={e => setSector(e.target.value)} 
              data-testid="input-add-sector"
            />
          </div>
        </div>
        <DialogFooter>
          {addMutation.isError && (
            <p className="mr-auto max-w-sm text-sm text-destructive" data-testid="status-add-symbol-validation-error">
              Server validation failed: {(addMutation.error as Error).message}
            </p>
          )}
          <Button variant="outline" onClick={() => setOpen(false)} data-testid="button-cancel-add-symbol">Cancel</Button>
          <Button onClick={handleAdd} disabled={addMutation.isPending} data-testid="button-submit-symbol">
            {addMutation.isPending ? "Validating..." : "Add Symbol"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ActivationDialog({ version, locked, lockReason }: { version: number; locked: boolean; lockReason: string | null }) {
  const [open, setOpen] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const { toast } = useToast();
  const activationRequest = useActivationRequest();
  const expectedConfirmation = `ACTIVATE ${version}`;

  const handleRequest = () => {
    if (locked || confirmation.trim() !== expectedConfirmation) return;
    activationRequest.mutate({ version, confirmation: confirmation.trim() }, {
      onSuccess: () => {
        toast({ title: "Activation Requested", description: `Revision v${version} submitted for activation.` });
        setConfirmation("");
        setOpen(false);
      },
      onError: (err: any) => {
        toast({ title: "Activation Failed", description: err.message, variant: "destructive" });
      }
    });
  };

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => {
      setOpen(nextOpen);
      if (!nextOpen) setConfirmation("");
    }}>
      <DialogTrigger asChild>
        <Button size="sm" variant={locked ? "secondary" : "default"} className="gap-2" data-testid="button-activate-draft">
          {locked ? <Lock size={14} /> : <Unlock size={14} />} Request Activation
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Request Activation</DialogTitle>
          <DialogDescription>
            Submit this draft revision to replace the active universe.
          </DialogDescription>
        </DialogHeader>
        <div className="py-4">
          {locked ? (
            <div className="flex items-start gap-3 rounded-md bg-warn-surface/20 border border-warn-border p-4 text-warn-text">
              <ShieldAlert size={18} className="mt-0.5 text-warn-icon" />
              <div>
                <p className="font-semibold text-sm">Server Certification Lock</p>
                <p className="text-sm mt-1">{lockReason || "Production restrictions block this activation."}</p>
              </div>
            </div>
          ) : <p className="text-sm">Activation is unlocked. Type the exact confirmation below to submit v{version} for approval.</p>}
          <div className="mt-4 space-y-2">
            <Label htmlFor="activation-confirmation">Type {expectedConfirmation}</Label>
            <Input
              id="activation-confirmation"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              placeholder={expectedConfirmation}
              className="font-mono"
              disabled={locked}
              data-testid="input-activation-confirmation"
            />
            {locked && <p className="text-xs text-muted-foreground">Confirmation is unavailable until the server certification lock is removed.</p>}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} data-testid="button-cancel-activation">Cancel</Button>
          <Button onClick={handleRequest} disabled={locked || confirmation.trim() !== expectedConfirmation || activationRequest.isPending} data-testid="button-confirm-activation">
            {activationRequest.isPending ? "Requesting..." : "Confirm Activation"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Main Page Component ──────────────────────────────────────────────────────

export default function CustomUniverseManagement() {
  const { toast } = useToast();
  const [activeTab, setActiveTab] = useState("overview");

  const { data: activeRes, isLoading: activeLoading, error: activeError } = useActiveUniverse();
  const revisionsQ = useRevisions();
  
  const activeRev = activeRes?.active_revision;
  const draftRev = revisionsQ.data?.revisions.find(r => r.status === "DRAFT");
  const activeMappingQ = useMappingCoverage(activeRev?.version ?? 0, Boolean(activeRev));
  
  const createDraftMutation = useCreateDraft();

  const handleCreateDraft = () => {
    createDraftMutation.mutate({ base_version: activeRev?.version }, {
      onSuccess: () => {
        toast({ title: "Draft Created", description: "A new draft universe has been created." });
      },
      onError: (err: any) => {
        toast({ title: "Error", description: err.message, variant: "destructive" });
      }
    });
  };

  const isLocked = activeRes?.activation?.locked ?? true;
  const lockReason = activeRes?.activation?.lock_reason ?? null;
  // Do not interpret an unresolved revisions query as "no draft". Creating a
  // second draft would make the operator's editable revision ambiguous.
  const canCreateDraft = Boolean(activeRev) && revisionsQ.isSuccess && !activeError && !revisionsQ.error;

  return (
    <div className="flex flex-col min-h-[100dvh] w-full" data-testid="page-universe-management">
      <div className="px-6 pt-6 pb-2">
        <PageHeader
          title="Universe Management"
          subtitle="Prepare immutable draft revisions for paper execution and research. The active production universe remains read-only here."
          icon={Database}
          agentId="market-data"
          agentName="Market Data"
          lastUpdated={new Date().toISOString()}
        />
      </div>

      <div className="flex-1 px-6 pb-6 flex flex-col gap-6">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full flex-1 flex flex-col">
          <TabsList className="w-full justify-start border-b rounded-none px-0 bg-transparent mb-4">
            <TabsTrigger value="overview" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary" data-testid="tab-overview">
              Overview & Draft
            </TabsTrigger>
            <TabsTrigger value="directory" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary" data-testid="tab-directory">
              Member Directory
            </TabsTrigger>
            <TabsTrigger value="history" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary" data-testid="tab-history">
              Version History
            </TabsTrigger>
            <TabsTrigger value="audit" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary" data-testid="tab-audit">
              Audit Log
            </TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="flex-1 space-y-6">
            {(isUnauthorized(activeError) || isUnauthorized(revisionsQ.error)) && (
              <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive" data-testid="status-universe-unauthorized">
                You are not authorized to view or prepare universe revisions. No credentials can be entered on this page.
              </div>
            )}
            {(activeError && !isUnauthorized(activeError)) || (revisionsQ.error && !isUnauthorized(revisionsQ.error)) ? (
              <div className="rounded-lg border border-warn-border bg-warn-surface px-4 py-3 text-sm text-warn-text" data-testid="status-universe-partial-error">
                Some universe information could not be refreshed. The views below show only the server data that is currently available.
              </div>
            ) : null}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
              
              {/* ACTIVE UNIVERSE PANEL */}
              <Card className="glass shadow-sm h-full" data-testid="card-active-universe">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle className="text-xl flex items-center gap-2">
                        <CheckCircle2 className="text-omni-success" size={20} />
                        Active Universe
                      </CardTitle>
                      <CardDescription>Currently driving paper market execution.</CardDescription>
                    </div>
                    {activeRev && <Badge className="bg-omni-success text-white border-transparent">v{activeRev.version}</Badge>}
                  </div>
                </CardHeader>
                <CardContent>
                  {activeLoading ? (
                    <div className="h-40 flex items-center justify-center text-muted-foreground">Loading active universe...</div>
                   ) : activeError ? (
                     <div className="h-40 flex items-center justify-center text-omni-danger" data-testid="status-active-universe-error">
                       {isUnauthorized(activeError) ? "Authorization required to load the active universe." : "Active universe data is unavailable or stale."}
                     </div>
                  ) : !activeRev ? (
                    <div className="h-40 flex items-center justify-center text-muted-foreground">No active universe configured.</div>
                  ) : (
                    <div className="space-y-6">
                      <div className="grid grid-cols-2 gap-y-4 text-sm">
                        <div>
                          <p className="text-muted-foreground mb-1 text-xs">Identity</p>
                          <p className="font-medium">{activeRev.universe_key}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground mb-1 text-xs">Enabled Count</p>
                          <p className="font-medium">{activeRev.enabled_symbol_count} symbols</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground mb-1 text-xs">Effective From</p>
                          <p className="font-medium">{fmtDate(activeRev.effective_from)}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground mb-1 text-xs">Last Updated By</p>
                          <p className="font-medium">{activeRev.approved_by || activeRev.created_by}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground mb-1 text-xs">Latest Change</p>
                          <p className="font-medium">{fmtDate(activeRev.approved_at || activeRev.created_at)}</p>
                        </div>
                      </div>
                      
                      <div className="p-4 bg-muted/20 border rounded-md">
                        <div className="flex justify-between items-center mb-2">
                          <p className="text-sm font-medium">Mapping Completeness</p>
                          {activeMappingQ.isLoading ? (
                            <Badge variant="outline" data-testid="status-active-mapping-loading">Checking</Badge>
                          ) : activeMappingQ.data?.complete ? (
                            <Badge variant="outline" className="text-omni-success border-omni-success/30" data-testid="status-active-mapping-complete">
                              {activeMappingQ.data.mapped} / {activeMappingQ.data.total} mapped
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="text-warn-text border-warn-border" data-testid="status-active-mapping-partial">
                              Mapping incomplete
                            </Badge>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {activeMappingQ.data
                            ? `${activeMappingQ.data.percent.toFixed(1)}% of the active revision is currently mapped.`
                            : "Mapping coverage has not been confirmed by the server."}
                        </p>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* DRAFT REVISION PANEL */}
              <Card className="glass shadow-sm h-full flex flex-col" data-testid="card-draft-universe">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle className="text-xl flex items-center gap-2">
                        <Activity className="text-blue-500" size={20} />
                        Draft Revision
                      </CardTitle>
                      <CardDescription>Proposed changes for next activation.</CardDescription>
                    </div>
                    {revisionsQ.isLoading ? (
                      <Badge variant="outline" className="text-muted-foreground" data-testid="status-draft-history-checking">Checking</Badge>
                    ) : draftRev ? (
                      <Badge variant="outline" className="bg-blue-500/10 text-blue-500 border-blue-500/30">v{draftRev.version}</Badge>
                    ) : (
                      <Badge variant="outline" className="text-muted-foreground">None</Badge>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="flex-1 flex flex-col">
                  {revisionsQ.isLoading ? (
                    <div className="flex-1 flex flex-col items-center justify-center text-center p-6 border border-dashed rounded-md bg-muted/10" data-testid="status-draft-history-loading">
                      <FileDiff className="text-muted-foreground mb-3" size={32} />
                      <p className="text-sm text-muted-foreground">Checking revision history before draft creation...</p>
                    </div>
                  ) : revisionsQ.error ? (
                    <div className="flex-1 flex flex-col items-center justify-center text-center p-6 border border-dashed rounded-md bg-muted/10" data-testid="status-draft-history-error">
                      <FileDiff className="text-muted-foreground mb-3" size={32} />
                      <p className="text-sm text-muted-foreground">Draft status is unavailable. Retry once revision history is restored.</p>
                    </div>
                  ) : !draftRev ? (
                    <div className="flex-1 flex flex-col items-center justify-center text-center p-6 border border-dashed rounded-md bg-muted/10">
                      <FileDiff className="text-muted-foreground mb-3" size={32} />
                      <p className="text-sm text-muted-foreground mb-4">No draft revision currently exists.</p>
                       <Button onClick={handleCreateDraft} disabled={!canCreateDraft || createDraftMutation.isPending} data-testid="button-create-draft">
                        {createDraftMutation.isPending ? "Creating..." : "Create Draft"}
                      </Button>
                    </div>
                  ) : (
                    <DraftView
                      draftVersion={draftRev.version}
                      draftHash={draftRev.exact_set_hash}
                      draftCount={draftRev.enabled_symbol_count}
                      activeVersion={activeRev?.version}
                      locked={isLocked}
                      lockReason={lockReason}
                    />
                  )}
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="directory" className="flex-1">
            <Card className="glass shadow-sm h-full flex flex-col">
              <CardHeader>
                <CardTitle>Member Directory</CardTitle>
                <CardDescription>Explore all symbols in the active and draft revisions.</CardDescription>
              </CardHeader>
              <CardContent className="flex-1">
                <MemberDirectoryTab activeRev={activeRev} draftRev={draftRev} />
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="history" className="flex-1">
            <Card className="glass shadow-sm h-[600px] flex flex-col">
              <CardHeader>
                <CardTitle>Version History</CardTitle>
                <CardDescription>Immutable record of all previous universe states.</CardDescription>
              </CardHeader>
              <CardContent className="flex-1 overflow-hidden p-0">
                <VersionHistoryTab revisions={revisionsQ.data?.revisions || []} />
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="audit" className="flex-1">
            <Card className="glass shadow-sm h-[600px] flex flex-col">
              <CardHeader>
                <CardTitle>Audit Log</CardTitle>
                <CardDescription>Detailed chronological event log for universe operations.</CardDescription>
              </CardHeader>
              <CardContent className="flex-1 overflow-hidden p-0">
                <AuditLogTab />
              </CardContent>
            </Card>
          </TabsContent>

        </Tabs>
      </div>
    </div>
  );
}

// ── Tab Components ──────────────────────────────────────────────────────────

function DraftView({
  draftVersion,
  draftHash,
  draftCount,
  activeVersion,
  locked,
  lockReason,
}: {
  draftVersion: number;
  draftHash?: string | null;
  draftCount: number;
  activeVersion?: number;
  locked: boolean;
  lockReason: string | null;
}) {
  const { data: diffRes, isLoading: diffLoading } = useRevisionDiff(activeVersion ?? null, draftVersion);
  const { data: validationRes } = useMappingCoverage(draftVersion);
  const { toast } = useToast();
  
  const validateMutation = useValidateRevision();
  const updateMutation = useUpdateMember();

  const handleValidate = () => {
    validateMutation.mutate(draftVersion, {
      onSuccess: () => toast({ title: "Validation Requested", description: "Server is re-evaluating draft mapping." }),
      onError: (err: any) => toast({ title: "Validation Error", description: err.message, variant: "destructive" })
    });
  };

  const handleRemove = (symbol: string) => {
    updateMutation.mutate({ version: draftVersion, operation: "remove", symbol, expected_hash: draftHash ?? undefined }, {
      onSuccess: () => toast({ title: "Symbol Removed", description: `${symbol} flagged for removal.` })
    });
  };

  const diff = diffRes || { added: [], removed: [], changed: [], unchanged: [] };
  const additions = diff.added?.length || 0;
  const removals = diff.removed?.length || 0;
  const hasChanges = additions > 0 || removals > 0 || diff.changed?.length > 0;

  return (
    <div className="flex flex-col h-full space-y-4">
      <div className="flex justify-between items-center p-3 bg-muted/20 border rounded-md">
        <div className="flex gap-4">
          <div className="text-center px-3 border-r border-border">
            <p className="text-xl font-bold text-omni-success">+{additions}</p>
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Added</p>
          </div>
          <div className="text-center px-3">
            <p className="text-xl font-bold text-omni-danger">-{removals}</p>
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Removed</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={handleValidate} disabled={validateMutation.isPending} data-testid="button-validate-draft">
            {validateMutation.isPending ? "Validating..." : "Validate"}
          </Button>
          <AddSymbolDialog draftVersion={draftVersion} expectedHash={draftHash} />
          <ActivationDialog version={draftVersion} locked={locked} lockReason={lockReason} />
        </div>
      </div>

      <div className="flex-1 border rounded-md overflow-hidden flex flex-col">
        <div className="bg-muted/50 p-2 text-sm font-medium border-b px-4">
          Draft Diffs vs Active
        </div>
        <ScrollArea className="flex-1 h-[200px]">
          {diffLoading ? (
            <div className="p-4 text-center text-sm text-muted-foreground">Loading diffs...</div>
          ) : !hasChanges ? (
            <div className="p-8 text-center text-sm text-muted-foreground">No changes proposed in this draft.</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Change</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {diff.added.map(symbol => (
                  <TableRow key={`add-${symbol}`}>
                    <TableCell className="font-medium">{symbol}</TableCell>
                    <TableCell><Badge variant="outline" className="text-omni-success border-omni-success/30 bg-omni-success/10">Added</Badge></TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="icon" onClick={() => handleRemove(symbol)} title="Undo Add" data-testid={`btn-undo-add-${symbol}`}>
                        <Trash2 size={14} className="text-muted-foreground" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {diff.removed.map(symbol => (
                  <TableRow key={`rm-${symbol}`}>
                    <TableCell className="font-medium text-muted-foreground line-through">{symbol}</TableCell>
                    <TableCell><Badge variant="outline" className="text-omni-danger border-omni-danger/30 bg-omni-danger/10">Removed</Badge></TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => updateMutation.mutate(
                          { version: draftVersion, operation: "restore", symbol, expected_hash: draftHash ?? undefined },
                          { onSuccess: () => toast({ title: "Symbol Restored", description: `${symbol} restored to the draft.` }) },
                        )}
                        title="Restore"
                        data-testid={`btn-restore-${symbol}`}
                      >
                        <RotateCcw size={14} className="text-muted-foreground" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {diff.changed.map(symbol => (
                  <TableRow key={`changed-${symbol}`}>
                    <TableCell className="font-medium">{symbol}</TableCell>
                    <TableCell><Badge variant="outline" className="text-blue-400 border-blue-400/30 bg-blue-400/10">Changed</Badge></TableCell>
                    <TableCell className="text-right text-xs text-muted-foreground">Draft-only</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </ScrollArea>
      </div>

      {validationRes && (
        <div className="text-xs text-muted-foreground flex items-center justify-between">
          <span data-testid="text-draft-mapping-coverage">Draft v{draftVersion}: {draftCount} enabled · mapping coverage {validationRes.percent.toFixed(1)}%</span>
          {!validationRes.complete && <span className="text-warn-text">Incomplete mapping may block activation.</span>}
        </div>
      )}
    </div>
  );
}

function MemberDirectoryTab({ activeRev, draftRev }: { activeRev?: Revision | null, draftRev?: Revision | null }) {
  const [source, setSource] = useState<"ACTIVE" | "DRAFT">("ACTIVE");
  const [search, setSearch] = useState("");
  const [mappingFilter, setMappingFilter] = useState<"ALL" | "MAPPED" | "UNMAPPED">("ALL");
  
  const version = source === "ACTIVE" ? activeRev?.version : draftRev?.version;
  const { data: membersRes, isLoading } = useRevisionMembers(version || 0, !!version);

  const filteredMembers = useMemo(() => {
    if (!membersRes?.revision?.members) return [];
    return membersRes.revision.members.filter(m => 
      (m.symbol.toLowerCase().includes(search.toLowerCase()) ||
        (m.sector && m.sector.toLowerCase().includes(search.toLowerCase())) ||
        m.exchange.toLowerCase().includes(search.toLowerCase())) &&
      (mappingFilter === "ALL" || (mappingFilter === "MAPPED" ? m.mapping_status === "MAPPED" : m.mapping_status !== "MAPPED"))
    );
  }, [membersRes, search, mappingFilter]);

  return (
    <div className="flex flex-col h-full space-y-4">
      <div className="flex gap-4 items-center">
        <Select value={source} onValueChange={(v: "ACTIVE"|"DRAFT") => setSource(v)}>
          <SelectTrigger className="w-[180px]" data-testid="select-directory-source">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ACTIVE" disabled={!activeRev}>Active Universe</SelectItem>
            <SelectItem value="DRAFT" disabled={!draftRev}>Draft Revision</SelectItem>
          </SelectContent>
        </Select>
        <div className="relative flex-1 max-w-sm">
          <Search size={14} className="absolute left-2.5 top-2.5 text-muted-foreground" />
          <Input 
            placeholder="Search symbols or sectors..." 
            className="pl-8" 
            value={search}
            onChange={e => setSearch(e.target.value)}
            data-testid="input-directory-search"
          />
        </div>
        <Select value={mappingFilter} onValueChange={(value: "ALL" | "MAPPED" | "UNMAPPED") => setMappingFilter(value)}>
          <SelectTrigger className="w-[150px]" data-testid="select-directory-mapping-filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">All mappings</SelectItem>
            <SelectItem value="MAPPED">Mapped only</SelectItem>
            <SelectItem value="UNMAPPED">Needs mapping</SelectItem>
          </SelectContent>
        </Select>
        <div className="text-sm text-muted-foreground ml-auto">
          <span data-testid="text-directory-count">{filteredMembers.length} symbols found</span>
        </div>
      </div>

      <div className="flex-1 border rounded-md overflow-hidden relative">
        <ScrollArea className="h-[400px]">
          <Table>
            <TableHeader className="bg-muted/50 sticky top-0 z-10 backdrop-blur">
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead>Exchange</TableHead>
                <TableHead>Sector</TableHead>
                <TableHead>Mapping Status</TableHead>
                <TableHead>Kite token</TableHead>
                <TableHead>State</TableHead>
                <TableHead>Revision</TableHead>
                <TableHead className="text-right">Added</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">Loading members...</TableCell>
                </TableRow>
              ) : filteredMembers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">No members found.</TableCell>
                </TableRow>
              ) : (
                filteredMembers.map(m => (
                  <TableRow key={m.id} className={!m.enabled ? "opacity-60" : ""}>
                    <TableCell className="font-medium">{m.symbol}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">{m.exchange}</TableCell>
                    <TableCell className="text-muted-foreground">{m.sector || "—"}</TableCell>
                    <TableCell>
                      {m.mapping_status === "MAPPED" ? (
                        <Badge variant="outline" className="text-omni-success border-omni-success/20 bg-omni-success/5 font-mono text-[10px]">MAPPED</Badge>
                      ) : (
                        <Badge variant="outline" className="text-warn-text border-warn-border bg-warn-surface font-mono text-[10px]">{m.mapping_status}</Badge>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{m.instrument_token ?? "—"}</TableCell>
                    <TableCell>
                      {m.enabled ? (
                        <Badge variant="outline" className="text-muted-foreground">Enabled</Badge>
                      ) : (
                        <Badge variant="outline" className="text-omni-danger border-omni-danger/20">Disabled</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">v{version}</TableCell>
                    <TableCell className="text-right text-xs text-muted-foreground">
                      {new Date(m.added_at).toLocaleDateString()}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </ScrollArea>
      </div>
    </div>
  );
}

function VersionHistoryTab({ revisions }: { revisions: Revision[] }) {
  const [selectedVer, setSelectedVer] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState("ALL");
  const historyRev = revisions
    .filter((revision) => revision.status !== "DRAFT")
    .filter((revision) => statusFilter === "ALL" || revision.status === statusFilter)
    .sort((a, b) => b.version - a.version);
  const selectedIndex = historyRev.findIndex((revision) => revision.version === selectedVer);
  const previousVersion = selectedIndex >= 0 ? historyRev[selectedIndex + 1]?.version : undefined;

  return (
    <div className="flex h-full">
      <div className="w-1/3 border-r flex flex-col bg-muted/5">
        <div className="space-y-2 border-b p-3">
          <p className="font-medium text-sm">Committed Versions</p>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger data-testid="select-history-status-filter"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All committed states</SelectItem>
              <SelectItem value="ACTIVE">Active</SelectItem>
              <SelectItem value="PENDING_ACTIVATION">Pending activation</SelectItem>
              <SelectItem value="ARCHIVED">Archived</SelectItem>
              <SelectItem value="CANCELLED">Cancelled</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <ScrollArea className="flex-1">
          {historyRev.map(rev => (
            <button
              key={rev.id}
              onClick={() => setSelectedVer(rev.version)}
              className={`w-full text-left p-4 border-b hover:bg-muted/30 transition-colors flex items-center justify-between ${selectedVer === rev.version ? "bg-muted/50 border-l-4 border-l-primary" : "border-l-4 border-l-transparent"}`}
              data-testid={`history-row-v${rev.version}`}
            >
              <div>
                <div className="font-medium flex items-center gap-2">
                  v{rev.version}
                  <Badge variant="outline" className="text-[10px] uppercase">{rev.status}</Badge>
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  {fmtDate(rev.created_at)}
                </div>
              </div>
              <ArrowRightLeft size={14} className="text-muted-foreground" />
            </button>
          ))}
          {historyRev.length === 0 && <div className="p-6 text-center text-sm text-muted-foreground">No historical versions found.</div>}
        </ScrollArea>
      </div>
      <div className="w-2/3 flex flex-col p-6">
        {selectedVer ? (
          <VersionDetailPane version={selectedVer} previousVersion={previousVersion} />
        ) : (
          <div className="m-auto text-muted-foreground flex flex-col items-center gap-2">
            <ServerCog size={32} className="opacity-50" />
            <p>Select a version to view snapshot details</p>
          </div>
        )}
      </div>
    </div>
  );
}

function VersionDetailPane({ version, previousVersion }: { version: number; previousVersion?: number }) {
  const { data, isLoading, isError } = useRevisionDetail(version);
  const membersQ = useRevisionMembers(version);
  const coverageQ = useMappingCoverage(version);
  const diffQ = useRevisionDiff(previousVersion ?? null, version);
  const auditQ = useAudit();
  
  if (isLoading) return <div className="m-auto text-muted-foreground">Loading details...</div>;
  if (isError || !data?.revision) return <div className="m-auto text-muted-foreground" data-testid="status-history-detail-error">Details unavailable or stale.</div>;
  
  const r = data.revision;

  return (
    <div className="space-y-6 animate-in fade-in zoom-in-95 duration-200">
      <div className="flex justify-between items-start pb-4 border-b">
        <div>
          <h3 className="text-2xl font-bold">Version {r.version}</h3>
          <p className="text-muted-foreground">{r.universe_key}</p>
        </div>
        <Badge variant="outline" className="text-sm px-3 py-1 bg-muted/50">{r.status}</Badge>
      </div>

      <div className="grid grid-cols-2 gap-y-6 text-sm">
        <div>
          <p className="text-muted-foreground text-xs uppercase tracking-wider mb-1">Created By</p>
          <p>{r.created_by}</p>
          <p className="text-xs text-muted-foreground">{fmtDate(r.created_at)}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs uppercase tracking-wider mb-1">Approved By</p>
          <p>{r.approved_by || "—"}</p>
          <p className="text-xs text-muted-foreground">{fmtDate(r.approved_at)}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs uppercase tracking-wider mb-1">Effective Period</p>
          <p>{fmtDate(r.effective_from)}</p>
          <p className="text-xs text-muted-foreground">until {r.effective_until ? fmtDate(r.effective_until) : "present"}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs uppercase tracking-wider mb-1">Enabled Symbols</p>
          <p className="text-xl font-medium">{r.enabled_symbol_count}</p>
        </div>
      </div>
      
      <div className="pt-4 border-t">
        <p className="text-muted-foreground text-xs uppercase tracking-wider mb-2">Immutable Hash</p>
        <code className="text-xs bg-muted/30 p-2 rounded block break-all font-mono">
          {r.exact_set_hash || "hash_pending"}
        </code>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="rounded-md border bg-muted/10 p-4">
          <p className="text-xs uppercase tracking-wider text-muted-foreground">Mapping coverage</p>
          <p className="mt-1 text-lg font-semibold" data-testid="text-history-mapping-coverage">
            {coverageQ.data ? `${coverageQ.data.mapped} / ${coverageQ.data.total} mapped` : "Not available"}
          </p>
          <p className="text-xs text-muted-foreground">{coverageQ.data?.complete ? "Complete at the last server check." : "No complete mapping proof is available."}</p>
        </div>
        <div className="rounded-md border bg-muted/10 p-4">
          <p className="text-xs uppercase tracking-wider text-muted-foreground">Difference from prior committed revision</p>
          <p className="mt-1 text-lg font-semibold" data-testid="text-history-diff-summary">
            {previousVersion && diffQ.data
              ? `+${diffQ.data.added.length} · −${diffQ.data.removed.length} · ${diffQ.data.changed.length} changed`
              : "No prior revision available"}
          </p>
          <p className="text-xs text-muted-foreground">This immutable detail never exposes mutation controls.</p>
        </div>
      </div>

      <div className="space-y-2 border-t pt-4">
        <p className="text-sm font-medium">Exact member snapshot</p>
        <div className="max-h-44 overflow-auto rounded-md border">
          <Table>
            <TableHeader><TableRow><TableHead>Symbol</TableHead><TableHead>Exchange</TableHead><TableHead>Mapping</TableHead><TableHead>Enabled</TableHead></TableRow></TableHeader>
            <TableBody>
              {membersQ.isLoading ? <TableRow><TableCell colSpan={4} className="py-4 text-center text-muted-foreground">Loading immutable members…</TableCell></TableRow> : null}
              {!membersQ.isLoading && !(membersQ.data?.revision.members?.length) ? <TableRow><TableCell colSpan={4} className="py-4 text-center text-muted-foreground">No member snapshot available.</TableCell></TableRow> : null}
              {membersQ.data?.revision.members?.map((member) => (
                <TableRow key={member.id}>
                  <TableCell className="font-mono">{member.symbol}</TableCell>
                  <TableCell>{member.exchange}</TableCell>
                  <TableCell>{member.mapping_status}</TableCell>
                  <TableCell>{member.enabled ? "Enabled" : "Disabled"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>

      <div className="space-y-2 border-t pt-4">
        <p className="text-sm font-medium">Relevant audit events</p>
        <div className="max-h-32 overflow-auto rounded-md border p-2 text-xs">
          {auditQ.isLoading ? <p className="text-muted-foreground">Loading audit context…</p> : null}
          {!auditQ.isLoading && !auditQ.data?.events.filter((event) => event.new_version === version || event.old_version === version).length ? <p className="text-muted-foreground">No linked audit events.</p> : null}
          {auditQ.data?.events.filter((event) => event.new_version === version || event.old_version === version).map((event) => (
            <p key={event.id} className="border-b border-border/40 py-1 last:border-0">{fmtDate(event.occurred_at)} · {event.action} · {event.symbol ?? `v${event.new_version ?? event.old_version}`}</p>
          ))}
        </div>
      </div>
    </div>
  );
}

function AuditLogTab() {
  const { data, isLoading } = useAudit();
  
  return (
    <div className="h-full flex flex-col">
      <ScrollArea className="flex-1">
        <Table>
          <TableHeader className="bg-muted/50 sticky top-0">
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Target</TableHead>
              <TableHead>Details</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center py-8 text-muted-foreground">Loading audit events...</TableCell>
              </TableRow>
            ) : !data?.events?.length ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center py-8 text-muted-foreground">No events recorded.</TableCell>
              </TableRow>
            ) : (
              data.events.map(ev => (
                <TableRow key={ev.id} className="text-sm">
                  <TableCell className="whitespace-nowrap text-muted-foreground">{fmtDate(ev.occurred_at)}</TableCell>
                  <TableCell className="font-medium">{ev.actor}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className="font-mono text-[10px]">{ev.action}</Badge>
                  </TableCell>
                  <TableCell>
                    {ev.symbol ? (
                      <span className="font-mono">{ev.symbol}</span>
                    ) : ev.new_version ? (
                      <span>v{ev.new_version}</span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground max-w-[250px] truncate" title={ev.notes || ""}>
                    {ev.notes || "—"}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </ScrollArea>
    </div>
  );
}
