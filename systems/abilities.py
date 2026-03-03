"""Passive ability system — lightweight, extensible framework."""
from __future__ import annotations
from config.settings import (
    REINFORCE_BONUS_MULTIPLIER,
    REINFORCE_HP_BONUS,
    REINFORCE_STACK_INTERVAL,
    REINFORCE_MAX_STACKS,
    REACTIVE_ARMOR_INTERVAL,
    REACTIVE_ARMOR_MAX_STACKS,
    REACTIVE_ARMOR_REDUCTION,
    REACTIVE_ARMOR_COLOR,
)
import pygame


class PassiveAbility:
    name: str = "passive"
    description: str = ""

    def __init__(self):
        self.active: bool = False

    def update(self, entity, dt: float) -> None:
        pass

    def on_activate(self, entity) -> None:
        pass

    def on_fire(self, entity) -> None:
        """Hook called when the unit fires its weapon."""
        pass

    def modify_damage(self, amount: float, entity) -> float:
        """Hook for abilities that alter incoming damage. Return modified amount."""
        return amount

    def draw(self, entity, surface: pygame.Surface) -> None:
        pass

    def to_dict(self) -> dict:
        return {"type": self.name, "active": self.active}

    @classmethod
    def from_dict(cls, data: dict) -> PassiveAbility:
        obj = cls()
        obj.active = data.get("active", False)
        return obj


class Reinforce(PassiveAbility):
    name = "reinforce"
    description = "Builds plating over time. At full stacks, gains bonus HP and doubles spawn bonus."

    def __init__(self):
        super().__init__()
        self.stacks: int = 0
        self.max_stacks: int = REINFORCE_MAX_STACKS
        self.stack_interval: float = REINFORCE_STACK_INTERVAL
        self.stack_timer: float = 0.0

    def update(self, entity, dt: float) -> None:
        if self.active:
            return
        self.stack_timer += dt
        while self.stack_timer >= self.stack_interval and self.stacks < self.max_stacks:
            self.stack_timer -= self.stack_interval
            self.stacks += 1
        if self.stacks >= self.max_stacks and not self.active:
            self.on_activate(entity)

    def on_activate(self, entity) -> None:
        self.active = True
        entity.max_hp += REINFORCE_HP_BONUS
        entity.hp += REINFORCE_HP_BONUS

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "stacks": self.stacks,
            "stack_timer": self.stack_timer,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Reinforce:
        obj = cls()
        obj.active = data.get("active", False)
        obj.stacks = data.get("stacks", 0)
        obj.stack_timer = data.get("stack_timer", 0.0)
        return obj


class ReactiveArmor(PassiveAbility):
    name = "reactive_armor"
    description = "Every 5s gain a charge (max 2). Each stack reduces incoming damage by 50%. Lose all stacks when hit."

    def __init__(self):
        super().__init__()
        self.stacks: int = 0
        self.max_stacks: int = REACTIVE_ARMOR_MAX_STACKS
        self.stack_interval: float = REACTIVE_ARMOR_INTERVAL
        self.stack_timer: float = 0.0

    def update(self, entity, dt: float) -> None:
        if self.stacks >= self.max_stacks:
            return
        self.stack_timer += dt
        while self.stack_timer >= self.stack_interval and self.stacks < self.max_stacks:
            self.stack_timer -= self.stack_interval
            self.stacks += 1

    def modify_damage(self, amount: float, entity) -> float:
        if self.stacks <= 0:
            return amount
        reduction = min(self.stacks * REACTIVE_ARMOR_REDUCTION, 1.0)
        self.stacks = 0
        self.stack_timer = 0.0
        return amount * (1.0 - reduction)

    def draw(self, entity, surface: pygame.Surface) -> None:
        if self.stacks <= 0:
            return
        # Draw small diamond indicators above the unit, one per stack
        y_off = entity.radius + 6
        spacing = 6
        start_x = entity.x - (self.stacks - 1) * spacing / 2
        for i in range(self.stacks):
            cx = start_x + i * spacing
            cy = entity.y - y_off
            size = 3
            points = [
                (cx, cy - size),
                (cx + size, cy),
                (cx, cy + size),
                (cx - size, cy),
            ]
            pygame.draw.polygon(surface, REACTIVE_ARMOR_COLOR, points)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "stacks": self.stacks,
            "stack_timer": self.stack_timer,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ReactiveArmor:
        obj = cls()
        obj.active = data.get("active", False)
        obj.stacks = data.get("stacks", 0)
        obj.stack_timer = data.get("stack_timer", 0.0)
        return obj


class Focus(PassiveAbility):
    name = "focus"
    description = "After firing, speed drops to 25% and gradually recovers over 3 seconds."

    DURATION = 3.0
    MIN_MULT = 0.25  # 25% speed immediately after firing

    def __init__(self):
        super().__init__()
        self.timer: float = 0.0
        self._base_speed: float = 0.0  # captured on first slow

    def on_fire(self, entity) -> None:
        if self._base_speed == 0.0:
            self._base_speed = entity.speed
        self.timer = self.DURATION
        entity.speed = self._base_speed * self.MIN_MULT

    def update(self, entity, dt: float) -> None:
        if self.timer <= 0:
            return
        self.timer = max(0.0, self.timer - dt)
        # Lerp: MIN_MULT at timer=DURATION → 1.0 at timer=0
        t = self.timer / self.DURATION
        mult = self.MIN_MULT + (1.0 - self.MIN_MULT) * (1.0 - t)
        entity.speed = self._base_speed * mult

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "timer": self.timer,
            "_base_speed": self._base_speed,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Focus:
        obj = cls()
        obj.active = data.get("active", False)
        obj.timer = data.get("timer", 0.0)
        obj._base_speed = data.get("_base_speed", 0.0)
        return obj


ABILITY_REGISTRY: dict[str, type[PassiveAbility]] = {
    "reinforce": Reinforce,
    "reactive_armor": ReactiveArmor,
    "focus": Focus,
}


def ability_from_dict(data: dict) -> PassiveAbility:
    """Reconstruct an ability from serialized data."""
    cls = ABILITY_REGISTRY.get(data.get("type", ""), PassiveAbility)
    return cls.from_dict(data)
