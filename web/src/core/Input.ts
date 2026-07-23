// Per-frame input state collected from DOM events. Immediate-mode widgets read
// this snapshot during draw; deltas (pressed/released/wheel/keysPressed/chars)
// are cleared at the end of each frame by endFrame().

export interface KeyPress {
  key: string;
  ctrl: boolean;
  shift: boolean;
}

export class Input {
  mouseX = 0;
  mouseY = 0;
  mouseDown = false; // left button currently held
  rightDown = false;
  middleDown = false;

  // Edge events for this frame
  pressed = false; // left mousedown happened this frame
  released = false; // left mouseup happened this frame
  rightPressed = false;
  rightReleased = false;
  middlePressed = false;
  middleReleased = false;
  doubleClick = false;
  wheel = 0; // accumulated wheel delta this frame (normalized steps)

  keysDown = new Set<string>(); // currently held (event.key values)
  // keydown events this frame, each with the modifier state captured at the
  // moment of the press (a global modifier snapshot races with key release).
  keysPressed: KeyPress[] = [];
  chars = ""; // printable characters typed this frame

  // Modifier snapshot
  shift = false;
  ctrl = false;

  private canvas: HTMLCanvasElement;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.attach();
  }

  private setMouseFromEvent(e: MouseEvent): void {
    const r = this.canvas.getBoundingClientRect();
    this.mouseX = e.clientX - r.left;
    this.mouseY = e.clientY - r.top;
    this.shift = e.shiftKey;
    this.ctrl = e.ctrlKey || e.metaKey;
  }

  private attach(): void {
    const c = this.canvas;

    c.addEventListener("mousemove", (e) => this.setMouseFromEvent(e));

    c.addEventListener("mousedown", (e) => {
      this.setMouseFromEvent(e);
      if (e.button === 0) {
        this.mouseDown = true;
        this.pressed = true;
      } else if (e.button === 2) {
        this.rightDown = true;
        this.rightPressed = true;
      } else if (e.button === 1) {
        this.middleDown = true;
        this.middlePressed = true;
      }
      c.focus();
    });

    window.addEventListener("mouseup", (e) => {
      if (e.button === 0) {
        this.mouseDown = false;
        this.released = true;
      } else if (e.button === 2) {
        this.rightDown = false;
        this.rightReleased = true;
      } else if (e.button === 1) {
        this.middleDown = false;
        this.middleReleased = true;
      }
    });

    c.addEventListener("dblclick", () => {
      this.doubleClick = true;
    });

    c.addEventListener(
      "wheel",
      (e) => {
        // Normalize to integer steps (deltaY > 0 = scroll down).
        this.wheel += e.deltaY > 0 ? 1 : e.deltaY < 0 ? -1 : 0;
        e.preventDefault();
      },
      { passive: false },
    );

    // Suppress the browser context menu so right-click can be a game command.
    c.addEventListener("contextmenu", (e) => e.preventDefault());

    c.addEventListener("keydown", (e) => {
      this.shift = e.shiftKey;
      this.ctrl = e.ctrlKey || e.metaKey;
      this.keysDown.add(e.key);
      this.keysPressed.push({ key: e.key, ctrl: e.ctrlKey || e.metaKey, shift: e.shiftKey });
      // Collect printable characters (single-grapheme keys, no modifiers).
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
        this.chars += e.key;
      }
      // Prevent page scroll / back-nav on keys the game uses.
      if (
        ["Tab", " ", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Backspace", "F3"].includes(
          e.key,
        )
      ) {
        e.preventDefault();
      }
    });

    c.addEventListener("keyup", (e) => {
      this.shift = e.shiftKey;
      this.ctrl = e.ctrlKey || e.metaKey;
      this.keysDown.delete(e.key);
    });
  }

  /** Clear per-frame deltas. Called once at the end of every frame. */
  endFrame(): void {
    this.pressed = false;
    this.released = false;
    this.rightPressed = false;
    this.rightReleased = false;
    this.middlePressed = false;
    this.middleReleased = false;
    this.doubleClick = false;
    this.wheel = 0;
    this.keysPressed.length = 0;
    this.chars = "";
  }
}
