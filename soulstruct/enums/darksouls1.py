__all__ = [
    # Basic enums/types
    "RestartType",
    "uint",
    "short",
    "ushort",
    "char",
    "uchar",
    "PLAYER",
    "CLIENT_PLAYER_1",
    "CLIENT_PLAYER_2",
    "CLIENT_PLAYER_3",
    "CLIENT_PLAYER_4",
    "CLIENT_PLAYER_5",
    # Enums identical in all games
    "AIStatusType",
    "BitOperation",
    "ButtonType",
    "CharacterType",
    "CharacterUpdateRate",
    "ClassType",
    "ComparisonType",
    "CutsceneType",
    "DamageTargetType",
    "EventEndType",
    "FlagState",
    "FlagType",
    "InterpolationState",
    "ItemType",
    "RangeState",
    "CoordEntityType",
    "NavmeshType",
    "NumberButtons",
    "OnOffChange",
    "RestartType",
    "SoundType",
    "StatueType",
    "SummonSignType",
    "TriggerAttribute",
    "WorldTendencyType",
    "UpdateAuthority",
    # Enums in Dark Souls 1 (both PTD and DSR) only
    "CalculationType",
    "ConditionGroup",
    "Covenant",
    "TeamType",
    "BannerType",
    "MultiplayerState",
    "NPCPartType",

    # Non-event enums
    "CollisionHitFilter",
]

from enum import IntEnum

from .shared import *


class CalculationType(IntEnum):
    Add = 0
    Subtract = 1
    Multiply = 2
    Divide = 3
    Modulus = 4


class ConditionGroup(IntEnum):
    OR_7 = -7
    OR_6 = -6
    OR_5 = -5
    OR_4 = -4
    OR_3 = -3
    OR_2 = -2
    OR_1 = -1
    MAIN = 0
    AND_1 = 1
    AND_2 = 2
    AND_3 = 3
    AND_4 = 4
    AND_5 = 5
    AND_6 = 6
    AND_7 = 7


class Covenant(IntEnum):
    NoCovenant = 0
    WayOfWhite = 1
    PrincessGuard = 2
    WarriorOfSunlight = 3
    Darkwraith = 4
    PathOfTheDragon = 5
    GravelordServant = 6
    ForestHunter = 7
    DarkmoonBlade = 8
    ChaosServant = 9


class TeamType(IntEnum):
    Default = -1
    NoTeam = 0
    Human = 1
    WhitePhantom = 2
    BlackPhantom = 3
    Hollow = 4
    Vagrant = 5
    Enemy = 6
    Boss = 7
    Ally = 8  # Targets no one, targeted by Enemy/Boss. (Not sure about HostileAlly.)
    HostileAlly = 9  # Targets and targeted by everyone.
    Decoy = 10
    RedChild = 11
    FightingAlly = 12  # Targets Enemy/Boss, targeted by Enemy/Boss.
    Intruder = 13  # Targets and targeted by Human/WhitePhantom/Hollow
    Neutral = 14
    Charm = 15


class BannerType(IntEnum):
    VictoryAchieved = 1
    YouDied = 2
    HumanityRestored = 3
    SoulsRetrieved = 4
    TargetDestroyed = 5
    YouDiedPhantom = 6  # Phantom version of "YOU DIED"
    BlackPhantomDestroyed = 7
    AreaName = 8  # Name determined by current floor collision.
    MagicRevival = 9
    RingRevival = 10
    RareRingRevival = 11
    Congratulations = 12  # Bugged texture.
    BonfireLit = 13
    YouWin = 15
    YouLose = 16
    Draw = 17
    BeginMatch = 18  # REMASTERED ONLY.


class MultiplayerState(IntEnum):
    Host = 0
    Client = 1
    Multiplayer = 2
    Singleplayer = 3
    UnknownPlayerType4 = 4  # REMASTERED ONLY.
    UnknownPlayerType5 = 5  # REMASTERED ONLY.


class NPCPartType(IntEnum):
    """Used in definining different behavior for parts of NPC models, e.g. tails that can be cut or Smough's invincible
    hammer."""
    Part1 = 1
    Part2 = 2
    Part3 = 3
    Part4 = 4
    Part5 = 5
    Part6 = 6
    WeakPoint = 7
    Part7 = 8
    Part8 = 9


class CollisionHitFilter(IntEnum):
    """Defines behavior of `MSBCollision` instances in maps. Courtesy of horkrux."""
    NoHiHitNoFeetIK = 0  # solid
    NoHiHit_1 = 1  # solid
    NoHiHit_2 = 2  # solid
    NoHiHit_3 = 3  # solid
    NoHiHit_4 = 4  # solid
    NoHiHit_5 = 5  # solid
    NoHiHit_6 = 6  # solid
    NoHiHit_7 = 7  # solid
    Normal = 8  # solid
    Water_A = 9  # blue
    Unknown_10 = 10
    Solid_ForNPCsOnly_A = 11  # blue
    Unknown_12 = 12
    DeathCam = 13  # white
    LethalFall = 14  # red
    DeathPlane = 15  # black
    Water_B = 16  # dark blue
    GroupSwitch = 17  # turquoise; in elevator shafts
    Unknown_18 = 18
    Solid_ForNPCsOnly_B = 19  # turquoise
    LevelExit_A = 20  # purple
    Slide = 21  # yellow
    FallProtection = 22  # permeable for projectiles
    LevelExit_B = 23  # glowing turquoise
