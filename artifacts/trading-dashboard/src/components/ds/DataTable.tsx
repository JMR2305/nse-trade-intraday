/**
 * DataTable.tsx — DS Phase 9.7
 * Standardised data table with search, sort, pagination, and column chooser.
 * READ-ONLY · UI ONLY
 */
import React, { useState, useMemo, useCallback } from "react";
import { Search, ChevronUp, ChevronDown, ChevronsUpDown, Download, Columns, ChevronLeft, ChevronRight } from "lucide-react";
import { TEXT, SURFACE, FONT_SIZE, FONT_WEIGHT } from "@/lib/designTokens";

export type SortDir = "asc" | "desc" | null;

export interface TableColumn<T = Record<string, unknown>> {
  key:       string;
  label:     string;
  sortable?: boolean;
  width?:    number | string;
  hidden?:   boolean;
  render?:   (value: unknown, row: T, rowIndex: number) => React.ReactNode;
}

interface DataTableProps<T extends Record<string, unknown>> {
  columns:      TableColumn<T>[];
  data:         T[];
  rowKey?:      (row: T, i: number) => string;
  pageSize?:    number;
  searchable?:  boolean;
  searchKeys?:  string[];
  exportable?:  boolean;
  exportName?:  string;
  columnChooser?: boolean;
  emptyLabel?:  string;
  loading?:     boolean;
  compact?:     boolean;
  style?:       React.CSSProperties;
  onRowClick?:  (row: T) => void;
}

function SortIcon({ dir }: { dir: SortDir }) {
  if (dir === "asc")  return <ChevronUp   size={12} aria-hidden="true" />;
  if (dir === "desc") return <ChevronDown  size={12} aria-hidden="true" />;
  return <ChevronsUpDown size={11} color={TEXT.muted} aria-hidden="true" />;
}

export function DataTable<T extends Record<string, unknown>>({
  columns, data, rowKey, pageSize = 20, searchable = true, searchKeys,
  exportable = true, exportName = "data", columnChooser = true,
  emptyLabel = "No data available", loading = false, compact = false, style, onRowClick,
}: DataTableProps<T>) {
  const [search,      setSearch]      = useState("");
  const [sortKey,     setSortKey]     = useState<string | null>(null);
  const [sortDir,     setSortDir]     = useState<SortDir>(null);
  const [page,        setPage]        = useState(1);
  const [hiddenCols,  setHiddenCols]  = useState<Set<string>>(() => new Set(columns.filter(c => c.hidden).map(c => c.key)));
  const [showChooser, setShowChooser] = useState(false);

  const visibleCols = useMemo(() => columns.filter(c => !hiddenCols.has(c.key)), [columns, hiddenCols]);

  const keys = searchKeys ?? columns.map(c => c.key);

  // Search filter
  const filtered = useMemo(() => {
    if (!search.trim()) return data;
    const q = search.toLowerCase();
    return data.filter(row => keys.some(k => String(row[k] ?? "").toLowerCase().includes(q)));
  }, [data, search, keys]);

  // Sort
  const sorted = useMemo(() => {
    if (!sortKey || !sortDir) return filtered;
    return [...filtered].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      const cmp = typeof av === "number" && typeof bv === "number"
        ? av - bv
        : String(av ?? "").localeCompare(String(bv ?? ""));
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [filtered, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage   = Math.min(page, totalPages);
  const pageData   = sorted.slice((safePage - 1) * pageSize, safePage * pageSize);

  const handleSort = useCallback((key: string) => {
    if (sortKey === key) {
      setSortDir(d => d === "asc" ? "desc" : d === "desc" ? null : "asc");
      if (sortDir === "desc") setSortKey(null);
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
    setPage(1);
  }, [sortKey, sortDir]);

  const handleExport = useCallback(() => {
    const headers = visibleCols.map(c => c.label);
    const rows    = sorted.map(row => visibleCols.map(c => String(row[c.key] ?? "")));
    const csv     = [headers, ...rows].map(r => r.map(v => `"${v.replace(/"/g, '""')}"`).join(",")).join("\n");
    const a       = document.createElement("a");
    a.href        = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download    = `${exportName}_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
  }, [visibleCols, sorted, exportName]);

  const rowH = compact ? 36 : 44;

  return (
    <div style={{ ...style }}>
      {/* Toolbar */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
        {searchable && (
          <div style={{ position: "relative", flex: "1 1 200px", minWidth: 160 }}>
            <Search size={13} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: TEXT.muted, pointerEvents: "none" }} aria-hidden="true" />
            <input
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1); }}
              placeholder="Search…"
              aria-label="Search table"
              style={{
                width: "100%", boxSizing: "border-box",
                paddingLeft: 30, paddingRight: 10,
                height: 32, fontSize: FONT_SIZE.sm,
                background: SURFACE.card, border: `1px solid ${SURFACE.border}`,
                borderRadius: 6, color: TEXT.primary, outline: "none",
              }}
            />
          </div>
        )}
        <div style={{ display: "flex", gap: 6 }}>
          {columnChooser && (
            <div style={{ position: "relative" }}>
              <button
                onClick={() => setShowChooser(v => !v)}
                aria-label="Choose columns"
                aria-expanded={showChooser}
                style={{
                  display: "flex", alignItems: "center", gap: 5,
                  height: 32, padding: "0 10px", fontSize: FONT_SIZE.xs,
                  background: SURFACE.card, border: `1px solid ${SURFACE.border}`,
                  borderRadius: 6, color: TEXT.secondary, cursor: "pointer",
                }}
              >
                <Columns size={12} aria-hidden="true" /> Columns
              </button>
              {showChooser && (
                <div
                  style={{
                    position: "absolute", top: 36, right: 0, zIndex: 50,
                    background: "#151b2b", border: `1px solid ${SURFACE.border}`,
                    borderRadius: 8, padding: "8px", minWidth: 180,
                    boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
                  }}
                  role="dialog" aria-label="Column chooser"
                >
                  {columns.map(c => (
                    <label
                      key={c.key}
                      style={{
                        display: "flex", alignItems: "center", gap: 8,
                        padding: "5px 8px", cursor: "pointer",
                        fontSize: FONT_SIZE.sm, color: TEXT.secondary,
                        borderRadius: 4,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={!hiddenCols.has(c.key)}
                        onChange={() => setHiddenCols(s => {
                          const n = new Set(s);
                          n.has(c.key) ? n.delete(c.key) : n.add(c.key);
                          return n;
                        })}
                        aria-label={`Toggle ${c.label} column`}
                      />
                      {c.label}
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}
          {exportable && (
            <button
              onClick={handleExport}
              aria-label="Export table as CSV"
              style={{
                display: "flex", alignItems: "center", gap: 5,
                height: 32, padding: "0 10px", fontSize: FONT_SIZE.xs,
                background: SURFACE.card, border: `1px solid ${SURFACE.border}`,
                borderRadius: 6, color: TEXT.secondary, cursor: "pointer",
              }}
            >
              <Download size={12} aria-hidden="true" /> Export
            </button>
          )}
        </div>
        <span style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted, marginLeft: "auto" }}>
          {filtered.length} row{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Table */}
      <div style={{ overflowX: "auto", borderRadius: 8, border: `1px solid ${SURFACE.border}` }}>
        <table
          style={{ width: "100%", borderCollapse: "collapse" }}
          role="table"
          aria-label="Data table"
          aria-rowcount={sorted.length}
        >
          <thead>
            <tr style={{ background: SURFACE.card }}>
              {visibleCols.map(col => (
                <th
                  key={col.key}
                  scope="col"
                  onClick={col.sortable ? () => handleSort(col.key) : undefined}
                  aria-sort={
                    sortKey === col.key
                      ? sortDir === "asc" ? "ascending" : sortDir === "desc" ? "descending" : "none"
                      : undefined
                  }
                  style={{
                    padding:      compact ? "6px 12px" : "9px 14px",
                    textAlign:    "left",
                    fontSize:     FONT_SIZE.xs,
                    fontWeight:   FONT_WEIGHT.semibold,
                    color:        TEXT.muted,
                    letterSpacing:"0.04em",
                    textTransform:"uppercase",
                    borderBottom: `1px solid ${SURFACE.border}`,
                    whiteSpace:   "nowrap",
                    cursor:       col.sortable ? "pointer" : "default",
                    userSelect:   "none",
                    width:        col.width,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    {col.label}
                    {col.sortable && <SortIcon dir={sortKey === col.key ? sortDir : null} />}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: Math.min(5, pageSize) }).map((_, i) => (
                  <tr key={i} aria-hidden="true">
                    {visibleCols.map(c => (
                      <td key={c.key} style={{ padding: compact ? "6px 12px" : "9px 14px", borderBottom: `1px solid ${SURFACE.borderSub}` }}>
                        <div style={{ height: 12, background: SURFACE.card, borderRadius: 4, animation: "aq-skeleton-shimmer 1.5s infinite" }} />
                      </td>
                    ))}
                  </tr>
                ))
              : pageData.length === 0
                ? (
                    <tr>
                      <td colSpan={visibleCols.length} style={{ padding: "32px 14px", textAlign: "center", color: TEXT.muted, fontSize: FONT_SIZE.sm }}>
                        {emptyLabel}
                      </td>
                    </tr>
                  )
                : pageData.map((row, ri) => (
                    <tr
                      key={rowKey ? rowKey(row, ri) : ri}
                      onClick={onRowClick ? () => onRowClick(row) : undefined}
                      style={{
                        height:     rowH,
                        borderBottom:`1px solid ${SURFACE.borderSub}`,
                        cursor:     onRowClick ? "pointer" : "default",
                        transition: "background 150ms ease",
                      }}
                      onMouseEnter={e => { (e.currentTarget as HTMLTableRowElement).style.background = SURFACE.cardHover; }}
                      onMouseLeave={e => { (e.currentTarget as HTMLTableRowElement).style.background = ""; }}
                      aria-rowindex={(safePage - 1) * pageSize + ri + 1}
                    >
                      {visibleCols.map(col => (
                        <td
                          key={col.key}
                          style={{ padding: compact ? "0 12px" : "0 14px", fontSize: FONT_SIZE.sm, color: TEXT.secondary, verticalAlign: "middle" }}
                        >
                          {col.render ? col.render(row[col.key], row, ri) : String(row[col.key] ?? "—")}
                        </td>
                      ))}
                    </tr>
                  ))
            }
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 10 }}>
          <span style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted }}>
            Page {safePage} of {totalPages}
          </span>
          <div style={{ display: "flex", gap: 4 }}>
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={safePage === 1}
              aria-label="Previous page"
              style={{
                width: 28, height: 28, borderRadius: 5, display: "flex", alignItems: "center", justifyContent: "center",
                background: SURFACE.card, border: `1px solid ${SURFACE.border}`, cursor: safePage === 1 ? "not-allowed" : "pointer",
                color: safePage === 1 ? TEXT.disabled : TEXT.secondary, fontSize: FONT_SIZE.sm,
              }}
            >
              <ChevronLeft size={13} />
            </button>
            {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
              const p = safePage <= 3 ? i + 1 : safePage + i - 2;
              if (p < 1 || p > totalPages) return null;
              return (
                <button
                  key={p}
                  onClick={() => setPage(p)}
                  aria-label={`Page ${p}`}
                  aria-current={p === safePage ? "page" : undefined}
                  style={{
                    width: 28, height: 28, borderRadius: 5,
                    background: p === safePage ? "#6366F1" : SURFACE.card,
                    border: `1px solid ${p === safePage ? "#6366F1" : SURFACE.border}`,
                    color: p === safePage ? "#fff" : TEXT.secondary,
                    cursor: "pointer", fontSize: FONT_SIZE.xs, fontWeight: p === safePage ? FONT_WEIGHT.semibold : FONT_WEIGHT.normal,
                  }}
                >
                  {p}
                </button>
              );
            })}
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={safePage === totalPages}
              aria-label="Next page"
              style={{
                width: 28, height: 28, borderRadius: 5, display: "flex", alignItems: "center", justifyContent: "center",
                background: SURFACE.card, border: `1px solid ${SURFACE.border}`, cursor: safePage === totalPages ? "not-allowed" : "pointer",
                color: safePage === totalPages ? TEXT.disabled : TEXT.secondary,
              }}
            >
              <ChevronRight size={13} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
