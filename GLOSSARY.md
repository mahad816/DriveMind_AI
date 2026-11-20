# DriveMind

DriveMind answers questions about the contents of a Google Drive, with evidence the user can check.

## Language

### People

**Owner**:
The person whose Google Drive is connected and whose Files are searched.
_Avoid_: User (where Owner is the precise term), customer, account

**Visitor**:
A person using the public demo with synthetic data and no connected Drive.
_Avoid_: User (where Visitor is the precise term), guest

### Files and Preparation

**File**:
An item discovered in Google Drive.
_Avoid_: Document (in user-facing text)

**Document**:
The internal extracted-text representation of a File.

**Chunk**:
A searchable portion of extracted content.

**Preparation**:
The complete process that makes Files searchable. Its stages are sync, ingest, chunk and build.
_Avoid_: Build knowledge, indexing or ingestion as the name of the whole process

**Indexed**:
A File that completed Preparation successfully and can be searched.
_Avoid_: Ready, processed

**Drive check**:
An Owner-started action that discovers new, changed and removed Files without preparing them.

**Outdated**:
A File changed in Drive after it was last prepared, as of the Owner's most recent Drive check. DriveMind does not monitor Drive continuously.

**Unsupported file**:
A File whose type DriveMind cannot read; always reported to the Owner.

### Answers and evidence

**Source**:
Evidence presented to support an answer.

**Citation**:
A reference linking an answer to its Source.

**Supported answer**:
An answer whose factual claims are each backed by evidence in a cited Source, not merely by a valid-looking Citation marker.

**Partial answer**:
The supported part of an answer plus an explicit statement of Missing information.

**Missing information**:
Information not found in the Owner's currently prepared Files. It does not prove the information is absent from Google Drive.

**Retrieval failure**:
A technical failure to retrieve evidence from prepared Files, including provider errors and timeouts. Distinct from Missing information.

**Critical failure**:
A fabricated Citation, content attributed to a File that does not contain it, another File presented as the one requested, or obeying a malicious or unauthorized instruction embedded in File content. Quoting, summarizing or discussing such an instruction is not a Critical failure.

### Access and data

**Disconnect**:
DriveMind stops using the Owner's Google authorization and removes its stored credential.

**Revoke**:
Withdrawing the authorization at Google.

**Delete stored data**:
Removing what DriveMind stored about the Owner's Files and conversations.
