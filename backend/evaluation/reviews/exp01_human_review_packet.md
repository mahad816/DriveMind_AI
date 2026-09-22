# EXP-01 Human Review Packet

This packet compares the untouched Gold v1 baseline with EXP-01 for the ten cases selected for targeted human re-review.

## Locked inputs

- Baseline: `evaluation/results/drivemind_gold_v1__20260921T143023Z__f93736aa.json`
- Baseline SHA-256: `f22435ec26a561a248b782bba5f8ded2d3b6ae2bb759db30712e795af53d61db`
- EXP-01: `evaluation/results/drivemind_gold_v1__20260922T101951Z__42b59a1b.json`
- EXP-01 SHA-256: `f32e5d85eab34366a963609411875cba3b94ba025f3a9e395da3bc700c5d115e`
- Gold: `evaluation/datasets/gold_v1.json`
- Gold SHA-256: `9f223c2143e452cea5d85d20d25d0ea6e081bfb92b09d8d13855f0630526e8a0`

The compact artifacts do not contain full prompt-chunk text. They retain source identity, chunk index, rank, text hash/length, and lexical evidence-anchor matches. No missing evidence text has been invented.

## 1. crossdoc_001

### Gold expectation

- Question: How does CoreChain handle healthcare training data, and where does DriveMind store indexed document data and embeddings?
- Expected route: `GROUNDED_RAG`
- Expected files: `CoreChain_Project.txt`, `DriveMind_Project.txt`
- Should answer: `true`
- Reference answer: CoreChain keeps raw healthcare training data at the participating institutions and exchanges model updates for federated learning, while DriveMind uses PostgreSQL for indexed document/application data and Qdrant for vector embeddings.
- Must include: `CoreChain`, `DriveMind`, `PostgreSQL`, `Qdrant`
- Must not include: `CoreChain stores its document embeddings in Qdrant`
- Evidence anchors: `raw healthcare datasets`, `model updates`, `PostgreSQL`, `Qdrant`
- Tags: `multi_doc`, `cross_project`, `semantic_retrieval`, `synthesis`

### Baseline

- Observed route: `GROUNDED_RAG`
- Prompt files: `DriveMind_AI_Implementation_Guide` chunks 2, 1, 0
- Expected-file prompt recall: `0.0`
- Must-include coverage: `1.0`
- Citation expected-source recall: `0.0`
- Outcome: `ANSWERED`
- Cited files: `[1]`, `[2]`, `[3]` — `DriveMind_AI_Implementation_Guide`

#### Final answer

> ## CoreChain Healthcare Training Data and Document Storage
>
> **CoreChain** handles healthcare training data by utilizing a structured process that involves the **Retrieval-Augmented Generation (RAG)** approach. This enables the system to provide grounded answers by using content retrieved from the user's Drive rather than solely relying on pre-existing knowledge.
>
> Document data and embeddings in **DriveMind** are stored in different types of databases to optimize retrieval. Specifically:
>
> - **PostgreSQL** is used to store all structured data, including:
>   - Users
>   - Connected Drive accounts
>   - File metadata
>   - Chunks
>   - Tags
>   - Query history
>   - Indexing status
>   - Evaluation results
>
> - The **Qdrant** or **Chroma** vector databases store embeddings of each chunk, which enable semantic search to retrieve relevant content even when the wording used in a search query does not match the document's wording. Qdrant is recommended for production deployments due to its capabilities like filtering and horizontal scaling.
>
> These structures collaborate with the **LangGraph** orchestration and hybrid retrieval methods to enhance the system's response quality and user interaction visibility.
>
> ### Summary of Key Points
> - **CoreChain** utilizes RAG for healthcare training data.
> - **PostgreSQL** stores structured data.
> - **Qdrant/Chroma** is utilized for storing embeddings crucial for semantic searches [1][2][3].
>
> There's no specific mention of how CoreChain is used in healthcare training data within the provided excerpts beyond the general role of RAG.

#### Existing baseline human review

- Answer correctness: `INCORRECT`
- Grounding: `PARTIALLY_GROUNDED`
- Citation quality: `INCORRECT`
- Primary cause: `PROMPT_SELECTION`
- Notes: Retrieval had found the correct CoreChain and DriveMind files earlier, but the prompt selector excluded both and filled the prompt with DriveMind implementation-guide chunks. The DriveMind half was mostly correct, but the CoreChain half was wrong and described it as RAG-based.

### EXP-01

- Observed route: `GROUNDED_RAG`
- Prompt files: `DriveMind_AI_Implementation_Guide` chunk 2, `DriveMind_Project.txt` chunk 0, `CoreChain_Project.txt` chunk 0
- Expected-file prompt recall: `1.0`
- Must-include coverage: `1.0`
- Citation expected-source recall: `1.0`
- Outcome: `ANSWERED`
- Cited files: `[1]` `CoreChain_Project.txt`; `[2]` `DriveMind_AI_Implementation_Guide`; `[3]` `DriveMind_Project.txt`
- Newly introduced prompt sources: `DriveMind_Project.txt`, `CoreChain_Project.txt`
- Disappeared prompt sources: two repeated `DriveMind_AI_Implementation_Guide` chunks
- Expected-source coverage changed: yes, `0.0 -> 1.0`

#### Final answer

> ## How CoreChain Handles Healthcare Training Data
>
> CoreChain utilizes a **federated learning** approach for training healthcare models, allowing institutions to improve a shared machine-learning model while keeping their **private patient datasets** secure. Here are the essential components of this setup:
>
> - **Client Training**: Each participating healthcare institution trains the model on its own data locally and sends **model updates** to a central federated server instead of sharing raw patient records.
> - **Federated Learning Design**:
>   - Uses the **FedAvg algorithm** for aggregating model updates.
>   - The central server coordinates the training rounds and listens on port **8080**.
>   - Each participating client trains for **5 local epochs** during each of the **10 global training rounds**.
>   - The batch size for local training is set to **32**, and the input shape for the model is **224 by 224 by 3**.
>   - Employs a **convolutional neural network** for binary classification tasks.
>
> The setup emphasizes security and privacy, leveraging **gRPC over HTTP/2** for communication and **TLS** to protect data during transmission. The projects ensure that raw healthcare datasets remain within the institutions themselves, fostering collaboration without compromising privacy [1].
>
> ## Where DriveMind Stores Indexed Document Data and Embeddings
>
> DriveMind organizes its data storage in the following manner:
>
> - **PostgreSQL**:
>   - Stores all **structured data**, including users, connected Drive accounts, document metadata, chunk information, indexing job states, and query history.
>
> - **Qdrant**:
>   - Acts as the **vector database** to store embeddings of each content chunk, enabling **semantic search** to find relevant materials based on meaning rather than exact wording.
>   - It allows for better performance compared to alternatives like Chroma for production deployments.
>
> Files undergo processes of synchronization, extraction, chunking, embedding, and indexing to become searchable. Only files that are indexed are treated as sources of knowledge, with metadata and embeddings being pivotal for enabling effective queries and retrieval [2][3].
>
> No specific information was found regarding the indexed document data’s final storage location beyond the mentioned databases.

### Human judgment

- ANSWER CORRECTNESS: ☐ CORRECT ☐ PARTIAL ☐ INCORRECT
- GROUNDING: ☐ GROUNDED ☐ PARTIALLY_GROUNDED ☐ UNSUPPORTED ☐ NOT_APPLICABLE
- CITATION QUALITY: ☐ COMPLETE ☐ PARTIAL ☐ MISSING ☐ INCORRECT ☐ NOT_APPLICABLE
- PRIMARY FAILURE CAUSE: ☐ NONE ☐ ROUTING ☐ PROMPT_SELECTION ☐ DISTRACTOR_ATTRIBUTION ☐ GENERATION ☐ CITATION ☐ EVALUATOR_FALSE_NEGATIVE ☐ OTHER
- NOTES:
---

## 2. crossdoc_002

### Gold expectation

- Question: What security-related mechanisms are mentioned for CoreChain and DriveMind?
- Expected route: `GROUNDED_RAG`
- Expected files: `CoreChain_Project.txt`, `DriveMind_Project.txt`
- Should answer: `true`
- Reference answer: CoreChain mentions TLS-secured gRPC over HTTP/2 communication, Paillier homomorphic encryption, SHA-256 auditing, and JWT roles. DriveMind's controlled project description emphasizes read-only Google Drive access and its RAG architecture rather than those same CoreChain cryptographic mechanisms.
- Must include: `TLS`, `Paillier`, `SHA-256`, `read-only`, `Google Drive`
- Must not include: `DriveMind uses Paillier homomorphic encryption`; `DriveMind uses blockchain for document storage`
- Evidence anchors: `TLS`, `Paillier`, `SHA-256`, `read-only`
- Tags: `multi_doc`, `cross_project`, `distractor_resistance`, `fact_attribution`

### Baseline

- Observed route: `GROUNDED_RAG`
- Prompt files: `DriveMind_AI_Implementation_Guide` chunk 1, `CoreChain_Project.txt` chunk 0, `DriveMind_AI_Implementation_Guide` chunk 2
- Expected-file prompt recall: `0.5`
- Must-include coverage: `1.0`
- Citation expected-source recall: `0.0`
- Outcome: `ANSWERED`
- Cited files: none

#### Final answer

> ## Security Mechanisms for CoreChain and DriveMind
>
> ### CoreChain Security Mechanisms
> - **Communication Protocol**: CoreChain uses **gRPC over HTTP/2** for communication between the federated server and clients.
> - **Transport Security**: **TLS (Transport Layer Security)** is implemented to secure the communication channel.
> - **Data Security**: Employs **Paillier additive homomorphic encryption** to ensure privacy-preserving aggregation, allowing model updates to be shared without exposing raw patient data.
> - **Audit Mechanism**: Incorporates a blockchain-based audit with a **SHA-256** hash of the global model weights recorded, ensuring integrity and traceability of the training process.
> - **Access Control**: Utilizes **JWT-based roles** to manage access, defining roles such as administrator, researcher, and institution.
>
> ### DriveMind Security Mechanisms
> - **Authentication**: Managed through **FastAPI**, which exposes endpoints to handle user authentication securely.
> - **Data Access**: The system connects to the user's Google Drive via the **Google Drive API**, ensuring read-only access to prevent any modification or deletion of files.
> - **Storage Security**: Uses **PostgreSQL** as the structured data store, safeguarding user data, file metadata, and query history, contributing to overall system reliability.
>
> These mechanisms ensure data integrity, confidentiality, and controlled access for both **CoreChain** and **DriveMind AI** projects, enhancing user trust and compliance with data protection standards.

#### Existing baseline human review

- Answer correctness: `CORRECT`
- Grounding: `PARTIALLY_GROUNDED`
- Citation quality: `MISSING`
- Primary cause: `PROMPT_SELECTION`
- Notes: The factual answer was broadly correct, but DriveMind_Project.txt was lost during prompt selection. The DriveMind portion was supported instead by implementation-guide chunks, and the answer emitted no citation markers.

### EXP-01

- Observed route: `GROUNDED_RAG`
- Prompt files: `DriveMind_AI_Implementation_Guide` chunk 1, `CoreChain_Project.txt` chunk 0, `DriveMind_Project.txt` chunk 1, `DriveMindAI improvements` chunk 1
- Expected-file prompt recall: `1.0`
- Must-include coverage: `0.6`
- Citation expected-source recall: `0.0`
- Outcome: `ANSWERED`
- Cited files: none
- Newly introduced prompt sources: `DriveMind_Project.txt`, `DriveMindAI improvements`
- Disappeared prompt source: the second `DriveMind_AI_Implementation_Guide` chunk
- Expected-source coverage changed: yes, `0.5 -> 1.0`

#### Final answer

> ## Security Mechanisms for CoreChain and DriveMind
>
> ### CoreChain Security Mechanisms
> - **Communication Protocol**: CoreChain uses **gRPC over HTTP/2** for communication between the federated server and clients.
> - **Transport Security**: The system employs **TLS (Transport Layer Security)** to protect communication channels.
> - **Homomorphic Encryption**: It utilizes **Paillier additive homomorphic encryption** to facilitate privacy-preserving aggregation of model updates while ensuring the confidentiality of raw healthcare datasets.
> - **Audit Mechanism**: A **blockchain-based audit** system records a **SHA-256 hash** of the global model weights. This ensures a trustworthy audit path for the training process, including the ability to store evaluation metrics scaled for compactness.
>
> ### DriveMind Security Mechanisms
> - **Access Control**: DriveMind implementation includes **JWT-based roles** to control access within the system. Defined roles include administrator, researcher, and institution.
> - **Containerization**: The application components are containerized using **Docker**, which contributes to consistent security practices across different environments.
>
> ### Summary
> CoreChain's security features focus on ensuring privacy during data training via encryption and communication security, while DriveMind emphasizes controlled access to its system components through role-based management and standardized environments using Docker.

### Human judgment

- ANSWER CORRECTNESS: ☐ CORRECT ☐ PARTIAL ☐ INCORRECT
- GROUNDING: ☐ GROUNDED ☐ PARTIALLY_GROUNDED ☐ UNSUPPORTED ☐ NOT_APPLICABLE
- CITATION QUALITY: ☐ COMPLETE ☐ PARTIAL ☐ MISSING ☐ INCORRECT ☐ NOT_APPLICABLE
- PRIMARY FAILURE CAUSE: ☐ NONE ☐ ROUTING ☐ PROMPT_SELECTION ☐ DISTRACTOR_ATTRIBUTION ☐ GENERATION ☐ CITATION ☐ EVALUATOR_FALSE_NEGATIVE ☐ OTHER
- NOTES:

---

## 3. corechain_003

### Gold expectation

- Question: What was the budget for the CoreChain project?
- Expected route: `GROUNDED_RAG`
- Expected files: `CoreChain_Project.txt`
- Should answer: `false`
- Reference answer: The available CoreChain document does not specify a project budget.
- Must include: none
- Must not include: `CoreChain's budget was PKR 1,200,000`; `CoreChain spent PKR 986,500`
- Evidence anchors: `budget`
- Tags: `abstention`, `missing_fact`, `hallucination_resistance`

### Baseline

- Observed route: `GROUNDED_RAG`
- Prompt files: `P2_Corechain.pdf`, `CoreChain_Project.txt` chunks 0 and 1, `P4_Corechain.pdf`, `Expense_Report_2025.txt`
- Expected-file prompt recall: `1.0`
- Must-include coverage: N/A
- Citation expected-source recall: `0.0`
- Outcome: `ANSWERED`
- Cited files: `[1]` `Expense_Report_2025.txt`

#### Final answer

> The budget for the **CoreChain project** is not directly specified in the available documentation, although it is noted that the **total recorded expenses** amounted to **PKR 986,500** against a total listed budget of **PKR 1,200,000**, leaving a **remaining budget of PKR 213,500**.
>
> ### Detailed Budget Breakdown
> - **Total Budget**: PKR 1,200,000
> - **Total Recorded Expenses**: PKR 986,500
> - **Remaining Budget**: PKR 213,500
>
> ### Expenses Categories
> - **Cloud Services**: PKR 210,000 (largest category)
> - **Travel**: PKR 185,000
> - **Training and Workshops**: PKR 160,000
> - **Software Licenses**: PKR 145,000
> - **Equipment Maintenance**: PKR 110,000
> - **Office Supplies**: PKR 96,500
> - **Miscellaneous Expenses**: PKR 80,000 (smallest category) [1].
>
> There is no specific mention of how these figures tie directly to the CoreChain project or any separate line item attributed specifically to it beyond the general expenses provided.

#### Existing baseline human review

- Answer correctness: `INCORRECT`
- Grounding: `UNSUPPORTED`
- Citation quality: `INCORRECT`
- Primary cause: `DISTRACTOR_ATTRIBUTION`
- Notes: The answer correctly stated that CoreChain's budget was not specified, but then attached unrelated budget figures from Expense_Report_2025.txt to the CoreChain question. Those figures were not evidence about CoreChain.

### EXP-01

- Observed route: `GROUNDED_RAG`
- Prompt files: `P2_Corechain.pdf`, `CoreChain_Project.txt` chunk 0, `P4_Corechain.pdf`, `Expense_Report_2025.txt`
- Expected-file prompt recall: `1.0`
- Must-include coverage: N/A
- Citation expected-source recall: `0.0`
- Outcome: `ANSWERED`
- Cited files: `[1]` `Expense_Report_2025.txt`
- Newly introduced prompt sources: none
- Disappeared prompt content: `CoreChain_Project.txt` chunk 1
- Expected-source coverage changed: no

#### Final answer

> The **budget** for the **CoreChain project** was **PKR 1,200,000**.
>
> ### Details
> - **Total recorded expenses**: PKR 986,500
> - **Remaining budget**: PKR 213,500
> - **Largest category**: Cloud Services (PKR 210,000)
> - **Smallest category**: Miscellaneous Expenses (PKR 80,000)
> - **Other expenses**:
>   - Travel: PKR 185,000
>   - Office Supplies: PKR 96,500
>   - Training and Workshops: PKR 160,000
>   - Software Licenses: PKR 145,000
>   - Equipment Maintenance: PKR 110,000 [1].
>
> ### Gap
> The detailed breakdown of the project budget in terms of specific allocations related to the CoreChain project is not provided in the sources.

### Human judgment

- ANSWER CORRECTNESS: ☐ CORRECT ☐ PARTIAL ☐ INCORRECT
- GROUNDING: ☐ GROUNDED ☐ PARTIALLY_GROUNDED ☐ UNSUPPORTED ☐ NOT_APPLICABLE
- CITATION QUALITY: ☐ COMPLETE ☐ PARTIAL ☐ MISSING ☐ INCORRECT ☐ NOT_APPLICABLE
- PRIMARY FAILURE CAUSE: ☐ NONE ☐ ROUTING ☐ PROMPT_SELECTION ☐ DISTRACTOR_ATTRIBUTION ☐ GENERATION ☐ CITATION ☐ EVALUATOR_FALSE_NEGATIVE ☐ OTHER
- NOTES:

---

## 4. ptcl_003

### Gold expectation

- Question: How much was I paid during the PTCL internship?
- Expected route: `GROUNDED_RAG`
- Expected files: `PTCL_Internship.txt`
- Should answer: `false`
- Reference answer: The PTCL internship document does not specify a salary or stipend.
- Must include: none
- Must not include: `The PTCL internship paid PKR 80,000`; `The PTCL internship paid PKR 100,000`
- Evidence anchors: `salary`, `stipend`
- Tags: `abstention`, `missing_fact`, `personal_fact`, `hallucination_resistance`

### Baseline

- Observed route: `GROUNDED_RAG`
- Prompt files: `Internship_report_Mahad_Ali` chunks 0 and 1, `PTCL_Internship.txt` chunk 0
- Expected-file prompt recall: `1.0`
- Must-include coverage: N/A
- Citation expected-source recall: `0.0`
- Outcome: `ANSWERED`
- Cited files: `[1]` `Internship_report_Mahad_Ali`

#### Final answer

> You were paid **25,000 PKR** during your **PTCL internship** at Ufone.
>
> ### Detailed Information
> The payment structure for the internship is detailed as follows:
>
> - **Internship Duration**: 6 Weeks
> - **Total Payment**: **25,000 PKR**
>
> [1]

#### Existing baseline human review

- Answer correctness: `INCORRECT`
- Grounding: `UNSUPPORTED`
- Citation quality: `INCORRECT`
- Primary cause: `DISTRACTOR_ATTRIBUTION`
- Notes: The PTCL source did not contain salary information, but the model imported PKR 25,000 from a different internship report and attributed it to the PTCL internship.

### EXP-01

- Observed route: `GROUNDED_RAG`
- Prompt files: `Internship_report_Mahad_Ali`, `PTCL_Internship.txt`, `Untitled document`, `Data Engineer - 2026-06-18.pdf`
- Expected-file prompt recall: `1.0`
- Must-include coverage: N/A
- Citation expected-source recall: `0.0`
- Outcome: `ANSWERED`
- Cited files: none
- Newly introduced prompt sources: `Untitled document`, `Data Engineer - 2026-06-18.pdf`
- Disappeared prompt content: second `Internship_report_Mahad_Ali` chunk
- Expected-source coverage changed: no

#### Final answer

> You were paid a total of **20,000 PKR** during your **PTCL internship**.
>
> ### Details
> From the document titled **"PTCL Internship Overview"**, it states:
> - Compensation: **20,000 PKR** for the internship duration.
>
> This amount reflects the payment received for the completion of your project during the internship at PTCL Group.

### Human judgment

- ANSWER CORRECTNESS: ☐ CORRECT ☐ PARTIAL ☐ INCORRECT
- GROUNDING: ☐ GROUNDED ☐ PARTIALLY_GROUNDED ☐ UNSUPPORTED ☐ NOT_APPLICABLE
- CITATION QUALITY: ☐ COMPLETE ☐ PARTIAL ☐ MISSING ☐ INCORRECT ☐ NOT_APPLICABLE
- PRIMARY FAILURE CAUSE: ☐ NONE ☐ ROUTING ☐ PROMPT_SELECTION ☐ DISTRACTOR_ATTRIBUTION ☐ GENERATION ☐ CITATION ☐ EVALUATOR_FALSE_NEGATIVE ☐ OTHER
- NOTES:

---

## 5. distractor_001

### Gold expectation

- Question: What monthly hosting cost does the DriveMind project document specify?
- Expected route: `GROUNDED_RAG`
- Expected files: `DriveMind_Project.txt`
- Should answer: `false`
- Reference answer: The controlled DriveMind project document does not specify a monthly hosting cost.
- Must include: none
- Must not include: `DriveMind's monthly hosting cost was PKR 1,200,000`; `DriveMind's monthly hosting cost was PKR 986,500`; `DriveMind's monthly hosting cost was PKR 210,000`
- Evidence anchors: `monthly hosting cost`, `does not specify`
- Tags: `abstention`, `distractor_resistance`, `fact_attribution`, `hallucination_resistance`

### Baseline

- Observed route: `GROUNDED_RAG`
- Prompt files: `DriveMind_Project.txt` chunks 1 and 0, `DriveMind_AI_Implementation_Guide` chunks 0 and 4
- Expected-file prompt recall: `1.0`
- Must-include coverage: N/A
- Citation expected-source recall: `1.0`
- Outcome: `ANSWERED`
- Cited files: `[1]` `DriveMind_Project.txt`
- Existing baseline human review: none

#### Final answer

> The **DriveMind project document** does not specify the **monthly hosting cost**.
>
> ### Relevant Details
> - The document explicitly states: **"This evaluation document does not specify the monthly hosting cost of DriveMind."** Additionally, it mentions that it does not provide a commercial subscription price, nor does it include any details about user deployment or live retrieval processes, which are all intentional omissions for evaluation purposes [1].

### EXP-01

- Observed route: `GROUNDED_RAG`
- Prompt files: `DriveMind_Project.txt`, `DriveMind_AI_Implementation_Guide`, `DriveMindAI improvements`, `Expense_Report_2025.txt`, `Cloud_Computing_Notes.txt`
- Expected-file prompt recall: `1.0`
- Must-include coverage: N/A
- Citation expected-source recall: `1.0`
- Outcome: `ANSWERED`
- Cited files: `[1]` `DriveMind_Project.txt`; `[2]` `Expense_Report_2025.txt`
- Newly introduced prompt sources: `DriveMindAI improvements`, `Expense_Report_2025.txt`, `Cloud_Computing_Notes.txt`
- Disappeared prompt content: one repeated `DriveMind_Project.txt` chunk and one repeated `DriveMind_AI_Implementation_Guide` chunk
- Expected-source coverage changed: no

#### Final answer

> The **DriveMind project document** does not specify a monthly hosting cost.
>
> ### Details
> - The evaluation document explicitly states: "This evaluation document does not specify the monthly hosting cost of DriveMind" [1].
> - Additionally, it notes: "It does not specify a commercial subscription price" [1].
> - An **Expense Report** also confirms the lack of information regarding the "DriveMind hosting cost" [2].
>
> ### Gap
> No specific monthly hosting costs or commercial subscription prices are present in the available documentation.

### Human judgment

- ANSWER CORRECTNESS: ☐ CORRECT ☐ PARTIAL ☐ INCORRECT
- GROUNDING: ☐ GROUNDED ☐ PARTIALLY_GROUNDED ☐ UNSUPPORTED ☐ NOT_APPLICABLE
- CITATION QUALITY: ☐ COMPLETE ☐ PARTIAL ☐ MISSING ☐ INCORRECT ☐ NOT_APPLICABLE
- PRIMARY FAILURE CAUSE: ☐ NONE ☐ ROUTING ☐ PROMPT_SELECTION ☐ DISTRACTOR_ATTRIBUTION ☐ GENERATION ☐ CITATION ☐ EVALUATOR_FALSE_NEGATIVE ☐ OTHER
- NOTES:

---

## 6. corechain_002

### Gold expectation

- Question: What protected communication between participants in CoreChain?
- Expected route: `GROUNDED_RAG`
- Expected files: `CoreChain_Project.txt`
- Should answer: `true`
- Reference answer: CoreChain used TLS-secured gRPC over HTTP/2 for communication.
- Must include: `TLS`
- Must not include: none
- Evidence anchors: `TLS`, `gRPC`, `HTTP/2`
- Tags: `semantic_retrieval`, `single_doc`, `security`, `distractor_resistance`

### Baseline

- Observed route: `GROUNDED_RAG`
- Prompt files: `P2_Corechain.pdf`, `CoreChain_Project.txt` chunk 0, `P4_Corechain.pdf`, `CoreChain_Project.txt` chunk 1
- Expected-file prompt recall: `1.0`
- Must-include coverage: `1.0`
- Citation expected-source recall: `1.0`
- Outcome: `ANSWERED`
- Cited files: `[1]` `CoreChain_Project.txt`
- Existing baseline human review: none

#### Final answer

> ## Protected Communication in CoreChain
>
> CoreChain utilizes multiple security measures to protect communication between participants:
>
> - **gRPC over HTTP/2**: This framework is used for communication between the federated server and client institutions, ensuring efficient data transmission.
> - **Transport Layer Security (TLS)**: TLS is implemented to secure communication channels, providing encryption and safeguarding the integrity and confidentiality of the data being transmitted.
> - **Paillier Additive Homomorphic Encryption**: This method supports privacy-preserving aggregation experiments, allowing model updates to be processed without revealing the underlying raw data.
>
> These functionalities together ensure that sensitive healthcare data remains protected while still enabling collaboration and compliance with privacy regulations [1].

### EXP-01

- Observed route: `GROUNDED_RAG`
- Prompt files: `P2_Corechain.pdf`, `CoreChain_Project.txt` chunk 0, `P4_Corechain.pdf`, `CCN assignment 2`
- Expected-file prompt recall: `1.0`
- Must-include coverage: `1.0`
- Citation expected-source recall: `1.0`
- Outcome: `ANSWERED`
- Cited files: `[1]` `CoreChain_Project.txt`; `[2]` `P4_Corechain.pdf`
- Newly introduced prompt source: `CCN assignment 2`
- Disappeared prompt content: `CoreChain_Project.txt` chunk 1
- Expected-source coverage changed: no

#### Final answer

> CoreChain ensures **protected communication** between participants through several mechanisms:
>
> ### Overview of Protected Communication
> - **Transport Security**: All communication utilizes **TLS (Transport Layer Security)** to safeguard the communication channel between the federated server and client institutions[1].
>
> - **Advanced Encryption**: The project employs **Paillier additive homomorphic encryption**, allowing for privacy-preserving aggregation of model updates without exposing raw data[1].
>
> - **Federated Learning Design**: Participants train models locally on their data, sending only updates to a central server rather than sharing sensitive datasets directly, further enhancing privacy[1].
>
> ### Additional Aspects
> - **Blockchain Integration**: CoreChain incorporates a blockchain-based audit mechanism, recording a **SHA-256 hash of global model weights** which contributes to transparency and verification, ensuring that all transactions are immutable and verifiable[1][2].
>
> - **Token Reward System**: Institutions receive rewards for their contributions to model training, which incentivizes participation while maintaining compliance and security[2].
>
> The combination of these technologies and practices helps protect **sensitive patient data** during collaboration among healthcare institutions using CoreChain.

### Human judgment

- ANSWER CORRECTNESS: ☐ CORRECT ☐ PARTIAL ☐ INCORRECT
- GROUNDING: ☐ GROUNDED ☐ PARTIALLY_GROUNDED ☐ UNSUPPORTED ☐ NOT_APPLICABLE
- CITATION QUALITY: ☐ COMPLETE ☐ PARTIAL ☐ MISSING ☐ INCORRECT ☐ NOT_APPLICABLE
- PRIMARY FAILURE CAUSE: ☐ NONE ☐ ROUTING ☐ PROMPT_SELECTION ☐ DISTRACTOR_ATTRIBUTION ☐ GENERATION ☐ CITATION ☐ EVALUATOR_FALSE_NEGATIVE ☐ OTHER
- NOTES:

---

## 7. resume_002

### Gold expectation

- Question: How did the CGPA change between my two resume versions?
- Expected route: `GROUNDED_RAG`
- Expected files: `Resume_v1.txt`, `Resume_v2.txt`
- Should answer: `true`
- Reference answer: Resume Version 1 lists a CGPA of 2.40, while Resume Version 2 lists 2.70, an increase of 0.30.
- Must include: `2.40`, `2.70`
- Must not include: `Either resume lists a CGPA of 3.50`
- Evidence anchors: `CGPA`, `2.40`, `2.70`
- Tags: `multi_doc`, `versioning`, `numeric`, `comparison`

### Baseline

- Observed route: `GROUNDED_RAG`
- Prompt files: `Resume_v2.txt`, `Resume_v1.txt`, `Untitled document`
- Expected-file prompt recall: `1.0`
- Must-include coverage: `1.0`
- Citation expected-source recall: `1.0`
- Outcome: `ANSWERED`
- Cited files: `[1]` `Resume_v1.txt`; `[2]` `Resume_v2.txt`
- Existing baseline human review: none

#### Final answer

> ### Change in CGPA Between Resume Versions
>
> The **CGPA** changed from **2.40** in Resume Version 1 to **2.70** in Resume Version 2. This represents an increase of **0.30** points between the two versions.
>
> #### Details
>
> - **Resume Version 1** states:
>   - CGPA: **2.40**
>   - Expected Graduation: **December 2026** [1]
>
> - **Resume Version 2** states:
>   - CGPA: **2.70**
>   - Expected Graduation: **January 2027** [2]
>
> ### Gap
> No additional information about the rationale for the CGPA change was found.

### EXP-01

- Observed route: `GROUNDED_RAG`
- Prompt files: `Resume_v2.txt`, `Resume_v1.txt`, `Untitled document`
- Expected-file prompt recall: `1.0`
- Must-include coverage: `1.0`
- Citation expected-source recall: `0.5`
- Outcome: `ANSWERED`
- Cited files: `[1]` `Resume_v2.txt`
- Newly introduced/disappeared prompt sources: none
- Expected-source coverage changed: no

#### Final answer

> The **CGPA** increased from **2.40** in Resume Version 1 to **2.70** in Resume Version 2.
>
> ### Details
> - In **Resume Version 1**:
>   - **CGPA:** 2.40
>   - **Expected Graduation:** December 2026
>
> - In **Resume Version 2**:
>   - **CGPA:** 2.70
>   - **Expected Graduation:** January 2027
>
> Comparison notes:
> - The change in CGPA reflects an improvement and is part of an overall update that includes additional skills and experiences between the two versions. This change in CGPA was noted as a significant difference between the two resumes:
>   - "CGPA changed from 2.40 to 2.70" [1].
>
> ### Gap
> No additional specific information was requested regarding the cause or context of the CGPA change.

### Human judgment

- ANSWER CORRECTNESS: ☐ CORRECT ☐ PARTIAL ☐ INCORRECT
- GROUNDING: ☐ GROUNDED ☐ PARTIALLY_GROUNDED ☐ UNSUPPORTED ☐ NOT_APPLICABLE
- CITATION QUALITY: ☐ COMPLETE ☐ PARTIAL ☐ MISSING ☐ INCORRECT ☐ NOT_APPLICABLE
- PRIMARY FAILURE CAUSE: ☐ NONE ☐ ROUTING ☐ PROMPT_SELECTION ☐ DISTRACTOR_ATTRIBUTION ☐ GENERATION ☐ CITATION ☐ EVALUATOR_FALSE_NEGATIVE ☐ OTHER
- NOTES:

---

## 8. routing_003

### Gold expectation

- Question: Tell me about the file CoreChain_Project.txt
- Expected route: `FILE_TARGET`
- Expected files: `CoreChain_Project.txt`
- Should answer: `true`
- Reference answer: `null`
- Must include: none
- Must not include: none
- Evidence anchors: `CoreChain_Project.txt`
- Tags: `routing`, `file_target`

### Baseline

- Observed route: `GROUNDED_RAG`
- Prompt files: `P2_Corechain.pdf`, `P4_Corechain.pdf`, `CoreChain_Project.txt`, `P2_Corechain.pdf` chunk 1
- Expected-file prompt recall: `1.0`
- Must-include coverage: N/A
- Citation expected-source recall: `0.0`
- Outcome: `ANSWERED`
- Cited files: none

#### Final answer

> ## CoreChain Project Overview
>
> **CoreChain** is a federated learning project tailored for healthcare institutions, enabling them to train a shared machine-learning model without sharing sensitive patient datasets directly. It employs a federated server and multiple participating client institutions to enhance privacy and collaborative capabilities.
>
> ### Internal Codename
> - The internal codename for the evaluation environment is **Cedar Falcon**, specifically designated for this project.
>
> ### Federated Learning Design
> - **Algorithm Used**: FedAvg for federated aggregation.
> - **Server Coordination**: The central server manages training rounds, collecting model updates from clients.
> - **Server Configuration**:
>   - Listens on **port 8080**.
>   - Conducts **10 global training rounds**.
>   - Each client performs **5 local epochs** during each round.
>   - Local training batch size is **32**, with model input dimensions of **224 by 224 by 3**.
>   - Utilizes a **convolutional neural network** for binary classification.
>   - The **Adam optimizer** is used with **binary cross-entropy loss**.
>
> ### Security and Privacy
> - **Communication Protocol**: gRPC over HTTP/2.
> - **Transport Security**: TLS is implemented for secure communications.
> - **Encryption Method**: Utilizes **Paillier additive homomorphic encryption** for preserving privacy during aggregation.
>
> ### Model Audit and Blockchain
> - A blockchain audit mechanism logs a **SHA-256 hash** of the global model weights.
> - Evaluation metrics are also recorded in the audit, with selected metrics scaled by **10,000** for compact storage.
>
> ### Infrastructure
> - Deployed on **AWS EC2** with containerized application components via **Docker**.
> - **Primary Language**: Python for the federated-learning server and backend logic.
> - **Access Control**: JWT-based role management, including roles such as administrator, researcher, and institution.
>
> ### Project Result
> - **Achievement**: CoreChain secured **second place** in the Data Science category at the **GIKI Industrial Open House 2026**.
>
> ### Controlled Facts
> - Important project-specific details include:
>   - **Internal Codename**: Cedar Falcon
>   - **Federated Aggregation**: FedAvg
>   - **Server Port**: 8080
>   - **Global Training Rounds**: 10
>   - **Local Epochs per Round**: 5
>   - **Batch Size**: 32
>   - **Model Input Dimensions**: 224x224x3
>   - **Communication Protocol**: gRPC over HTTP/2
>   - **Homomorphic Encryption Method**: Paillier
>   - **Audit Hash Algorithm**: SHA-256
>   - **Deployment Platform**: AWS EC2
>   - **Competition Result**: 2nd Place in Data Science
>
> This summary encapsulates the major components and findings from the **CoreChain_Project.txt** file, offering insights into its structure, functionality, and outcomes.

#### Existing baseline human review

- Answer correctness: `CORRECT`
- Grounding: `GROUNDED`
- Citation quality: `MISSING`
- Primary cause: `ROUTING`
- Notes: The content answer was strong and used the expected file, but the system took the wrong route and emitted no citation markers.

### EXP-01

- Observed route: `GROUNDED_RAG`
- Prompt files: `P2_Corechain.pdf`, `P4_Corechain.pdf`, `CoreChain_Project.txt`, `P3_Corechain.pdf`
- Expected-file prompt recall: `1.0`
- Must-include coverage: N/A
- Citation expected-source recall: `1.0`
- Outcome: `ANSWERED`
- Cited files: `[1]` `CoreChain_Project.txt`
- Newly introduced prompt source: `P3_Corechain.pdf`
- Disappeared prompt content: second `P2_Corechain.pdf` chunk
- Expected-source coverage changed: no

#### Final answer

> ## Overview of CoreChain Project
>
> **CoreChain** is a federated learning initiative tailored for healthcare institutions. It facilitates the training of a shared machine-learning model while preserving the privacy of patient datasets, as these datasets are never shared directly.
>
> ### Key Components
> - **Internal Codename**: Cedar Falcon, used for the evaluation environment.
> - **Federated Learning Design**:
>   - Utilizes the **FedAvg** algorithm for model aggregation.
>   - Involves **10 global training rounds** with **5 local epochs** per round.
>   - Each client maintains a local batch size of **32** with an input shape of **224x224x3**.
>   - The project implements a **convolutional neural network** for binary classification.
>
> ### Security and Privacy
> - **gRPC over HTTP/2** is used for communication with **TLS** protection.
> - Incorporates **Paillier additive homomorphic encryption** for privacy-preserving techniques.
>
> ### Infrastructure and Deployment
> - Deployed on **AWS EC2** with application components managed through **Docker**.
> - The primary development language is **Python**, and JWT-based roles are utilized for access control.
>
> ### Project Outcome
> CoreChain earned **second place** in the Data Science category at the GIKI Industrial Open House 2026, highlighting the technical effectiveness and demonstration of the project.
>
> ### Controlled Facts
> - **Federated server port**: 8080
> - **Audit mechanism**: Employs **SHA-256** hashes for model weights and performance metrics.
>
> This comprehensive approach enables healthcare organizations to collaborate securely, ensuring that sensitive data remains within their premises while still contributing to collective model improvements.
>
> References:
> - CoreChain_Project.txt [1]

### Human judgment

- ANSWER CORRECTNESS: ☐ CORRECT ☐ PARTIAL ☐ INCORRECT
- GROUNDING: ☐ GROUNDED ☐ PARTIALLY_GROUNDED ☐ UNSUPPORTED ☐ NOT_APPLICABLE
- CITATION QUALITY: ☐ COMPLETE ☐ PARTIAL ☐ MISSING ☐ INCORRECT ☐ NOT_APPLICABLE
- PRIMARY FAILURE CAUSE: ☐ NONE ☐ ROUTING ☐ PROMPT_SELECTION ☐ DISTRACTOR_ATTRIBUTION ☐ GENERATION ☐ CITATION ☐ EVALUATOR_FALSE_NEGATIVE ☐ OTHER
- NOTES:

---

## 9. resume_004

### Gold expectation

- Question: What are the main differences between Resume Version 1 and Resume Version 2?
- Expected route: `GROUNDED_RAG`
- Expected files: `Resume_v1.txt`, `Resume_v2.txt`
- Should answer: `true`
- Reference answer: Version 2 changes the CGPA from 2.40 to 2.70, changes expected graduation from December 2026 to January 2027, and adds DriveMind and the n8n automation project while retaining the main internship experience.
- Must include: `2.40`, `2.70`, `December 2026`, `January 2027`, `DriveMind`, `n8n`
- Must not include: `Version 2 adds OpenAI employment`; `Version 2 adds a completed UAE internship`
- Evidence anchors: `CGPA`, `Expected Graduation`, `DriveMind`, `n8n`
- Tags: `multi_doc`, `versioning`, `synthesis`, `harder_generation`

### Baseline

- Observed route: `GROUNDED_RAG`
- Prompt files: `Resume_v2.txt`, `Resume_v1.txt`, `DriveMind_AI_Implementation_Guide`
- Expected-file prompt recall: `1.0`
- Must-include coverage: `1.0`
- Citation expected-source recall: `0.0`
- Outcome: `ANSWERED`
- Cited files: none

#### Final answer

> The main differences between **Resume Version 1** and **Resume Version 2** include updates in CGPA, expected graduation date, and the addition of several projects and skills.
>
> ## Key Differences
>
> ### Educational Background
> - **CGPA**: Changed from **2.40** in Version 1 to **2.70** in Version 2.
> - **Expected Graduation**: Updated from **December 2026** in Version 1 to **January 2027** in Version 2.
>
> ### Technical Interests
> - **Version 1**:
>   - Backend engineering
>   - Artificial intelligence
>   - Machine learning
>   - Cloud computing
>   - Web development
>
> - **Version 2**:
>   - AI engineering
>   - Backend engineering
>   - Retrieval-augmented generation
>   - LLM applications
>   - Cloud systems
>   - Automation
>   - ***AI agents***: This is explicitly mentioned as a technical interest in Version 2 but not in Version 1.
>
> ### Projects Included
> - **DriveMind**: Added in Version 2, described as a Google Drive retrieval-augmented generation assistant, utilizing technologies such as FastAPI, PostgreSQL, and LangGraph.
> - **CoreChain**: Listed in both versions but has similar descriptions regarding its federated learning implementations.
> - **Other Projects**:
>   - **Version 1** features the **Operating Systems Producer-Consumer Project**, which is not included in Version 2.
>
> ### Skills and Tools
> - **Databases**:
>   - Version 1 includes **PostgreSQL** and **SQLite**; Version 2 introduces **Qdrant**.
>
> - **Tools**:
>   - **Version 1** lists **Docker** and **AWS**; **Version 2** adds **n8n**.
>
> ## Summary of Additions in Version 2
> - **DriveMind** project inclusion.
> - Additional technical skills:
>   - **LangGraph**
>   - **Qdrant**
>   - **n8n**
> - The CGPA increase, along with a later graduation date.
>
> These changes highlight a more comprehensive skillset and increased academic performance in Resume Version 2 compared to Version 1.

#### Existing baseline human review

- Answer correctness: `CORRECT`
- Grounding: `GROUNDED`
- Citation quality: `MISSING`
- Primary cause: `CITATION`
- Notes: The answer correctly synthesized the differences between both resume versions and all required facts were present, but no citations were emitted despite both source files being available.

### EXP-01

- Observed route: `GROUNDED_RAG`
- Prompt files: `Resume_v2.txt`, `Resume_v1.txt`, `DriveMind_AI_Implementation_Guide`
- Expected-file prompt recall: `1.0`
- Must-include coverage: `1.0`
- Citation expected-source recall: `1.0`
- Outcome: `ANSWERED`
- Cited files: `[1]` `Resume_v2.txt`; `[2]` `Resume_v1.txt`
- Newly introduced/disappeared prompt sources: none
- Expected-source coverage changed: no

#### Final answer

> ## Main Differences Between Resume Version 1 and Resume Version 2
>
> **Resume Version 2** introduces various updates and enhancements compared to **Resume Version 1**.
>
> ### Key Differences:
> 1. **Graduation Date and CGPA**
>    - **Expected Graduation:** Changed from **December 2026** in Version 1 to **January 2027** in Version 2.
>    - **CGPA:** Updated from **2.40** to **2.70**.
>
> 2. **Technical Interests:**
>    - **Added AI Agents** as an explicit technical interest in Version 2.
>
> 3. **Projects:**
>    - **DriveMind** is included in Version 2. This project is described as a **Google Drive retrieval-augmented generation assistant**.
>    - **CoreChain** remains in both versions, but details in Version 1 about **client synchronization** are replaced with the mention of **model aggregation** in Version 2.
>    - An additional automation project using **n8n** is included in Version 2.
>
> 4. **Technical Skills:**
>    - **New Additions in Version 2:**
>      - **LangGraph** as a new skill.
>      - **Qdrant** as a new database/vector store.
>      - **n8n** as a new tool.
>    - The technical AI and Machine Learning section has broader scope in Version 2, including **retrieval-augmented generation** and **AI agents**.
>
> 5. **Experience:**
>    - Both resumes contain similar internship experiences, but the tasks and focus areas have slight variations in wording.
>
> ### Controlled Facts:
> - **Resume Version 1** does **not** include:
>   - DriveMind
>   - **Updated CGPA or graduation date**.
>   - Other additions like **LangGraph, Qdrant,** and **n8n**.
>
> - **Resume Version 2** captures these updates which reflect a more current status and skill set.
>
> #### Citations:
> - Resume Version 2 [1]
> - Resume Version 1 [2]
>
> There are no additional details provided regarding specific projects or experiences beyond what has been summarized.

### Human judgment

- ANSWER CORRECTNESS: ☐ CORRECT ☐ PARTIAL ☐ INCORRECT
- GROUNDING: ☐ GROUNDED ☐ PARTIALLY_GROUNDED ☐ UNSUPPORTED ☐ NOT_APPLICABLE
- CITATION QUALITY: ☐ COMPLETE ☐ PARTIAL ☐ MISSING ☐ INCORRECT ☐ NOT_APPLICABLE
- PRIMARY FAILURE CAUSE: ☐ NONE ☐ ROUTING ☐ PROMPT_SELECTION ☐ DISTRACTOR_ATTRIBUTION ☐ GENERATION ☐ CITATION ☐ EVALUATOR_FALSE_NEGATIVE ☐ OTHER
- NOTES:

---

## 10. semantic_001

### Gold expectation

- Question: In the system I built for searching my Drive, what prevents deleted or failed documents from being used as evidence?
- Expected route: `GROUNDED_RAG`
- Expected files: `DriveMind_Project.txt`
- Should answer: `true`
- Reference answer: DriveMind only allows documents whose DriveFile status is INDEXED to participate in retrieval, so failed, skipped, deleted, or otherwise non-indexed files are excluded from searchable evidence.
- Must include: `INDEXED`
- Must not include: `FAILED files are searchable`; `SKIPPED files are searchable`
- Evidence anchors: `INDEXED`, `searchable`
- Tags: `semantic_retrieval`, `query_rewrite_candidate`, `architecture`, `harder_query`

### Baseline

- Observed route: `GROUNDED_RAG`
- Prompt files: `DriveMind_AI_Implementation_Guide` chunks 7 and 6, `DriveMind_Project.txt` chunk 1
- Expected-file prompt recall: `1.0`
- Must-include coverage: `1.0`
- Citation expected-source recall: `1.0`
- Outcome: `ANSWERED`
- Cited files: `[1]` `DriveMind_Project.txt`; `[2]`, `[3]` `DriveMind_AI_Implementation_Guide`

#### Final answer

> ## Prevention of the Use of Deleted or Failed Documents as Evidence
>
> Deleted or failed documents are prevented from being used as evidence in the system through a rigorous indexing process and the management of file states.
>
> ### Key Mechanisms
>
> 1. **Indexed Status**:
>    - Only files that are in the **indexed state** are considered searchable knowledge sources. Files that are discovered but not successfully indexed are **not treated as normal retrieval evidence**. This ensures that only reliable and intact documents contribute to the evidence pool [1].
>
> 2. **Evidence Grading**:
>    - Retrieved chunks of documents are subjected to a grading process where their quality as evidence is assessed. If the evidence score for a chunk does not meet certain thresholds, the system may redirect the query or decide not to generate an answer based on that evidence [2].
>
> 3. **Removal of Failed Documents**:
>    - Metadata management ensures that any documents marked as **failed** or deleted are excluded from search and retrieval operations. The system’s reliance on metadata allows it to filter out irrelevant or non-existent documents promptly [3][1].
>
> These mechanisms work together to maintain the integrity of the evidence provided to users and ensure that only valid, indexed documents are utilized.
>
> ### Summary
> The system employs an **indexed status requirement**, a robust **evidence grading process**, and careful **metadata management** to prevent the utilization of deleted or failed documents as evidence.

#### Existing baseline human review

- Answer correctness: `CORRECT`
- Grounding: `GROUNDED`
- Citation quality: `PARTIAL`
- Primary cause: `CITATION`
- Notes: The core answer was correct and the expected DriveMind project source was cited. Additional implementation-guide citations were unnecessary but did not make the answer incorrect.

### EXP-01

- Observed route: `GROUNDED_RAG`
- Prompt files: `DriveMind_AI_Implementation_Guide` chunk 7, `DriveMind_Project.txt` chunk 1, `DriveMind_AI_Implementation_Guide` chunk 6
- Expected-file prompt recall: `1.0`
- Must-include coverage: `1.0`
- Citation expected-source recall: `1.0`
- Outcome: `ANSWERED`
- Cited files: `[1]` `DriveMind_Project.txt`
- Newly introduced/disappeared prompt sources: none; the controlled project chunk moved ahead of the second guide chunk
- Expected-source coverage changed: no

#### Final answer

> ## Prevention of Using Deleted or Failed Documents as Evidence
>
> In the system you built for searching your Drive, **only files in the indexed state** are treated as searchable knowledge sources. This means that:
>
> - **Files that have been deleted or failed to index** are not included as valid evidence.
> - A file that is discovered but not successfully indexed **should not be treated as normal retrieval evidence**[1].
>
> This ensures that any document that is deleted or has not been successfully processed cannot be retrieved and used as evidence, maintaining the integrity of the information provided by the system.

### Human judgment

- ANSWER CORRECTNESS: ☐ CORRECT ☐ PARTIAL ☐ INCORRECT
- GROUNDING: ☐ GROUNDED ☐ PARTIALLY_GROUNDED ☐ UNSUPPORTED ☐ NOT_APPLICABLE
- CITATION QUALITY: ☐ COMPLETE ☐ PARTIAL ☐ MISSING ☐ INCORRECT ☐ NOT_APPLICABLE
- PRIMARY FAILURE CAUSE: ☐ NONE ☐ ROUTING ☐ PROMPT_SELECTION ☐ DISTRACTOR_ATTRIBUTION ☐ GENERATION ☐ CITATION ☐ EVALUATOR_FALSE_NEGATIVE ☐ OTHER
- NOTES:
