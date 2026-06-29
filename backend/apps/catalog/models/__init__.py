"""Catalog models — pinball machines, manufacturers, groups, and people.

The catalog represents the resolved/materialized view of each entity.
Field values are derived by resolving claims from the provenance layer.
"""

from .base import AliasModel, CatalogModel
from .gameplay_feature import (
    GameplayFeature,
    GameplayFeatureAlias,
    GameplayFeatureParent,
    MachineModelGameplayFeature,
)
from .location import CorporateEntityLocation, Location, LocationAlias
from .machine_model import MachineModel, ModelAbbreviation
from .manufacturer import (
    CorporateEntity,
    CorporateEntityAlias,
    Manufacturer,
    ManufacturerAlias,
    OperatingStatus,
)
from .person import Credit, Person, PersonAlias
from .series import Franchise, Series
from .system import System, SystemMpuString
from .taxonomy import (
    PRODUCED_SLUG,
    Cabinet,
    CreditRole,
    DisplaySubtype,
    DisplayType,
    GameFormat,
    MachineModelRewardType,
    MachineModelTag,
    ProductionStatus,
    RewardType,
    RewardTypeAlias,
    Tag,
    TechnologyGeneration,
    TechnologySubgeneration,
)
from .theme import MachineModelTheme, Theme, ThemeAlias, ThemeParent
from .title import Title, TitleAbbreviation
