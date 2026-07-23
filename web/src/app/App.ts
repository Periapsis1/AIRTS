// Top-level app: owns the UI context, the shared server Connection (carried
// from the lobby into the game), and the active screen. Routes Transitions to
// the next screen, mirroring app.py's screen routing.

import type { UI } from "../ui/Widgets";
import type { Connection } from "../net/Connection";
import { Screen, type Transition } from "./Screen";
import { MainMenuScreen } from "../screens/MainMenuScreen";
import { ConnectScreen } from "../screens/ConnectScreen";
import { CreateLobbyScreen } from "../screens/CreateLobbyScreen";
import { ClientGameScreen } from "../screens/ClientGameScreen";
import { ResultsScreen } from "../screens/ResultsScreen";

export class App {
  ui: UI;
  /** Active server connection, shared from the lobby into the game screen. */
  conn: Connection | null = null;

  private screen: Screen;

  constructor(ui: UI) {
    this.ui = ui;
    this.screen = new MainMenuScreen(this);
  }

  frame(dt: number): void {
    const t = this.screen.render(dt);
    if (t) this.transition(t);
  }

  private transition(t: Transition): void {
    this.screen.dispose();
    const data = t.data ?? {};
    switch (t.next) {
      case "main_menu":
        // Returning to the menu drops any active connection.
        if (this.conn) {
          this.conn.close();
          this.conn = null;
        }
        this.screen = new MainMenuScreen(this);
        break;
      case "connect":
        this.screen = new ConnectScreen(this);
        break;
      case "create_lobby":
        this.screen = new CreateLobbyScreen(this);
        break;
      case "game":
        this.screen = new ClientGameScreen(this, data);
        break;
      case "results":
        this.screen = new ResultsScreen(this, data);
        break;
      case "quit":
        // Browsers can't truly close the tab; just return to the menu.
        this.screen = new MainMenuScreen(this);
        break;
      default:
        console.warn("Unknown transition target:", t.next);
        this.screen = new MainMenuScreen(this);
    }
  }
}
