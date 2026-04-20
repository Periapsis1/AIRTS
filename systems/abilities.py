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
    ELECTRIC_ARMOR_INTERVAL,
    ELECTRIC_ARMOR_MAX_STACKS,
    ELECTRIC_ARMOR_REDUCTION,
    ELECTRIC_ARMOR_REGEN_PER_STACK,
    ELECTRIC_ARMOR_SPEED_BONUS,
    ELECTRIC_ARMOR_COLOR,
    OVERCLOCK_RANGE,
    OVERCLOCK_REGEN,
    OVERCLOCK_BONUS,
    OVERCLOCK_REGEN_T2,
    OVERCLOCK_BONUS_T2,
    OVERCLOCK_COLOR,
    DETECTION_AURA_RANGE,
    DETECTION_LOS_PER_STACK,
    DETECTION_LOS_MAX_BONUS,
    DETECTION_RANGE_PER_STACK,
    DETECTION_RANGE_MAX_BONUS,
    DETECTION_COLOR,
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


class ElectricArmor(PassiveAbility):
    name = "electric_armor"
    description = "Gains a stack every second (max 8). While stacks > 0: 60% damage reduction. Each stack: +1 HP/s regen, +20% speed. Loses one stack when hit."

    def __init__(self):
        super().__init__()
        self.stacks: int = 0
        self.max_stacks: int = ELECTRIC_ARMOR_MAX_STACKS
        self.stack_interval: float = ELECTRIC_ARMOR_INTERVAL
        self.stack_timer: float = 0.0
        self._base_speed: float = 0.0

    def update(self, entity, dt: float) -> None:
        # Capture base speed on first update
        if self._base_speed == 0.0:
            self._base_speed = entity.speed

        # Build stacks
        if self.stacks < self.max_stacks:
            self.stack_timer += dt
            while self.stack_timer >= self.stack_interval and self.stacks < self.max_stacks:
                self.stack_timer -= self.stack_interval
                self.stacks += 1

        # Passive regen: 1 HP/s per stack
        if self.stacks > 0 and entity.hp < entity.max_hp:
            heal = ELECTRIC_ARMOR_REGEN_PER_STACK * self.stacks * dt
            entity.hp = min(entity.max_hp, entity.hp + heal)

        # Speed bonus: +20% per stack
        entity.speed = self._base_speed * (1.0 + ELECTRIC_ARMOR_SPEED_BONUS * self.stacks)

    def modify_damage(self, amount: float, entity) -> float:
        if self.stacks <= 0:
            return amount
        # Flat 60% reduction as long as stacks > 0 (does not scale with stack count)
        reduction = ELECTRIC_ARMOR_REDUCTION
        self.stacks -= 1
        self.stack_timer = 0.0
        return amount * (1.0 - reduction)

    def draw(self, entity, surface: pygame.Surface) -> None:
        if self.stacks <= 0:
            return
        # Draw small diamond indicators above the unit, one per stack
        y_off = entity.radius + 6
        spacing = 5
        start_x = entity.x - (self.stacks - 1) * spacing / 2
        for i in range(self.stacks):
            cx = start_x + i * spacing
            cy = entity.y - y_off
            size = 2
            points = [
                (cx, cy - size),
                (cx + size, cy),
                (cx, cy + size),
                (cx - size, cy),
            ]
            pygame.draw.polygon(surface, ELECTRIC_ARMOR_COLOR, points)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "stacks": self.stacks,
            "stack_timer": self.stack_timer,
            "_base_speed": self._base_speed,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ElectricArmor:
        obj = cls()
        obj.active = data.get("active", False)
        obj.stacks = data.get("stacks", 0)
        obj.stack_timer = data.get("stack_timer", 0.0)
        obj._base_speed = data.get("_base_speed", 0.0)
        return obj


class CombatStim(PassiveAbility):
    """For every 10 missing HP, gain -0.1 weapon cooldown and +5% movement speed."""
    name = "combat_stim"
    description = "For every 10 missing HP: -0.1s cooldown, +5% speed."

    def __init__(self):
        super().__init__()
        self._base_speed: float = 0.0
        self._base_cooldown: float = 0.0

    def update(self, entity, dt: float) -> None:
        # Capture base values on first update
        if self._base_speed == 0.0 and entity.speed > 0:
            self._base_speed = entity.speed
        if self._base_cooldown == 0.0:
            self._base_cooldown = entity.attack_cooldown_max

        missing = max(0.0, entity.max_hp - entity.hp)
        stacks = int(missing / 10.0)

        if stacks > 0:
            self.active = True
            # Speed bonus: +5% per stack
            entity.speed = self._base_speed * (1.0 + 0.05 * stacks)
            # Cooldown reduction: -0.1s per stack (min 0.1s)
            if self._base_cooldown > 0:
                entity.attack_cooldown_max = max(0.1, self._base_cooldown - 0.1 * stacks)
        else:
            self.active = False
            if self._base_speed > 0:
                entity.speed = self._base_speed
            if self._base_cooldown > 0:
                entity.attack_cooldown_max = self._base_cooldown

    def draw(self, entity, surface: pygame.Surface) -> None:
        if not self.active:
            return
        # Draw a small upward chevron above the unit (green-ish)
        cx = entity.x
        cy = entity.y - entity.radius - 6
        size = 3
        pts = [(cx - size, cy + size), (cx, cy - size), (cx + size, cy + size)]
        pygame.draw.lines(surface, (100, 255, 100), False, pts, 2)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["_base_speed"] = self._base_speed
        d["_base_cooldown"] = self._base_cooldown
        return d

    @classmethod
    def from_dict(cls, data: dict) -> CombatStim:
        obj = cls()
        obj.active = data.get("active", False)
        obj._base_speed = data.get("_base_speed", 0.0)
        obj._base_cooldown = data.get("_base_cooldown", 0.0)
        return obj


class Overclock(PassiveAbility):
    """Allied metal extractors in range gain HP/s regen and an additive spawn bonus."""
    name = "overclock"
    description = (
        "Allied metal extractors in range gain HP regen and a small spawn boost."
    )

    # Set by Game each tick: tuple of all live MetalExtractor instances.
    all_metal_extractors: tuple = ()

    def __init__(self, regen: float = OVERCLOCK_REGEN,
                 bonus: float = OVERCLOCK_BONUS,
                 aura_range: float = OVERCLOCK_RANGE):
        super().__init__()
        self.regen: float = regen
        self.bonus: float = bonus
        self.aura_range: float = aura_range

    def update(self, entity, dt: float) -> None:
        # Buff every allied metal extractor whose centre is within aura_range.
        range_sq = self.aura_range * self.aura_range
        for me in Overclock.all_metal_extractors:
            if not me.alive or me.team != entity.team:
                continue
            dx = me.x - entity.x
            dy = me.y - entity.y
            if dx * dx + dy * dy > range_sq:
                continue
            # Direct heal — capped at max_hp. Multiple engineers heal additively.
            if me.hp < me.max_hp:
                me.hp = min(me.max_hp, me.hp + self.regen * dt)
            # Stack additively with other engineers via the pending accumulator.
            me._overclock_bonus_pending += self.bonus
        # Show as "active" purely for UI/inspection — never gates anything.
        self.active = True

    def draw(self, entity, surface: pygame.Surface) -> None:
        # Faint aura ring so the player can see the buff radius on selected engineers.
        if not getattr(entity, "selected", False):
            return
        r = int(self.aura_range)
        if r <= 0:
            return
        ix, iy = int(round(entity.x)), int(round(entity.y))
        ring = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(ring, (*OVERCLOCK_COLOR, 60), (r + 2, r + 2), r, 1)
        surface.blit(ring, (ix - r - 2, iy - r - 2))

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "regen": self.regen,
            "bonus": self.bonus,
            "aura_range": self.aura_range,
        })
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Overclock:
        obj = cls(
            regen=data.get("regen", OVERCLOCK_REGEN),
            bonus=data.get("bonus", OVERCLOCK_BONUS),
            aura_range=data.get("aura_range", OVERCLOCK_RANGE),
        )
        obj.active = data.get("active", False)
        return obj


class Detection(PassiveAbility):
    """Sweeper passive — stacks LOS from nearby allied sweepers and grants
    allies inside the aura bonus attack range.

    LOS scales with *other* sweepers on the same team within aura range:
    +DETECTION_LOS_PER_STACK per sweeper, capped at DETECTION_LOS_MAX_BONUS.
    Each allied unit in range (including other sweepers) receives
    +DETECTION_RANGE_PER_STACK attack_range per sweeper covering it, capped
    at DETECTION_RANGE_MAX_BONUS (the per-unit cap is enforced by the
    receiver when flushing `_detection_range_pending`).
    """
    name = "detection"
    description = (
        "Nearby allied sweepers stack LOS (+50 per sweeper, max +200). "
        "Allied units in range gain +5 attack range per sweeper (max +20)."
    )

    # Set by Game each tick — live sweeper list (all teams) and unit list.
    all_sweepers: tuple = ()
    all_units: tuple = ()

    def __init__(self, aura_range: float = DETECTION_AURA_RANGE):
        super().__init__()
        self.aura_range: float = aura_range

    def update(self, entity, dt: float) -> None:
        range_sq = self.aura_range * self.aura_range

        # -- LOS bonus: count other allied sweepers within aura --------------
        nearby = 0
        for sw in Detection.all_sweepers:
            if sw is entity or not sw.alive or sw.team != entity.team:
                continue
            dx = sw.x - entity.x
            dy = sw.y - entity.y
            if dx * dx + dy * dy <= range_sq:
                nearby += 1
        los_bonus = min(nearby * DETECTION_LOS_PER_STACK, DETECTION_LOS_MAX_BONUS)
        base_los = getattr(entity, "_base_line_of_sight", None)
        if base_los is None:
            base_los = entity.line_of_sight
            entity._base_line_of_sight = base_los
        entity.line_of_sight = base_los + los_bonus

        # -- Range aura: stack +5 on each allied unit in range ---------------
        for u in Detection.all_units:
            if not u.alive or u.team != entity.team:
                continue
            dx = u.x - entity.x
            dy = u.y - entity.y
            if dx * dx + dy * dy > range_sq:
                continue
            pending = getattr(u, "_detection_range_pending", 0.0)
            u._detection_range_pending = min(
                pending + DETECTION_RANGE_PER_STACK,
                DETECTION_RANGE_MAX_BONUS,
            )
        self.active = True

    def draw(self, entity, surface: pygame.Surface) -> None:
        if not getattr(entity, "selected", False):
            return
        r = int(self.aura_range)
        if r <= 0:
            return
        ix, iy = int(round(entity.x)), int(round(entity.y))
        ring = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(ring, (*DETECTION_COLOR, 60), (r + 2, r + 2), r, 1)
        surface.blit(ring, (ix - r - 2, iy - r - 2))

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["aura_range"] = self.aura_range
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Detection:
        obj = cls(aura_range=data.get("aura_range", DETECTION_AURA_RANGE))
        obj.active = data.get("active", False)
        return obj


ABILITY_REGISTRY: dict[str, type[PassiveAbility]] = {
    "reinforce": Reinforce,
    "reactive_armor": ReactiveArmor,
    "focus": Focus,
    "electric_armor": ElectricArmor,
    "combat_stim": CombatStim,
    "overclock": Overclock,
    "detection": Detection,
}


def ability_from_dict(data: dict) -> PassiveAbility:
    """Reconstruct an ability from serialized data."""
    cls = ABILITY_REGISTRY.get(data.get("type", ""), PassiveAbility)
    return cls.from_dict(data)
