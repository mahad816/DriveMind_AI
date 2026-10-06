"""Semantic restrictions are distinct from concrete retrieval eligibility."""

from typing import Annotated, Literal, TypeAlias
from uuid import UUID
from pydantic import Field, model_validator
from .references import CandidateId, ContractModel

InventoryOrdering: TypeAlias = Literal[
    "DEFAULT", "NEWEST_FIRST", "OLDEST_FIRST", "NAME_ASC", "NAME_DESC"
]
# DEFAULT is an executor contract, not a database sorting implementation.
DEFAULT_LIST_ORDER = ("filename_unicode_casefold_ascending", "internal_file_id_ascending")


class AllVisibleIndexedFiles(ContractModel):
    kind: Literal["ALL_VISIBLE_INDEXED_FILES"] = "ALL_VISIBLE_INDEXED_FILES"


class ExplicitFileTargetScope(ContractModel):
    kind: Literal["EXPLICIT_FILE_TARGET"] = "EXPLICIT_FILE_TARGET"


class FolderReferenceScope(ContractModel):
    kind: Literal["FOLDER_REFERENCE"] = "FOLDER_REFERENCE"
    candidate_id: CandidateId


class LabelReferenceScope(ContractModel):
    kind: Literal["LABEL_REFERENCE"] = "LABEL_REFERENCE"
    candidate_id: CandidateId


class ModifiedTimeReferenceScope(ContractModel):
    kind: Literal["MODIFIED_TIME_REFERENCE"] = "MODIFIED_TIME_REFERENCE"
    candidate_id: CandidateId


ScopeRestriction: TypeAlias = Annotated[
    FolderReferenceScope | LabelReferenceScope | ModifiedTimeReferenceScope,
    Field(discriminator="kind"),
]


class RestrictedCollectionScope(ContractModel):
    """Bounded conjunction: multiple restrictions must not disappear."""

    kind: Literal["RESTRICTED_COLLECTION"] = "RESTRICTED_COLLECTION"
    restrictions: tuple[ScopeRestriction, ...] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def distinct(self) -> "RestrictedCollectionScope":
        if len(set(self.restrictions)) != len(self.restrictions):
            raise ValueError("duplicate scope restriction")
        return self


class NoFileScope(ContractModel):
    kind: Literal["NO_FILE_SCOPE"] = "NO_FILE_SCOPE"


SemanticScope: TypeAlias = Annotated[
    AllVisibleIndexedFiles
    | ExplicitFileTargetScope
    | FolderReferenceScope
    | LabelReferenceScope
    | ModifiedTimeReferenceScope
    | RestrictedCollectionScope
    | NoFileScope,
    Field(discriminator="kind"),
]


class EligibleCollectionScope(ContractModel):
    kind: Literal["ELIGIBLE_INDEXED_COLLECTION"] = "ELIGIBLE_INDEXED_COLLECTION"


class ResolvedFileScope(ContractModel):
    kind: Literal["RESOLVED_FILES"] = "RESOLVED_FILES"
    # Empty means zero eligible files, never ALL.
    file_ids: tuple[UUID, ...]

    @model_validator(mode="after")
    def unique_files(self) -> "ResolvedFileScope":
        if len(set(self.file_ids)) != len(self.file_ids):
            raise ValueError("duplicate resolved file identity")
        return self


RetrievalScope: TypeAlias = Annotated[
    EligibleCollectionScope | ResolvedFileScope, Field(discriminator="kind")
]


class DeferredFileResultScope(ContractModel):
    kind: Literal["DEFERRED_FILE_RESULT"] = "DEFERRED_FILE_RESULT"


class NoRetrievalScope(ContractModel):
    kind: Literal["NO_RETRIEVAL"] = "NO_RETRIEVAL"


ExecutionScope: TypeAlias = Annotated[
    EligibleCollectionScope | ResolvedFileScope | DeferredFileResultScope | NoRetrievalScope,
    Field(discriminator="kind"),
]
