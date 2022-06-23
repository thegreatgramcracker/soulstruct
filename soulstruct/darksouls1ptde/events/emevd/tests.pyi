import typing as tp

from soulstruct.darksouls1ptde.game_types import *
from .enums import *

__all__ = [
    # Names processed directly by EVS parser
    "NeverRestart",
    "RestartOnRest",
    "UnknownRestart",
    "EVENTS",
    "Condition",
    "HeldCondition",
    "END",
    "RESTART",
    "Await",
    "THIS_FLAG",
    "THIS_SLOT_FLAG",
    "ONLINE",
    "OFFLINE",
    "DLC_OWNED",
    "SKULL_LANTERN_ACTIVE",
    "WHITE_WORLD_TENDENCY",
    "BLACK_WORLD_TENDENCY",
    "NEW_GAME_CYCLE",
    "SOUL_LEVEL",
    "FlagEnabled",
    "FlagDisabled",
    "SecondsElapsed",
    "FramesElapsed",
    "CharacterInsideRegion",
    "CharacterOutsideRegion",
    "PlayerInsideRegion",
    "PlayerOutsideRegion",
    "AllPlayersInsideRegion",
    "AllPlayersOutsideRegion",
    "InsideMap",
    "OutsideMap",
    "EntityWithinDistance",
    "EntityBeyondDistance",
    "PlayerWithinDistance",
    "PlayerBeyondDistance",
    "HasItem",
    "HasWeapon",
    "HasArmor",
    "HasRing",
    "HasGood",
    "ActionButton",
    "MultiplayerEvent",
    "TrueFlagCount",
    "EventValue",
    "EventFlagValue",
    "AnyItemDroppedInRegion",
    "ItemDropped",
    "OwnsItem",
    "OwnsWeapon",
    "OwnsArmor",
    "OwnsRing",
    "OwnsGood",
    "IsAlive",
    "IsDead",
    "IsAttacked",
    "HealthRatio",
    "HealthValue",
    "PartHealthValue",
    "IsCharacterType",
    "IsHollow",
    "IsHuman",
    "IsInvader",
    "IsBlackPhantom",
    "IsWhitePhantom",
    "HasSpecialEffect",
    "BackreadEnabled",
    "BackreadDisabled",
    "HasTaeEvent",
    "IsTargeting",
    "HasAiStatus",
    "AiStatusIsNormal",
    "AiStatusIsRecognition",
    "AiStatusIsAlert",
    "AiStatusIsBattle",
    "PlayerIsClass",
    "PlayerInCovenant",
    "IsDamaged",
    "IsDestroyed",
    "IsActivated",
    "PlayerStandingOnCollision",
    "PlayerMovingOnCollision",
    "PlayerRunningOnCollision",
    "HOST",
    "CLIENT",
    "MULTIPLAYER",
    "SINGLEPLAYER",
]

# Restart decorators. They can be used as names (not function calls) or have an event ID argument.
def NeverRestart(event_id_or_func: tp.Union[tp.Callable, int]): ...
def RestartOnRest(event_id_or_func: tp.Union[tp.Callable, int]): ...
def UnknownRestart(event_id_or_func: tp.Union[tp.Callable, int]): ...

# Dummy enum for accessing event flags defined by events.
class EVENTS(Flag): ...

# Dummy class for creating conditions.
class Condition:
    def __init__(self, condition, hold: bool = False): ...

class HeldCondition:
    def __init__(self, condition): ...

# Terminators.
END = ...
RESTART = ...

# The Await function. Equivalent to using the 'await' built-in Python keyword.
def Await(condition): ...

# Boolean constants.
THIS_FLAG = ...
THIS_SLOT_FLAG = ...
ONLINE = ...
OFFLINE = ...
DLC_OWNED = ...
SKULL_LANTERN_ACTIVE = ...

# Compare these constants to numeric values.
WHITE_WORLD_TENDENCY = ...
BLACK_WORLD_TENDENCY = ...
NEW_GAME_CYCLE = ...
SOUL_LEVEL = ...

def FlagEnabled(flag: FlagInt): ...
def FlagDisabled(flag: FlagInt): ...
def SecondsElapsed(elapsed_seconds): ...
def FramesElapsed(elapsed_frames): ...
def CharacterInsideRegion(entity: AnimatedEntityTyping, region: RegionTyping): ...
def CharacterOutsideRegion(entity: AnimatedEntityTyping, region: RegionTyping): ...
def PlayerInsideRegion(region: RegionTyping): ...
def PlayerOutsideRegion(region: RegionTyping): ...
def AllPlayersInsideRegion(region: RegionTyping): ...
def AllPlayersOutsideRegion(region: RegionTyping): ...
def InsideMap(game_map: MapTyping): ...
def OutsideMap(game_map: MapTyping): ...
def EntityWithinDistance(first_entity: CoordEntityTyping, second_entity: CoordEntityTyping, max_distance): ...
def EntityBeyondDistance(first_entity: CoordEntityTyping, second_entity: CoordEntityTyping, min_distance): ...
def PlayerWithinDistance(entity: CoordEntityTyping, max_distance): ...
def PlayerBeyondDistance(entity: CoordEntityTyping, min_distance): ...

# These do NOT include storage, such as the Bottomless Box.
def HasItem(item: ItemTyping): ...  # Can be used with any subclass of Item.
def HasWeapon(weapon: WeaponTyping): ...
def HasArmor(armor: ArmorTyping): ...
def HasRing(ring: RingTyping): ...
def HasGood(good: GoodTyping): ...

# These DO include storage, such as the Bottomless Box.
def OwnsItem(item: ItemTyping): ...  # Can be used with any subclass of Item.
def OwnsWeapon(weapon: WeaponTyping): ...
def OwnsArmor(armor: ArmorTyping): ...
def OwnsRing(ring: RingTyping): ...
def OwnsGood(good: GoodTyping): ...

# This test creates a dialog prompt, and returns True when the prompt is activated (with A).
# Should only be used with Await().
def ActionButton(
    prompt_text: EventTextTyping,
    anchor_entity: CoordEntityTyping,
    anchor_type=None,
    facing_angle: float = None,
    max_distance: float = None,
    model_point: int = None,
    trigger_attribute: TriggerAttribute = TriggerAttribute.Human_or_Hollow,
    button=0,
    boss_version=False,
    line_intersects: CoordEntityTyping = None,
): ...
def MultiplayerEvent(multiplayer_event): ...
def EventFlagValue(left_start_flag, left_bit_count, right_start_flag, right_bit_count): ...  # Compare two flags.
def AnyItemDroppedInRegion(region: RegionTyping): ...
def ItemDropped(item: ItemTyping): ...
def IsAlive(character: CharacterTyping): ...
def IsDead(character: CharacterTyping): ...
def IsAttacked(attacked_entity: AnimatedEntityTyping, attacker: CharacterTyping): ...

# The values returned by these should be compared with a number literal.
def TrueFlagCount(flag_range) -> int: ...
def EventValue(start_flag, bit_count) -> int: ...  # Use this to compare an event value to an arbitrary integer.
def HealthRatio(character: CharacterTyping) -> float: ...
def HealthValue(character: CharacterTyping) -> int: ...
def PartHealthValue(character: CharacterTyping, part_type) -> int: ...

# Character tests.
def IsCharacterType(character: CharacterTyping, character_type: CharacterType): ...
def IsHollow(character: CharacterTyping): ...
def IsHuman(character: CharacterTyping): ...
def IsInvader(character: CharacterTyping): ...
def IsBlackPhantom(character: CharacterTyping): ...
def IsWhitePhantom(character: CharacterTyping): ...
def PlayerIsClass(class_type: ClassType): ...
def PlayerInCovenant(covenant_type: Covenant): ...
def IsTargeting(targeting_chr: CharacterTyping, targeted_chr: CharacterTyping): ...
def HasAiStatus(character: CharacterTyping, ai_status): ...
def AiStatusIsNormal(character: CharacterTyping): ...
def AiStatusIsRecognition(character: CharacterTyping): ...
def AiStatusIsAlert(character: CharacterTyping): ...
def AiStatusIsBattle(character: CharacterTyping): ...
def HasTaeEvent(character: CharacterTyping, tae_event_id): ...
def HasSpecialEffect(character: CharacterTyping, special_effect): ...
def BackreadEnabled(character: CharacterTyping): ...
def BackreadDisabled(character: CharacterTyping): ...

# Objects
def IsDamaged(obj: ObjectTyping): ...
def IsDestroyed(obj: ObjectTyping): ...
def IsActivated(obj_act_flag: FlagInt): ...

# Collisions
def PlayerStandingOnCollision(collision: CollisionTyping): ...
def PlayerMovingOnCollision(collision: CollisionTyping): ...
def PlayerRunningOnCollision(collision: CollisionTyping): ...

# Boolean conditions.
HOST = ...
CLIENT = ...
SINGLEPLAYER = ...
MULTIPLAYER = ...
