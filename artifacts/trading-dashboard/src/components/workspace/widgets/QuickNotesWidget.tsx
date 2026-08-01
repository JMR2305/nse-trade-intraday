/**
 * QuickNotesWidget — localStorage only, no API calls.
 * Personal trading notes, reminders, observations.
 */
import React, { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Plus, Trash2 } from "lucide-react";

interface Note { id: string; text: string; ts: number; }

const NOTES_KEY = "apexquant_quick_notes";

function readNotes(): Note[] {
  try { return JSON.parse(localStorage.getItem(NOTES_KEY) || "[]"); }
  catch { return []; }
}
function writeNotes(notes: Note[]) {
  try { localStorage.setItem(NOTES_KEY, JSON.stringify(notes)); }
  catch {}
}

interface Props { compact?: boolean; }

export default function QuickNotesWidget({ compact }: Props) {
  const [notes, setNotes] = useState<Note[]>(() => readNotes());
  const [draft, setDraft]  = useState("");
  const [adding, setAdding] = useState(false);

  const addNote = () => {
    const text = draft.trim();
    if (!text) { setAdding(false); return; }
    const next = [{ id: Math.random().toString(36).slice(2), text, ts: Date.now() }, ...notes];
    setNotes(next);
    writeNotes(next);
    setDraft("");
    setAdding(false);
  };

  const removeNote = (id: string) => {
    const next = notes.filter((n) => n.id !== id);
    setNotes(next);
    writeNotes(next);
  };

  const limit = compact ? 2 : 5;

  return (
    <div className="space-y-1.5 h-full flex flex-col">
      {/* Add note */}
      {adding ? (
        <div className="flex gap-1.5">
          <textarea
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); addNote(); }
              if (e.key === "Escape") { setAdding(false); setDraft(""); }
            }}
            placeholder="Type a note… (Enter to save)"
            className="flex-1 text-[11px] bg-muted/30 border border-border/40 rounded px-2 py-1.5 resize-none text-foreground/80 placeholder:text-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-primary/30"
            rows={2}
          />
          <button onClick={addNote} className="px-2 py-1 rounded bg-primary/20 text-primary text-[10px] font-semibold hover:bg-primary/30 transition-colors">
            Save
          </button>
        </div>
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="flex items-center gap-1.5 text-[11px] text-muted-foreground/50 hover:text-muted-foreground transition-colors px-1"
        >
          <Plus className="w-3.5 h-3.5" />
          Add note
        </button>
      )}

      {/* Notes list */}
      <div className="flex-1 space-y-1 overflow-y-auto">
        {notes.length === 0 && (
          <p className="text-[10px] text-muted-foreground/30 italic px-1">No notes yet</p>
        )}
        {notes.slice(0, limit).map((note) => (
          <div key={note.id} className="group relative flex items-start gap-1.5 px-2 py-1.5 rounded bg-amber-500/8 hover:bg-amber-500/12 border border-amber-500/15 transition-colors">
            <span className="flex-1 text-[11px] text-foreground/75 leading-relaxed break-words">{note.text}</span>
            <button
              onClick={() => removeNote(note.id)}
              className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground/40 hover:text-red-400 mt-0.5"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </div>
        ))}
        {notes.length > limit && (
          <p className="text-[10px] text-muted-foreground/40 text-center">
            +{notes.length - limit} more notes
          </p>
        )}
      </div>
    </div>
  );
}
