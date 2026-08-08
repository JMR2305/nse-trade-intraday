// @vitest-environment jsdom
/**
 * LayoutManager.test.tsx — Phase 25.1 Part 11 dashboard customization.
 *
 * Verifies the localStorage-backed layout hook + <SectionShell> chrome:
 *  - hidden section collapses to a restore chip (customizing) / renders nothing
 *  - pinned sections float to the top of the applied order
 *  - reset restores default order + visibility
 */
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup, renderHook } from "@testing-library/react";
import {
  useLayoutManager, SectionShell, type SectionDef, type LayoutManager,
} from "../LayoutManager";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const DEFS: SectionDef[] = [
  { id: "alpha", label: "Alpha" },
  { id: "beta", label: "Beta" },
  { id: "gamma", label: "Gamma" },
];

describe("useLayoutManager", () => {
  it("defaults to all sections visible + unpinned in declaration order", () => {
    const { result } = renderHook(() => useLayoutManager(DEFS));
    expect(result.current.order).toEqual(["alpha", "beta", "gamma"]);
    expect(result.current.isHidden("alpha")).toBe(false);
    expect(result.current.isPinned("alpha")).toBe(false);
  });

  it("pinned sections sort first (stable within groups)", () => {
    const { result } = renderHook(() => useLayoutManager(DEFS));
    act(() => result.current.togglePin("gamma"));
    expect(result.current.order).toEqual(["gamma", "alpha", "beta"]);
    expect(result.current.isPinned("gamma")).toBe(true);
  });

  it("toggleHide flags a section hidden and lists it in hiddenSections", () => {
    const { result } = renderHook(() => useLayoutManager(DEFS));
    act(() => result.current.toggleHide("beta"));
    expect(result.current.isHidden("beta")).toBe(true);
    expect(result.current.hiddenSections.map((s) => s.id)).toContain("beta");
  });

  it("moveDown / moveUp reorders sections", () => {
    const { result } = renderHook(() => useLayoutManager(DEFS));
    act(() => result.current.moveDown("alpha"));
    expect(result.current.order).toEqual(["beta", "alpha", "gamma"]);
    act(() => result.current.moveUp("alpha"));
    expect(result.current.order).toEqual(["alpha", "beta", "gamma"]);
  });

  it("reset restores defaults after pin + hide + reorder", () => {
    const { result } = renderHook(() => useLayoutManager(DEFS));
    act(() => { result.current.togglePin("gamma"); result.current.toggleHide("beta"); });
    expect(result.current.order[0]).toBe("gamma");
    act(() => result.current.reset());
    expect(result.current.order).toEqual(["alpha", "beta", "gamma"]);
    expect(result.current.isHidden("beta")).toBe(false);
    expect(result.current.isPinned("gamma")).toBe(false);
  });

  it("persists prefs to localStorage under mc-layout-v1", () => {
    const { result } = renderHook(() => useLayoutManager(DEFS));
    act(() => result.current.togglePin("beta"));
    const raw = localStorage.getItem("mc-layout-v1");
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed.find((p: { id: string }) => p.id === "beta").pinned).toBe(true);
  });
});

// ── SectionShell rendering ────────────────────────────────────────────────────

// Renders a live manager + one SectionShell so we can drive real interactions.
function Harness({ id, label, onMgr }: { id: string; label: string; onMgr?: (m: LayoutManager) => void }) {
  const mgr = useLayoutManager(DEFS);
  onMgr?.(mgr);
  return (
    <div>
      <button data-testid="do-customize" onClick={mgr.toggleCustomizing}>c</button>
      <button data-testid="do-hide" onClick={() => mgr.toggleHide(id)}>h</button>
      <SectionShell id={id} label={label} mgr={mgr}>
        <div data-testid="child">child-content</div>
      </SectionShell>
    </div>
  );
}

describe("SectionShell", () => {
  it("renders children plainly when visible and not customizing", () => {
    render(<Harness id="alpha" label="Alpha" />);
    expect(screen.getByTestId("child")).toBeTruthy();
    expect(screen.getByTestId("mc-section-alpha")).toBeTruthy();
  });

  it("hidden + not customizing renders nothing", () => {
    render(<Harness id="alpha" label="Alpha" />);
    fireEvent.click(screen.getByTestId("do-hide"));
    expect(screen.queryByTestId("child")).toBeNull();
    expect(screen.queryByTestId("mc-section-alpha")).toBeNull();
  });

  it("hidden while customizing collapses to a restore chip and restores", () => {
    render(<Harness id="alpha" label="Alpha" />);
    fireEvent.click(screen.getByTestId("do-customize")); // enter customize
    fireEvent.click(screen.getByTestId("do-hide"));       // hide alpha

    // collapsed chip present, children gone
    expect(screen.getByTestId("mc-section-hidden-alpha")).toBeTruthy();
    expect(screen.queryByTestId("child")).toBeNull();

    // restore brings the section back (now visible + customizing → controls header)
    fireEvent.click(screen.getByTestId("mc-section-restore-alpha"));
    expect(screen.queryByTestId("mc-section-hidden-alpha")).toBeNull();
    expect(screen.getByTestId("child")).toBeTruthy();
  });
});
