# AIRTS Documentation

AIRTS is a real-time strategy game built with Pygame for the BlueOrange AI Jam. Two teams battle for control of the map — each with a Command Center that spawns units, metal spots to capture for economic advantage, and five distinct unit types. The game is designed as a platform for writing AI controllers that compete against humans or other AIs.

## Reading Guide

| You want to…                        | Read                                      |
|--------------------------------------|-------------------------------------------|
| Write an AI controller               | [ai-guide.md](ai-guide.md)               |
| Understand the game rules            | [game-mechanics.md](game-mechanics.md)    |
| Understand the codebase internals    | [architecture.md](architecture.md)        |
| Add new units, maps, or systems      | [extending.md](extending.md)             |

## Setup

```bash
# Clone the repository
git clone <repo-url>
cd AIRTS

# Create a virtual environment and install dependencies
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows
pip install -r requirements.txt

# Run the game
python main.py
```

### Requirements

- Python 3.10+
- `pygame >= 2.6.0`
- `numpy >= 2.4.2`

## Game Modes

Configure the `team_ai` parameter in `main.py` to set up different game modes:

| Mode                | `team_ai=`                                     | Description                          |
|---------------------|-------------------------------------------------|--------------------------------------|
| Human vs AI         | `{2: WanderAI()}`                               | You control Team 1, AI controls Team 2 |
| AI vs Human         | `{1: MyAI()}`                                   | AI controls Team 1, you control Team 2 |
| AI vs AI (spectator)| `{1: MyAI(), 2: WanderAI()}`                    | Watch two AIs battle each other      |

At least one team must have an AI controller — Human-vs-Human is not supported.

### Example: Running AI vs AI

```python
# main.py
from game import Game
from systems.map_generator import DefaultMapGenerator
from systems.ai import WanderAI
from my_ai import MyAI  # your custom AI

def main():
    game = Game(
        width=800,
        height=600,
        title="AIRTS",
        map_generator=DefaultMapGenerator(),
        team_ai={1: MyAI(), 2: WanderAI()},
    )
    game.run()

if __name__ == "__main__":
    main()
```
