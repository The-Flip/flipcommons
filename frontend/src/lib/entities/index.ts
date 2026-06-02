import type { EntityKey } from './entity-meta';
import type { ListingInfo } from './types';

import { cabinet } from './cabinet';
import { corporateEntity } from './corporate-entity';
import { creditRole } from './credit-role';
import { displaySubtype } from './display-subtype';
import { displayType } from './display-type';
import { franchise } from './franchise';
import { gameFormat } from './game-format';
import { gameplayFeature } from './gameplay-feature';
import { location } from './location';
import { manufacturer } from './manufacturer';
import { model } from './model';
import { person } from './person';
import { rewardType } from './reward-type';
import { series } from './series';
import { system } from './system';
import { tag } from './tag';
import { technologyGeneration } from './technology-generation';
import { technologySubgeneration } from './technology-subgeneration';
import { theme } from './theme';
import { title } from './title';

export {
  cabinet,
  corporateEntity,
  creditRole,
  displaySubtype,
  displayType,
  franchise,
  gameFormat,
  gameplayFeature,
  location,
  manufacturer,
  model,
  person,
  rewardType,
  series,
  system,
  tag,
  technologyGeneration,
  technologySubgeneration,
  theme,
  title,
};

/** The listing-relevant projection of an `EntityInfo`, schema generic erased. */
export type ListingEntityInfo = { entityType: EntityKey; listing?: ListingInfo };

/**
 * Every entity's presentation info, keyed by `entity_type` (NOT the camelCase
 * export name — `corporateEntity` lives under `'corporate-entity'`). Lets the
 * generic listing wrappers resolve copy from a `CatalogEntityKey`. The
 * `satisfies Record<EntityKey, …>` makes a missing or misspelled key a compile
 * error.
 */
export const ENTITY_INFO = {
  cabinet,
  'corporate-entity': corporateEntity,
  'credit-role': creditRole,
  'display-subtype': displaySubtype,
  'display-type': displayType,
  franchise,
  'game-format': gameFormat,
  'gameplay-feature': gameplayFeature,
  location,
  manufacturer,
  model,
  person,
  'reward-type': rewardType,
  series,
  system,
  tag,
  'technology-generation': technologyGeneration,
  'technology-subgeneration': technologySubgeneration,
  theme,
  title,
} satisfies Record<EntityKey, ListingEntityInfo>;
