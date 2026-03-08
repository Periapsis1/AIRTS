from __future__ import annotations
import random
from config.unit_types import get_spawnable_types
from entities.unit import Unit
from systems.ai.base import BaseAI

def _build_unit_id_map(units):
    _map = {id(unit):unit for unit in units}

class Peri(BaseAI):
    """My own bot.

    Spams snipers and medics in a 4:1 ratio
    Increase medic portion more if sniper hp collectively falls below 70%

    Build order:
        sniper 1 (S1) -> 1st nearest mex (M1)
        S2 -> M1
        when M1 finishes: S1, S2 -> M2
        S3 -> M2
        (Move new snipers to nearest unclaimed mex from now on)
        S4 deny nearest enemy mex
        Medic 1 -> guard S4
        S5

        Attempt capture enemy mex
        Maintain front and push using micro logic
        
    Micro:
        Different modes: push, retreat, combat
        Medics in back, snipers in front
        each step, select target sniper with most hp > sniper damage

    """

    ai_id = "Peri"
    ai_name = "Peri AI"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.old_units = {}
        self.cur_units = {}

        self.new_units = {}
        self.destroyed_units = {}

        self.enemy_velocities = {}
        self.enemy_predictions = {}

        self.target_medic_ratio = 0.25
        self.num_medics = 0
        self.num_snipers = 0

    def on_start(self) -> None:
        self.set_build("sniper")

    def on_step(self, iteration: int) -> None:
        self.setup_step()
        self.calculate_diffs()

        for uid, unit in self.new_units.items():
            self.on_unit_built(uid, unit)
        
        for uid, unit in self.destroyed_units.items():
            self.on_unit_destroyed(uid, unit)

        
        

    def setup_step(self):
        self.old_units = self.cur_entities
        self.cur_units = _build_unit_id_map(self.get_units())

        self.new_units = {}
        self.destroyed_units = {}

        self.enemy_velocities = {}
        self.enemy_predictions = {}


    def calculate_diffs(self):
        for uid, unit in self.cur_units.items():
            if uid not in self.old_units:
                self.new_units[uid] = unit
        
        for uid, unit in self.old_units.items():
            if uid not in self.cur_units:
                self.destroyed_units[uid] = unit

    def on_unit_built(self, uid:int, unit:Unit):
        # update ratio and target
        if unit.team == self._team:
            if unit.unit_type == 'medic':
                self.num_medics += 1
            elif unit.unit_type == 'sniper':
                self.num_snipers += 1

    def on_unit_destroyed(self, uid:int, unit:Unit):
        if unit.team == self._team:
            if unit.unit_type == 'medic':
                self.num_medics -= 1
            elif unit.unit_type == 'sniper':
                self.num_snipers -= 1
            