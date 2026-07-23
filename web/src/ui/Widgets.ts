// Immediate-mode widget toolkit, drawn on the canvas to match ui/widgets.py.
//
// Each widget is a method called every frame inside a screen's render(); it
// draws itself and returns its interaction result (clicked / new value). The
// UI object holds the small amount of retained state interaction needs:
// hover is recomputed per frame, but focus (text input), drag (slider) and
// open-dropdown must persist across frames.
//
// Dropdowns: their open list must paint above sibling widgets, so the open
// list's *drawing* is deferred to a popup pass (flushPopups) after the screen
// draws. Its *interaction* is resolved at the top of the next frame against the
// geometry captured while open — and that press is marked consumed so widgets
// beneath the list don't also react (the classic immediate-mode overlap fix).

import { Input } from "../core/Input";
import * as T from "./theme";
import { drawText, measure } from "./Text";

export type Choice = [string, string]; // [value, label]

interface DropdownGeom {
  x: number;
  y: number;
  w: number;
  itemH: number;
  count: number;
  maxVisible: number;
  openUp: boolean;
}

interface DropdownState {
  selectedIndex: number;
  scroll: number;
  geom: DropdownGeom | null;
}

export class UI {
  ctx: CanvasRenderingContext2D;
  input: Input;
  w = 0; // CSS pixels
  h = 0;
  dpr = 1; // device pixel ratio (for screens that draw world layers)
  time = 0; // seconds, for cursor blink

  // Retained interaction state
  activeInput: string | null = null;
  activeDrag: string | null = null;
  openDropdown: string | null = null;

  private dropdowns = new Map<string, DropdownState>();
  private popups: Array<() => void> = [];
  pressConsumed = false; // a widget/popup claimed this frame's press
  private inputClaimed = false; // a text input claimed this frame's press

  constructor(ctx: CanvasRenderingContext2D, input: Input) {
    this.ctx = ctx;
    this.input = input;
  }

  beginFrame(w: number, h: number, dpr: number, dt: number): void {
    this.w = w;
    this.h = h;
    this.dpr = dpr;
    this.time += dt;
    this.popups.length = 0;
    this.pressConsumed = false;
    this.inputClaimed = false;

    // Resolve interaction for an open dropdown first, on top of everything.
    if (this.openDropdown) {
      const st = this.dropdowns.get(this.openDropdown);
      if (st && st.geom) this.resolveOpenDropdown(st);
      else this.openDropdown = null;
    }
  }

  endFrame(): void {
    // Click outside any focused text input clears focus.
    if (this.input.pressed && !this.inputClaimed && !this.pressConsumed) {
      this.activeInput = null;
    }
    if (!this.input.mouseDown) this.activeDrag = null;
  }

  /** Draw deferred popups (open dropdown lists) above the rest of the UI. */
  flushPopups(): void {
    for (const p of this.popups) p();
    this.popups.length = 0;
  }

  // -- drawing helpers --------------------------------------------------

  private pointIn(x: number, y: number, w: number, h: number): boolean {
    const { mouseX: mx, mouseY: my } = this.input;
    return mx >= x && mx <= x + w && my >= y && my <= y + h;
  }

  fillRect(x: number, y: number, w: number, h: number, color: T.RGB | T.RGBA): void {
    this.ctx.fillStyle = T.rgb(color);
    this.ctx.fillRect(x, y, w, h);
  }

  roundRectPath(x: number, y: number, w: number, h: number, r: number): void {
    const ctx = this.ctx;
    const rr = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.arcTo(x + w, y, x + w, y + h, rr);
    ctx.arcTo(x + w, y + h, x, y + h, rr);
    ctx.arcTo(x, y + h, x, y, rr);
    ctx.arcTo(x, y, x + w, y, rr);
    ctx.closePath();
  }

  panel(x: number, y: number, w: number, h: number, radius = 8): void {
    this.roundRectPath(x, y, w, h, radius);
    this.ctx.fillStyle = T.rgb(T.PANEL_BG);
    this.ctx.fill();
    this.ctx.strokeStyle = T.rgb(T.PANEL_BORDER);
    this.ctx.lineWidth = 1;
    this.ctx.stroke();
  }

  // -- widgets ----------------------------------------------------------

  button(
    id: string,
    x: number,
    y: number,
    w: number,
    h: number,
    label: string,
    opts: { enabled?: boolean; fontSize?: number } = {},
  ): boolean {
    void id; // buttons are stateless; id kept for call-site readability
    const enabled = opts.enabled ?? true;
    const fontSize = opts.fontSize ?? T.BTN_FONT_SIZE;
    const hover = enabled && !this.pressConsumed && this.pointIn(x, y, w, h);
    const held = hover && this.input.mouseDown;
    let bg: T.RGB = T.BTN_NORMAL;
    if (!enabled) bg = [28, 28, 38];
    else if (held) bg = T.BTN_PRESS;
    else if (hover) bg = T.BTN_HOVER;

    this.roundRectPath(x, y, w, h, T.BTN_BORDER_RADIUS);
    this.ctx.fillStyle = T.rgb(bg);
    this.ctx.fill();
    this.ctx.strokeStyle = T.rgb(T.BTN_BORDER);
    this.ctx.lineWidth = 1;
    this.ctx.stroke();

    drawText(this.ctx, label, x + w / 2, y + h / 2, {
      size: fontSize,
      color: enabled ? T.BTN_TEXT : T.BTN_DISABLED_TEXT,
      align: "center",
      baseline: "middle",
    });

    // A click is a mouse-up over the button this frame.
    if (enabled && hover && this.input.released) {
      this.pressConsumed = true;
      return true;
    }
    return false;
  }

  checkbox(id: string, x: number, y: number, label: string, checked: boolean, enabled = true): boolean {
    void id;
    const box = 18;
    const hover = enabled && !this.pressConsumed && this.pointIn(x, y, box, box);
    this.fillRect(x, y, box, box, enabled ? T.CB_BOX : T.CB_DISABLED);
    this.ctx.strokeStyle = T.rgb(T.CB_BORDER);
    this.ctx.lineWidth = 1;
    this.ctx.strokeRect(x + 0.5, y + 0.5, box - 1, box - 1);
    if (checked) {
      const ctx = this.ctx;
      ctx.strokeStyle = T.rgb(T.CB_CHECK);
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x + 4, y + 9);
      ctx.lineTo(x + 8, y + 13);
      ctx.lineTo(x + 14, y + 5);
      ctx.stroke();
    }
    drawText(this.ctx, label, x + box + 8, y + box / 2, {
      size: T.CONTENT_FONT_SIZE,
      color: enabled ? T.CONTENT_TEXT : T.CB_DISABLED,
      baseline: "middle",
    });
    void hover;
    if (enabled && hover && this.input.released) {
      this.pressConsumed = true;
      return true; // toggled (caller flips the bound value)
    }
    return false;
  }

  /** Returns the (possibly new) numeric value. */
  slider(
    id: string,
    x: number,
    y: number,
    w: number,
    label: string,
    min: number,
    max: number,
    value: number,
    step = 1,
  ): number {
    const trackY = y + 22;
    const handleR = T.SL_HANDLE_RADIUS;
    drawText(this.ctx, `${label}: ${value}`, x, y, {
      size: T.SL_FONT_SIZE,
      color: T.SL_TEXT_COLOR,
    });
    // Track
    this.fillRect(x, trackY, w, T.SL_HEIGHT, T.SL_TRACK_COLOR);
    const frac = max > min ? (value - min) / (max - min) : 0;
    const fillW = Math.round(frac * w);
    this.fillRect(x, trackY, fillW, T.SL_HEIGHT, T.SL_FILL_COLOR);
    const hx = x + frac * w;
    const hy = trackY + T.SL_HEIGHT / 2;

    // Interaction: start drag on press near track, continue while held.
    const onHandle = this.pointIn(x - handleR, trackY - 6, w + handleR * 2, T.SL_HEIGHT + 12);
    if (!this.pressConsumed && this.input.pressed && onHandle) {
      this.activeDrag = id;
      this.pressConsumed = true;
    }
    let newValue = value;
    if (this.activeDrag === id && this.input.mouseDown) {
      const t = Math.max(0, Math.min(1, (this.input.mouseX - x) / w));
      const raw = min + t * (max - min);
      newValue = Math.round(raw / step) * step;
      newValue = Math.max(min, Math.min(max, newValue));
    }

    // Handle
    this.ctx.beginPath();
    this.ctx.arc(hx, hy, handleR, 0, Math.PI * 2);
    this.ctx.fillStyle = T.rgb(T.SL_HANDLE_COLOR);
    this.ctx.fill();
    return newValue;
  }

  /** Mutually exclusive row. Returns the selected index. */
  toggleGroup(
    id: string,
    x: number,
    y: number,
    choices: Choice[],
    selectedIndex: number,
    btnW = 73,
    btnH = 26,
  ): number {
    void id;
    let result = selectedIndex;
    for (let i = 0; i < choices.length; i++) {
      const bx = x + i * (btnW + 4);
      const active = i === selectedIndex;
      const hover = !this.pressConsumed && this.pointIn(bx, y, btnW, btnH);
      this.fillRect(bx, y, btnW, btnH, active ? T.TG_ACTIVE : T.TG_INACTIVE);
      this.ctx.strokeStyle = T.rgb(T.TG_BORDER);
      this.ctx.lineWidth = 1;
      this.ctx.strokeRect(bx + 0.5, y + 0.5, btnW - 1, btnH - 1);
      drawText(this.ctx, choices[i][1], bx + btnW / 2, y + btnH / 2, {
        size: T.TG_FONT_SIZE,
        color: T.TG_TEXT,
        align: "center",
        baseline: "middle",
      });
      if (hover && this.input.released) {
        result = i;
        this.pressConsumed = true;
      }
    }
    return result;
  }

  /** Editable text field. Returns the (possibly new) text. */
  textInput(
    id: string,
    x: number,
    y: number,
    w: number,
    value: string,
    opts: { placeholder?: string; maxLen?: number; h?: number } = {},
  ): string {
    const h = opts.h ?? T.DD_HEIGHT;
    const maxLen = opts.maxLen ?? 64;
    const focused = this.activeInput === id;
    const hover = !this.pressConsumed && this.pointIn(x, y, w, h);

    if (!this.pressConsumed && this.input.pressed && hover) {
      this.activeInput = id;
      this.inputClaimed = true;
      this.pressConsumed = true;
    } else if (focused && this.input.pressed && hover) {
      this.inputClaimed = true;
    }

    this.fillRect(x, y, w, h, focused ? T.TI_ACTIVE_BG : T.TI_BG);
    this.ctx.strokeStyle = T.rgb(focused ? T.TI_ACTIVE_BORDER : T.TI_BORDER);
    this.ctx.lineWidth = 1;
    this.ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);

    let text = value;
    if (focused) {
      // Apply typed characters and backspace this frame.
      if (this.input.chars) {
        text = (text + this.input.chars).slice(0, maxLen);
      }
      for (const ev of this.input.keysPressed) {
        if (ev.key === "Backspace") text = text.slice(0, -1);
      }
    }

    const display = text || (focused ? "" : opts.placeholder ?? "");
    const isPlaceholder = !text && !focused;
    // Clip text to the box.
    this.ctx.save();
    this.ctx.beginPath();
    this.ctx.rect(x + 4, y, w - 8, h);
    this.ctx.clip();
    drawText(this.ctx, display, x + 6, y + h / 2, {
      size: T.DD_FONT_SIZE,
      color: isPlaceholder ? T.TI_PLACEHOLDER : T.TI_TEXT,
      baseline: "middle",
    });
    // Blinking caret
    if (focused && Math.floor(this.time * 2) % 2 === 0) {
      const cx = x + 6 + measure(this.ctx, text, T.DD_FONT_SIZE);
      this.ctx.strokeStyle = T.rgb(T.TI_TEXT);
      this.ctx.lineWidth = 1;
      this.ctx.beginPath();
      this.ctx.moveTo(cx + 1, y + 6);
      this.ctx.lineTo(cx + 1, y + h - 6);
      this.ctx.stroke();
    }
    this.ctx.restore();
    return text;
  }

  /** Dropdown. Returns the (possibly new) selected index. */
  dropdown(
    id: string,
    x: number,
    y: number,
    w: number,
    choices: Choice[],
    selectedIndex: number,
    opts: { maxVisible?: number; enabled?: boolean } = {},
  ): number {
    const enabled = opts.enabled ?? true;
    const maxVisible = opts.maxVisible ?? 8;
    const h = T.DD_HEIGHT;
    let st = this.dropdowns.get(id);
    if (!st) {
      st = { selectedIndex, scroll: 0, geom: null };
      this.dropdowns.set(id, st);
    }
    // Keep external selection authoritative unless we changed it via the list.
    st.selectedIndex = selectedIndex;

    const isOpen = this.openDropdown === id;
    const hover = enabled && !this.pressConsumed && this.pointIn(x, y, w, h);

    // Closed box
    this.fillRect(x, y, w, h, hover ? T.DD_HOVER : T.DD_BG);
    this.ctx.strokeStyle = T.rgb(T.DD_BORDER);
    this.ctx.lineWidth = 1;
    this.ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
    const label = choices[selectedIndex]?.[1] ?? "";
    this.ctx.save();
    this.ctx.beginPath();
    this.ctx.rect(x + 4, y, w - 24, h);
    this.ctx.clip();
    drawText(this.ctx, label, x + 8, y + h / 2, {
      size: T.DD_FONT_SIZE,
      color: enabled ? T.DD_TEXT : [110, 110, 130],
      baseline: "middle",
    });
    this.ctx.restore();
    // Caret triangle
    const tx = x + w - 14;
    const ty = y + h / 2;
    this.ctx.fillStyle = T.rgb(T.DD_TEXT);
    this.ctx.beginPath();
    this.ctx.moveTo(tx - 4, ty - 2);
    this.ctx.lineTo(tx + 4, ty - 2);
    this.ctx.lineTo(tx, ty + 3);
    this.ctx.closePath();
    this.ctx.fill();

    // Toggle open on click of the header.
    if (enabled && hover && this.input.released && !isOpen) {
      this.openDropdown = id;
      this.pressConsumed = true;
    } else if (isOpen && hover && this.input.released) {
      this.openDropdown = null;
      this.pressConsumed = true;
    }

    if (this.openDropdown === id) {
      // Capture/refresh geometry and defer drawing the list.
      const count = choices.length;
      const visible = Math.min(maxVisible, count);
      const listH = visible * h;
      const openUp = y + h + listH > this.h;
      st.geom = { x, y, w, itemH: h, count, maxVisible: visible, openUp };
      this.popups.push(() => this.drawDropdownList(choices, st!));
    }

    return st.selectedIndex;
  }

  private drawDropdownList(choices: Choice[], st: DropdownState): void {
    const g = st.geom!;
    const startY = g.openUp ? g.y - g.maxVisible * g.itemH : g.y + g.itemH;
    const first = st.scroll;
    for (let i = 0; i < g.maxVisible; i++) {
      const ci = first + i;
      if (ci >= g.count) break;
      const iy = startY + i * g.itemH;
      const hover = this.pointIn(g.x, iy, g.w, g.itemH);
      this.fillRect(g.x, iy, g.w, g.itemH, hover ? T.DD_HOVER : T.DD_BG);
      this.ctx.strokeStyle = T.rgb(T.DD_BORDER);
      this.ctx.lineWidth = 1;
      this.ctx.strokeRect(g.x + 0.5, iy + 0.5, g.w - 1, g.itemH - 1);
      this.ctx.save();
      this.ctx.beginPath();
      this.ctx.rect(g.x + 4, iy, g.w - 8, g.itemH);
      this.ctx.clip();
      drawText(this.ctx, choices[ci][1], g.x + 8, iy + g.itemH / 2, {
        size: T.DD_FONT_SIZE,
        color: T.DD_TEXT,
        baseline: "middle",
      });
      this.ctx.restore();
    }
  }

  private resolveOpenDropdown(st: DropdownState): void {
    const g = st.geom;
    if (!g) {
      this.openDropdown = null;
      return;
    }
    // Scroll the list while hovering it.
    const startY = g.openUp ? g.y - g.maxVisible * g.itemH : g.y + g.itemH;
    const listRect = { x: g.x, y: startY, w: g.w, h: g.maxVisible * g.itemH };
    const overList =
      this.input.mouseX >= listRect.x &&
      this.input.mouseX <= listRect.x + listRect.w &&
      this.input.mouseY >= listRect.y &&
      this.input.mouseY <= listRect.y + listRect.h;
    if (overList && this.input.wheel !== 0) {
      const maxScroll = Math.max(0, g.count - g.maxVisible);
      st.scroll = Math.max(0, Math.min(maxScroll, st.scroll + this.input.wheel));
    }
    if (this.input.pressed) {
      if (overList) {
        const idx = st.scroll + Math.floor((this.input.mouseY - startY) / g.itemH);
        if (idx >= 0 && idx < g.count) st.selectedIndex = idx;
        this.openDropdown = null;
        this.pressConsumed = true;
      } else {
        // Click away from the list — the header itself is handled in dropdown();
        // only close here if the press is also outside the header box.
        const overHeader = this.pointIn(g.x, g.y, g.w, g.itemH);
        if (!overHeader) {
          this.openDropdown = null;
          this.pressConsumed = true;
        }
      }
    }
  }
}
