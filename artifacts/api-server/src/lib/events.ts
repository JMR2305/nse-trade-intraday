/**
 * events.ts — Phase 11 Live Data Foundation
 * Tiny in-process event bus for SSE fan-out.
 * PAPER TRADING ONLY — research system.
 */
import { EventEmitter } from "events";

export interface AppEvent {
  event: string;                 // e.g. market.quote, market.status, scan.completed
  data: unknown;
  ts: string;                    // ISO timestamp
  id: number;                    // monotonically increasing event id
}

class EventBus extends EventEmitter {
  private nextId = 1;
  private recent: AppEvent[] = [];

  publish(event: string, data: unknown): AppEvent {
    const evt: AppEvent = {
      event,
      data,
      ts: new Date().toISOString(),
      id: this.nextId++,
    };
    this.recent.push(evt);
    if (this.recent.length > 200) this.recent.splice(0, this.recent.length - 200);
    this.emit("event", evt);
    return evt;
  }

  since(lastId: number): AppEvent[] {
    return this.recent.filter((e) => e.id > lastId);
  }
}

export const eventBus = new EventBus();
eventBus.setMaxListeners(100);
