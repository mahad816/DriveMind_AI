"""Application-owned semantic handles; Python Unicode code-point offsets."""

from typing import Annotated, Literal, TypeAlias
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


CandidateId: TypeAlias = Annotated[str, Field(pattern=r"^B[0-9]{3}$")]
InputIdentity: TypeAlias = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
OutputKind: TypeAlias = Literal[
    "FILE", "ORDERED_FILE_LIST", "TEXT_ANSWER", "EVIDENCE_SET", "NO_VALUE"
]


class InputSpan(ContractModel):
    start: int = Field(ge=0, lt=8000)
    end: int = Field(gt=0, le=8000)

    @model_validator(mode="after")
    def forward(self) -> "InputSpan":
        if self.end <= self.start:
            raise ValueError("source span must be forward and nonempty")
        return self


class NoTargetReference(ContractModel):
    kind: Literal["NO_TARGET"] = "NO_TARGET"


class LiteralFileCandidateReference(ContractModel):
    kind: Literal["LITERAL_FILE"] = "LITERAL_FILE"
    candidate_id: CandidateId


class MetadataSelectorReference(ContractModel):
    kind: Literal["METADATA_SELECTOR"] = "METADATA_SELECTOR"
    candidate_id: CandidateId
    selector: Literal["LATEST", "OLDEST"]


class PriorFileReference(ContractModel):
    kind: Literal["PRIOR_FILE"] = "PRIOR_FILE"
    candidate_id: CandidateId


class PriorTopicReference(ContractModel):
    kind: Literal["PRIOR_TOPIC"] = "PRIOR_TOPIC"
    candidate_id: CandidateId


class HistoryReference(ContractModel):
    kind: Literal["HISTORY"] = "HISTORY"
    role: Literal["user", "assistant"]
    relative_position: int = Field(ge=1, le=6)


class UnspecifiedSingleFileReference(ContractModel):
    kind: Literal["UNSPECIFIED_SINGLE_FILE"] = "UNSPECIFIED_SINGLE_FILE"


class UniqueFileSelector(ContractModel):
    kind: Literal["UNIQUE_FILE"] = "UNIQUE_FILE"


class ItemAtIndexSelector(ContractModel):
    kind: Literal["ITEM_AT_INDEX"] = "ITEM_AT_INDEX"
    index: int = Field(ge=0)


ResultSelector: TypeAlias = Annotated[
    UniqueFileSelector | ItemAtIndexSelector, Field(discriminator="kind")
]


class ResultReference(ContractModel):
    kind: Literal["CURRENT_PLAN_RESULT"] = "CURRENT_PLAN_RESULT"
    producer_step_position: int = Field(ge=1, le=3)
    # Required producer output, before selection; the selected value is a FILE.
    required_output_kind: Literal["FILE", "ORDERED_FILE_LIST"]
    selector: ResultSelector

    @model_validator(mode="after")
    def compatible_selector(self) -> "ResultReference":
        expected = "FILE" if isinstance(self.selector, UniqueFileSelector) else "ORDERED_FILE_LIST"
        if self.required_output_kind != expected:
            raise ValueError("result selector is incompatible with producer output kind")
        return self


FileReference: TypeAlias = Annotated[
    LiteralFileCandidateReference
    | MetadataSelectorReference
    | PriorFileReference
    | UnspecifiedSingleFileReference
    | ResultReference,
    Field(discriminator="kind"),
]
TargetReference: TypeAlias = Annotated[
    NoTargetReference
    | LiteralFileCandidateReference
    | MetadataSelectorReference
    | PriorFileReference
    | PriorTopicReference
    | HistoryReference
    | UnspecifiedSingleFileReference
    | ResultReference,
    Field(discriminator="kind"),
]
