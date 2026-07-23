// Screen contract. Screens are immediate-mode: render() draws the screen and
// handles input for the frame, returning a Transition to change screens or
// null to stay. Mirrors the role of screens/*.py + ScreenResult, but without a
// blocking event loop (the App drives one render() per animation frame).

import type { UI } from "../ui/Widgets";
import type { App } from "./App";

export interface Transition {
  next: string;
  data?: Record<string, unknown>;
}

export abstract class Screen {
  protected app: App;
  protected ui: UI;

  constructor(app: App) {
    this.app = app;
    this.ui = app.ui;
  }

  /** Draw + handle input for one frame. Return a Transition to switch. */
  abstract render(dt: number): Transition | null;

  /** Optional cleanup when leaving this screen. */
  dispose(): void {}
}
