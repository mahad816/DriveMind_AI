# EXP-02 Targeted Human Review Packet

Sources: locked Gold v1 dataset, saved EXP-01 result, and saved EXP-02 result. This packet selects 10 cases for human review; it is not a full 24-case review.

- Gold SHA-256: `9f223c2143e452cea5d85d20d25d0ea6e081bfb92b09d8d13855f0630526e8a0`
- EXP-01 artifact SHA-256: `f32e5d85eab34366a963609411875cba3b94ba025f3a9e395da3bc700c5d115e`
- EXP-02 artifact SHA-256: `e7b9af8c98c2f8e1b36620a4076c2c0f131b4075f497fa5e3b16b9bf4b667c0d`

Prompt chunks are identified by filename and chunk index in their saved order. The compact trace does not contain full chunk text. Answers below include the complete `trace.final_answer` wording; trailing line spaces were removed for Markdown hygiene. Deterministic metrics are diagnostics, not human labels.

## crossdoc_001

Review reason: Design target; both sources are retained, while generated wording changed.

Question:
~~~text
How does CoreChain handle healthcare training data, and where does DriveMind store indexed document data and embeddings?
~~~

Gold expectations:

- Expected route: `GROUNDED_RAG`
- Expected files: `["CoreChain_Project.txt", "DriveMind_Project.txt"]`
- Should answer: `true`
- Must include: `["CoreChain", "DriveMind", "PostgreSQL", "Qdrant"]`
- Must not include: `["CoreChain stores its document embeddings in Qdrant"]`

Reference answer:
~~~text
CoreChain keeps raw healthcare training data at the participating institutions and exchanges model updates for federated learning, while DriveMind uses PostgreSQL for indexed document/application data and Qdrant for vector embeddings.
~~~

### EXP-01

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["DriveMind_AI_Implementation_Guide #2", "DriveMind_Project.txt #0", "CoreChain_Project.txt #0"]`
- Unexpected prompt sources according to Gold: `["DriveMind_AI_Implementation_Guide"]`
- Final citations (marker and file): `["[1] CoreChain_Project.txt", "[2] DriveMind_AI_Implementation_Guide", "[3] DriveMind_Project.txt"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 66.67%
- Must-include lexical coverage: 100.00%
- Must-not lexical flags: `[]`
- Citation expected-source recall: 100.00%

Final answer (complete):
~~~text
## How CoreChain Handles Healthcare Training Data

CoreChain utilizes a **federated learning** approach for training healthcare models, allowing institutions to improve a shared machine-learning model while keeping their **private patient datasets** secure. Here are the essential components of this setup:

- **Client Training**: Each participating healthcare institution trains the model on its own data locally and sends **model updates** to a central federated server instead of sharing raw patient records.
- **Federated Learning Design**:
  - Uses the **FedAvg algorithm** for aggregating model updates.
  - The central server coordinates the training rounds and listens on port **8080**.
  - Each participating client trains for **5 local epochs** during each of the **10 global training rounds**.
  - The batch size for local training is set to **32**, and the input shape for the model is **224 by 224 by 3**.
  - Employs a **convolutional neural network** for binary classification tasks.

The setup emphasizes security and privacy, leveraging **gRPC over HTTP/2** for communication and **TLS** to protect data during transmission. The projects ensure that raw healthcare datasets remain within the institutions themselves, fostering collaboration without compromising privacy [1].

## Where DriveMind Stores Indexed Document Data and Embeddings

DriveMind organizes its data storage in the following manner:

- **PostgreSQL**:
  - Stores all **structured data**, including users, connected Drive accounts, document metadata, chunk information, indexing job states, and query history.

- **Qdrant**:
  - Acts as the **vector database** to store embeddings of each content chunk, enabling **semantic search** to find relevant materials based on meaning rather than exact wording.
  - It allows for better performance compared to alternatives like Chroma for production deployments.

Files undergo processes of synchronization, extraction, chunking, embedding, and indexing to become searchable. Only files that are indexed are treated as sources of knowledge, with metadata and embeddings being pivotal for enabling effective queries and retrieval [2][3].

No specific information was found regarding the indexed document data’s final storage location beyond the mentioned databases.
~~~

### EXP-02

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["DriveMind_AI_Implementation_Guide #2", "DriveMind_Project.txt #0", "CoreChain_Project.txt #0"]`
- Unexpected prompt sources according to Gold: `["DriveMind_AI_Implementation_Guide"]`
- Final citations (marker and file): `["[1] CoreChain_Project.txt", "[2] DriveMind_AI_Implementation_Guide", "[3] DriveMind_Project.txt"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 66.67%
- Must-include lexical coverage: 100.00%
- Must-not lexical flags: `[]`
- Citation expected-source recall: 100.00%

Final answer (complete):
~~~text
CoreChain handles healthcare training data by allowing participating institutions to train machine-learning models locally on their own patient datasets without sharing the data directly. Each institution sends model updates to a central federated server instead of the raw data.

### Key Details about CoreChain:
- **Federated Learning Design**:
  - Uses the **FedAvg** algorithm for federated aggregation.
  - The central server coordinates training rounds and collects model updates.
  - Each client institution trains for **5 local epochs** during each round with a batch size of **32**.
  - The model input shape is **224 by 224 by 3**.

- **Security and Privacy**:
  - Utilizes **gRPC over HTTP/2** for communication with **TLS** for security.
  - Employs **Paillier additive homomorphic encryption** to maintain the privacy of patient datasets during aggregation.

### Data Storage in DriveMind:
DriveMind stores indexed document data and embeddings in different systems:
- **PostgreSQL**:
  - Stores structured data including document metadata, extracted content, chunks, indexing job state, and query history.

- **Qdrant**:
  - Functions as the vector database to store embeddings for embedding-based retrieval tasks, enabling semantic search across documents.

### Summary of File Contents:
- **CoreChain_Project.txt** [1]
- **DriveMind_AI_Implementation_Guide** [2]
- **DriveMind_Project.txt** [3]

There are no details available on specific methodologies for handling and training data in healthcare outside of the federated learning framework.
~~~

### Reviewer fields

- Answer correctness:
- Grounding:
- Citation quality:
- Primary failure cause:
- Notes:

Rubric: answer correctness = CORRECT / PARTIAL / INCORRECT; grounding = GROUNDED / PARTIALLY_GROUNDED / UNSUPPORTED; citation quality = COMPLETE / PARTIAL / MISSING / INCORRECT / N/A; primary cause = NONE / ROUTING / RETRIEVAL / RERANK / PROMPT_SELECTION / GENERATION / CITATION / DISTRACTOR_ATTRIBUTION / EVALUATOR_FALSE_NEGATIVE / OTHER.

## crossdoc_002

Review reason: Design target; both sources are retained, but the answer remains lexically incomplete and uncited.

Question:
~~~text
What security-related mechanisms are mentioned for CoreChain and DriveMind?
~~~

Gold expectations:

- Expected route: `GROUNDED_RAG`
- Expected files: `["CoreChain_Project.txt", "DriveMind_Project.txt"]`
- Should answer: `true`
- Must include: `["TLS", "Paillier", "SHA-256", "read-only", "Google Drive"]`
- Must not include: `["DriveMind uses Paillier homomorphic encryption", "DriveMind uses blockchain for document storage"]`

Reference answer:
~~~text
CoreChain mentions TLS-secured gRPC over HTTP/2 communication, Paillier homomorphic encryption, SHA-256 auditing, and JWT roles. DriveMind's controlled project description emphasizes read-only Google Drive access and its RAG architecture rather than those same CoreChain cryptographic mechanisms.
~~~

### EXP-01

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["DriveMind_AI_Implementation_Guide #1", "CoreChain_Project.txt #0", "DriveMind_Project.txt #1", "DriveMindAI improvements #1"]`
- Unexpected prompt sources according to Gold: `["DriveMind_AI_Implementation_Guide", "DriveMindAI improvements"]`
- Final citations (marker and file): `[]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 50.00%
- Must-include lexical coverage: 60.00%
- Must-not lexical flags: `[]`
- Citation expected-source recall: 0.00%

Final answer (complete):
~~~text
## Security Mechanisms for CoreChain and DriveMind

### CoreChain Security Mechanisms
- **Communication Protocol**: CoreChain uses **gRPC over HTTP/2** for communication between the federated server and clients.
- **Transport Security**: The system employs **TLS (Transport Layer Security)** to protect communication channels.
- **Homomorphic Encryption**: It utilizes **Paillier additive homomorphic encryption** to facilitate privacy-preserving aggregation of model updates while ensuring the confidentiality of raw healthcare datasets.
- **Audit Mechanism**: A **blockchain-based audit** system records a **SHA-256 hash** of the global model weights. This ensures a trustworthy audit path for the training process, including the ability to store evaluation metrics scaled for compactness.

### DriveMind Security Mechanisms
- **Access Control**: DriveMind implementation includes **JWT-based roles** to control access within the system. Defined roles include administrator, researcher, and institution.
- **Containerization**: The application components are containerized using **Docker**, which contributes to consistent security practices across different environments.

### Summary
CoreChain's security features focus on ensuring privacy during data training via encryption and communication security, while DriveMind emphasizes controlled access to its system components through role-based management and standardized environments using Docker.
~~~

### EXP-02

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["DriveMind_AI_Implementation_Guide #1", "CoreChain_Project.txt #0", "DriveMind_Project.txt #1", "DriveMindAI improvements #1"]`
- Unexpected prompt sources according to Gold: `["DriveMind_AI_Implementation_Guide", "DriveMindAI improvements"]`
- Final citations (marker and file): `[]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 50.00%
- Must-include lexical coverage: 60.00%
- Must-not lexical flags: `[]`
- Citation expected-source recall: 0.00%

Final answer (complete):
~~~text
## Security-Related Mechanisms in CoreChain and DriveMind

**CoreChain** and **DriveMind** implement several security mechanisms to protect data and ensure integrity.

### CoreChain Security Mechanisms
- **Communication Protocol**: Utilizes **gRPC over HTTP/2** for secure communication between the federated server and clients.
- **Transport Security**: Implements **TLS** (Transport Layer Security) to protect the communication channel.
- **Homomorphic Encryption**: Employs **Paillier additive homomorphic encryption** for privacy-preserving aggregation experiments, ensuring that raw healthcare datasets remain secure at the client institutions.
- **Audit Mechanism**: Incorporates a **blockchain-based audit** system that records a **SHA-256 hash** of the global model weights and evaluation metrics.

### DriveMind Security Mechanisms
- **Backend Framework**: Developed using **FastAPI**, which facilitates secure and efficient API routes.
- **Access Control**: Uses **JWT-based roles** for access control, defining roles such as administrator, researcher, and institution, ensuring that access to various parts of the system is well-managed and secure.

In summary, **CoreChain** emphasizes patient data privacy through advanced encryption and a detailed audit trail, while **DriveMind** focuses on secure API management and defined user roles for access control.

### Information Not Present
No specific mechanisms were identified beyond those mentioned, which encompasses the primary security features of both systems.
~~~

### Reviewer fields

- Answer correctness:
- Grounding:
- Citation quality:
- Primary failure cause:
- Notes:

Rubric: answer correctness = CORRECT / PARTIAL / INCORRECT; grounding = GROUNDED / PARTIALLY_GROUNDED / UNSUPPORTED; citation quality = COMPLETE / PARTIAL / MISSING / INCORRECT / N/A; primary cause = NONE / ROUTING / RETRIEVAL / RERANK / PROMPT_SELECTION / GENERATION / CITATION / DISTRACTOR_ATTRIBUTION / EVALUATOR_FALSE_NEGATIVE / OTHER.

## corechain_003

Review reason: Second CoreChain chunk entered; Expense remains and is cited.

Question:
~~~text
What was the budget for the CoreChain project?
~~~

Gold expectations:

- Expected route: `GROUNDED_RAG`
- Expected files: `["CoreChain_Project.txt"]`
- Should answer: `false`
- Must include: `[]`
- Must not include: `["CoreChain's budget was PKR 1,200,000", "CoreChain spent PKR 986,500"]`

Reference answer:
~~~text
The available CoreChain document does not specify a project budget.
~~~

### EXP-01

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["P2_Corechain.pdf #0", "CoreChain_Project.txt #0", "P4_Corechain.pdf #0", "Expense_Report_2025.txt #1"]`
- Unexpected prompt sources according to Gold: `["P2_Corechain.pdf", "P4_Corechain.pdf", "Expense_Report_2025.txt"]`
- Final citations (marker and file): `["[1] Expense_Report_2025.txt"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 25.00%
- Must-include lexical coverage: N/A
- Must-not lexical flags: `[]`
- Citation expected-source recall: 0.00%

Final answer (complete):
~~~text
The **budget** for the **CoreChain project** was **PKR 1,200,000**.

### Details
- **Total recorded expenses**: PKR 986,500
- **Remaining budget**: PKR 213,500
- **Largest category**: Cloud Services (PKR 210,000)
- **Smallest category**: Miscellaneous Expenses (PKR 80,000)
- **Other expenses**:
  - Travel: PKR 185,000
  - Office Supplies: PKR 96,500
  - Training and Workshops: PKR 160,000
  - Software Licenses: PKR 145,000
  - Equipment Maintenance: PKR 110,000 [1].

### Gap
The detailed breakdown of the project budget in terms of specific allocations related to the CoreChain project is not provided in the sources.
~~~

### EXP-02

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["P2_Corechain.pdf #0", "CoreChain_Project.txt #0", "P4_Corechain.pdf #0", "CoreChain_Project.txt #1", "Expense_Report_2025.txt #1"]`
- Unexpected prompt sources according to Gold: `["P2_Corechain.pdf", "P4_Corechain.pdf", "Expense_Report_2025.txt"]`
- Final citations (marker and file): `["[1] Expense_Report_2025.txt"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 25.00%
- Must-include lexical coverage: N/A
- Must-not lexical flags: `[]`
- Citation expected-source recall: 0.00%

Final answer (complete):
~~~text
The **budget** for the **CoreChain** project is **not explicitly specified** in the provided documentation.

### Details
- While there is an **Expense Report** mentioning a total budget of **PKR 1,200,000**, it does not directly state this amount as the budget for the CoreChain project specifically. Instead, it outlines various expenses related to different categories such as:
  - Cloud Services: PKR 210,000
  - Travel: PKR 185,000
  - Office Supplies: PKR 96,500
  - Training and Workshops: PKR 160,000
  - Software Licenses: PKR 145,000
  - Equipment Maintenance: PKR 110,000
  - Miscellaneous Expenses: PKR 80,000
- Remaining budget recorded is **PKR 213,500** after total expenses of **PKR 986,500** are accounted for [1].

### Gap
No specific mention of the CoreChain project budget was found, indicating that the information may not have been included intentionally per the documentation protocol.
~~~

### Reviewer fields

- Answer correctness:
- Grounding:
- Citation quality:
- Primary failure cause:
- Notes:

Rubric: answer correctness = CORRECT / PARTIAL / INCORRECT; grounding = GROUNDED / PARTIALLY_GROUNDED / UNSUPPORTED; citation quality = COMPLETE / PARTIAL / MISSING / INCORRECT / N/A; primary cause = NONE / ROUTING / RETRIEVAL / RERANK / PROMPT_SELECTION / GENERATION / CITATION / DISTRACTOR_ATTRIBUTION / EVALUATOR_FALSE_NEGATIVE / OTHER.

## ptcl_003

Review reason: Prompt and compensation answer changed; another internship source remains.

Question:
~~~text
How much was I paid during the PTCL internship?
~~~

Gold expectations:

- Expected route: `GROUNDED_RAG`
- Expected files: `["PTCL_Internship.txt"]`
- Should answer: `false`
- Must include: `[]`
- Must not include: `["The PTCL internship paid PKR 80,000", "The PTCL internship paid PKR 100,000"]`

Reference answer:
~~~text
The PTCL internship document does not specify a salary or stipend.
~~~

### EXP-01

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["Internship_report_Mahad_Ali #0", "PTCL_Internship.txt #0", "Untitled document #0", "Data Engineer - 2026-06-18.pdf #0"]`
- Unexpected prompt sources according to Gold: `["Internship_report_Mahad_Ali", "Untitled document", "Data Engineer - 2026-06-18.pdf"]`
- Final citations (marker and file): `[]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 25.00%
- Must-include lexical coverage: N/A
- Must-not lexical flags: `[]`
- Citation expected-source recall: 0.00%

Final answer (complete):
~~~text
You were paid a total of **20,000 PKR** during your **PTCL internship**.

### Details
From the document titled **"PTCL Internship Overview"**, it states:
- Compensation: **20,000 PKR** for the internship duration.

This amount reflects the payment received for the completion of your project during the internship at PTCL Group.
~~~

### EXP-02

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["Internship_report_Mahad_Ali #0", "PTCL_Internship.txt #0", "Internship_report_Mahad_Ali #1"]`
- Unexpected prompt sources according to Gold: `["Internship_report_Mahad_Ali"]`
- Final citations (marker and file): `["[1] Internship_report_Mahad_Ali", "[2] PTCL_Internship.txt"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 50.00%
- Must-include lexical coverage: N/A
- Must-not lexical flags: `[]`
- Citation expected-source recall: 100.00%

Final answer (complete):
~~~text
You were not mentioned as receiving any payment during your internship at PTCL. The context provided does not include details about compensation or stipend amounts.

### Relevant Content Found
- Your **internship duration** was **6 weeks** and you were involved in the "U-Analyzer" project at Ufone, a subsidiary of PTCL Group, but there's no information on payment or stipend mentioned in your reports [1][2].

### Gap
Details regarding your compensation during the internship were not provided in the available documents.
~~~

### Reviewer fields

- Answer correctness:
- Grounding:
- Citation quality:
- Primary failure cause:
- Notes:

Rubric: answer correctness = CORRECT / PARTIAL / INCORRECT; grounding = GROUNDED / PARTIALLY_GROUNDED / UNSUPPORTED; citation quality = COMPLETE / PARTIAL / MISSING / INCORRECT / N/A; primary cause = NONE / ROUTING / RETRIEVAL / RERANK / PROMPT_SELECTION / GENERATION / CITATION / DISTRACTOR_ATTRIBUTION / EVALUATOR_FALSE_NEGATIVE / OTHER.

## distractor_001

Review reason: Expense and Cloud left the prompt; review negative answer and citation discipline.

Question:
~~~text
What monthly hosting cost does the DriveMind project document specify?
~~~

Gold expectations:

- Expected route: `GROUNDED_RAG`
- Expected files: `["DriveMind_Project.txt"]`
- Should answer: `false`
- Must include: `[]`
- Must not include: `["DriveMind's monthly hosting cost was PKR 1,200,000", "DriveMind's monthly hosting cost was PKR 986,500", "DriveMind's monthly hosting cost was PKR 210,000"]`

Reference answer:
~~~text
The controlled DriveMind project document does not specify a monthly hosting cost.
~~~

### EXP-01

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["DriveMind_Project.txt #1", "DriveMind_AI_Implementation_Guide #0", "DriveMindAI improvements #1", "Expense_Report_2025.txt #1", "Cloud_Computing_Notes.txt #1"]`
- Unexpected prompt sources according to Gold: `["DriveMind_AI_Implementation_Guide", "DriveMindAI improvements", "Expense_Report_2025.txt", "Cloud_Computing_Notes.txt"]`
- Final citations (marker and file): `["[1] DriveMind_Project.txt", "[2] Expense_Report_2025.txt"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 20.00%
- Must-include lexical coverage: N/A
- Must-not lexical flags: `[]`
- Citation expected-source recall: 100.00%

Final answer (complete):
~~~text
The **DriveMind project document** does not specify a monthly hosting cost.

### Details
- The evaluation document explicitly states: "This evaluation document does not specify the monthly hosting cost of DriveMind" [1].
- Additionally, it notes: "It does not specify a commercial subscription price" [1].
- An **Expense Report** also confirms the lack of information regarding the "DriveMind hosting cost" [2].

### Gap
No specific monthly hosting costs or commercial subscription prices are present in the available documentation.
~~~

### EXP-02

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["DriveMind_Project.txt #1", "DriveMind_AI_Implementation_Guide #0", "DriveMind_Project.txt #0", "DriveMind_AI_Implementation_Guide #4"]`
- Unexpected prompt sources according to Gold: `["DriveMind_AI_Implementation_Guide"]`
- Final citations (marker and file): `["[1] DriveMind_Project.txt"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 50.00%
- Must-include lexical coverage: N/A
- Must-not lexical flags: `[]`
- Citation expected-source recall: 100.00%

Final answer (complete):
~~~text
The DriveMind project documentation does not specify the **monthly hosting cost**.

### Details
- **Information Not Present**: The document explicitly mentions that it **does not specify the monthly hosting cost of DriveMind** and does not include details on a commercial subscription price or user deployment scale. These omissions are made intentionally for later evaluation [1].

No additional information regarding the cost or financial aspects is provided.
~~~

### Reviewer fields

- Answer correctness:
- Grounding:
- Citation quality:
- Primary failure cause:
- Notes:

Rubric: answer correctness = CORRECT / PARTIAL / INCORRECT; grounding = GROUNDED / PARTIALLY_GROUNDED / UNSUPPORTED; citation quality = COMPLETE / PARTIAL / MISSING / INCORRECT / N/A; primary cause = NONE / ROUTING / RETRIEVAL / RERANK / PROMPT_SELECTION / GENERATION / CITATION / DISTRACTOR_ATTRIBUTION / EVALUATOR_FALSE_NEGATIVE / OTHER.

## corechain_002

Review reason: Second CoreChain chunk entered and the cited-file set changed.

Question:
~~~text
What protected communication between participants in CoreChain?
~~~

Gold expectations:

- Expected route: `GROUNDED_RAG`
- Expected files: `["CoreChain_Project.txt"]`
- Should answer: `true`
- Must include: `["TLS"]`
- Must not include: `[]`

Reference answer:
~~~text
CoreChain used TLS-secured gRPC over HTTP/2 for communication.
~~~

### EXP-01

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["P2_Corechain.pdf #0", "CoreChain_Project.txt #0", "P4_Corechain.pdf #0", "CCN assignment 2 #1"]`
- Unexpected prompt sources according to Gold: `["P2_Corechain.pdf", "P4_Corechain.pdf", "CCN assignment 2"]`
- Final citations (marker and file): `["[1] CoreChain_Project.txt", "[2] P4_Corechain.pdf"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 25.00%
- Must-include lexical coverage: 100.00%
- Must-not lexical flags: `[]`
- Citation expected-source recall: 100.00%

Final answer (complete):
~~~text
CoreChain ensures **protected communication** between participants through several mechanisms:

### Overview of Protected Communication
- **Transport Security**: All communication utilizes **TLS (Transport Layer Security)** to safeguard the communication channel between the federated server and client institutions[1].

- **Advanced Encryption**: The project employs **Paillier additive homomorphic encryption**, allowing for privacy-preserving aggregation of model updates without exposing raw data[1].

- **Federated Learning Design**: Participants train models locally on their data, sending only updates to a central server rather than sharing sensitive datasets directly, further enhancing privacy[1].

### Additional Aspects
- **Blockchain Integration**: CoreChain incorporates a blockchain-based audit mechanism, recording a **SHA-256 hash of global model weights** which contributes to transparency and verification, ensuring that all transactions are immutable and verifiable[1][2].

- **Token Reward System**: Institutions receive rewards for their contributions to model training, which incentivizes participation while maintaining compliance and security[2].

The combination of these technologies and practices helps protect **sensitive patient data** during collaboration among healthcare institutions using CoreChain.
~~~

### EXP-02

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["P2_Corechain.pdf #0", "CoreChain_Project.txt #0", "P4_Corechain.pdf #0", "CoreChain_Project.txt #1"]`
- Unexpected prompt sources according to Gold: `["P2_Corechain.pdf", "P4_Corechain.pdf"]`
- Final citations (marker and file): `["[1] P2_Corechain.pdf", "[2] CoreChain_Project.txt", "[3] P4_Corechain.pdf"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 33.33%
- Must-include lexical coverage: 100.00%
- Must-not lexical flags: `[]`
- Citation expected-source recall: 100.00%

Final answer (complete):
~~~text
## Protected Communication in CoreChain

**CoreChain** implements several mechanisms to ensure that communication between participants is secure and private:

- **Transport Security**: All communication utilizes **TLS 1.3** encrypted channels to protect the integrity and confidentiality of data exchanged between client institutions and the federated server [1].

- **Communication Protocol**: The system uses **gRPC over HTTP/2** for communication, further enhancing its security features [2].

- **Privacy-Preserving Techniques**: To support aggregation without compromising individual data, **Paillier additive homomorphic encryption** is employed. This allows model updates to be aggregated securely while keeping raw data at the participating institutions [2].

- **Blockchain-Based Audit Logs**: A SHA-256 hash of the global model weights is recorded as a part of the audit process, ensuring all communications are traceable and verifiable, providing an extra layer of trust [2][3].

In conclusion, CoreChain's architecture prioritizes **privacy** and **security** through end-to-end encryption, advanced communication protocols, and homomorphic encryption techniques.

**No specific communication details about participant identities or methods for direct exchanges were found in the provided materials.**
~~~

### Reviewer fields

- Answer correctness:
- Grounding:
- Citation quality:
- Primary failure cause:
- Notes:

Rubric: answer correctness = CORRECT / PARTIAL / INCORRECT; grounding = GROUNDED / PARTIALLY_GROUNDED / UNSUPPORTED; citation quality = COMPLETE / PARTIAL / MISSING / INCORRECT / N/A; primary cause = NONE / ROUTING / RETRIEVAL / RERANK / PROMPT_SELECTION / GENERATION / CITATION / DISTRACTOR_ATTRIBUTION / EVALUATOR_FALSE_NEGATIVE / OTHER.

## corechain_004

Review reason: Prompt changed and the answer names an institution for a hospital deployment question.

Question:
~~~text
Which hospital deployed CoreChain in production?
~~~

Gold expectations:

- Expected route: `GROUNDED_RAG`
- Expected files: `["CoreChain_Project.txt"]`
- Should answer: `false`
- Must include: `[]`
- Must not include: `["Shifa deployed CoreChain in production", "PIMS deployed CoreChain in production", "Aga Khan deployed CoreChain in production"]`

Reference answer:
~~~text
The controlled CoreChain document does not identify any hospital that deployed the system in production.
~~~

### EXP-01

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["P4_Corechain.pdf #0", "CoreChain_Project.txt #0", "P2_Corechain.pdf #0", "P3_Corechain.pdf #0", "DBMS PROJECT #0"]`
- Unexpected prompt sources according to Gold: `["P4_Corechain.pdf", "P2_Corechain.pdf", "P3_Corechain.pdf", "DBMS PROJECT"]`
- Final citations (marker and file): `["[1] P4_Corechain.pdf", "[2] CoreChain_Project.txt", "[3] P2_Corechain.pdf", "[4] P3_Corechain.pdf"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 20.00%
- Must-include lexical coverage: N/A
- Must-not lexical flags: `[]`
- Citation expected-source recall: 100.00%

Final answer (complete):
~~~text
## Hospital Deployment

**The hospital that deployed CoreChain in production is not explicitly mentioned in the provided content.**

### Relevant Details

- **CoreChain** is designed for **healthcare institutions** to engage in federated learning without compromising patient data privacy.
- The significant features include:
  - Local model training, encrypted data transmission, and blockchain logging.
  - A central **aggregator server** facilitates training and keeps patient data secure at local institutions.

However, specific names of hospitals involved in the **CoreChain** deployment are not included in the available documents [1][2][3][4].
~~~

### EXP-02

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["P4_Corechain.pdf #0", "CoreChain_Project.txt #0", "P2_Corechain.pdf #0", "P3_Corechain.pdf #0"]`
- Unexpected prompt sources according to Gold: `["P4_Corechain.pdf", "P2_Corechain.pdf", "P3_Corechain.pdf"]`
- Final citations (marker and file): `["[1] CoreChain_Project.txt"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 25.00%
- Must-include lexical coverage: N/A
- Must-not lexical flags: `[]`
- Citation expected-source recall: 100.00%

Final answer (complete):
~~~text
CoreChain was deployed in production by the **Ghulam Ishaq Khan Institute of Engineering Sciences and Technology** as part of their final year project presentation and demonstration. The project received **second place** in the Data Science category at the GIKI Industrial Open House 2026 for its implementation and technical aspects. [1]
~~~

### Reviewer fields

- Answer correctness:
- Grounding:
- Citation quality:
- Primary failure cause:
- Notes:

Rubric: answer correctness = CORRECT / PARTIAL / INCORRECT; grounding = GROUNDED / PARTIALLY_GROUNDED / UNSUPPORTED; citation quality = COMPLETE / PARTIAL / MISSING / INCORRECT / N/A; primary cause = NONE / ROUTING / RETRIEVAL / RERANK / PROMPT_SELECTION / GENERATION / CITATION / DISTRACTOR_ATTRIBUTION / EVALUATOR_FALSE_NEGATIVE / OTHER.

## routing_002

Review reason: Inventory routing remains wrong and the new answer drops citations.

Question:
~~~text
What files do I have in my knowledge base?
~~~

Gold expectations:

- Expected route: `FILE_INVENTORY`
- Expected files: `[]`
- Should answer: `true`
- Must include: `[]`
- Must not include: `[]`

Reference answer:
~~~text
(none)
~~~

### EXP-01

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["DriveMind_AI_Implementation_Guide #15", "DriveMind_Project.txt #1", "DriveMind_AI_Implementation_Guide #7"]`
- Unexpected prompt sources according to Gold: `[]`
- Final citations (marker and file): `["[1] DriveMind_AI_Implementation_Guide", "[2] DriveMind_Project.txt"]`
- Prompt expected-file recall: N/A
- Prompt expected-source precision: N/A
- Must-include lexical coverage: N/A
- Must-not lexical flags: `[]`
- Citation expected-source recall: N/A

Final answer (complete):
~~~text
## Files in Your Knowledge Base

You have the following files in your knowledge base:

1. **DriveMind_AI_Implementation_Guide**
   - This guide includes detailed implementation strategies for DriveMind AI, including evaluation plans, hybrid retrieval processes, metadata retrieval, and system architecture.

2. **DriveMind_Project.txt**
   - This document covers the technology stack, indexing and searchability, and specific controlled facts related to the DriveMind framework.

These files are part of the indexed state within your system, making them searchable knowledge sources [1][2].
~~~

### EXP-02

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["DriveMind_AI_Implementation_Guide #15", "DriveMind_Project.txt #1", "DriveMind_AI_Implementation_Guide #7"]`
- Unexpected prompt sources according to Gold: `[]`
- Final citations (marker and file): `[]`
- Prompt expected-file recall: N/A
- Prompt expected-source precision: N/A
- Must-include lexical coverage: N/A
- Must-not lexical flags: `[]`
- Citation expected-source recall: N/A

Final answer (complete):
~~~text
## Your Knowledge Base Files

You have the following files indexed in your knowledge base:

1. **DriveMind_AI_Implementation_Guide**
   - This guide contains implementation details such as query rewriting prompts, results configurations, and evaluation plans pertaining to the DriveMind AI project.

2. **DriveMind_Project.txt**
   - A text file that discusses indexing, searchability, technology used, and controlled facts specific to the DriveMind project.

### Key Points on Indexed Files

- Indexed files are treated as searchable knowledge sources.
- The indexed files must pass through a process of synchronization, extraction, chunking, embedding, and indexing to be considered usable for queries.

This summary includes the names and brief descriptions of the files but does not enumerate other specific files or documents in your Google Drive if they are not mentioned.
~~~

### Reviewer fields

- Answer correctness:
- Grounding:
- Citation quality:
- Primary failure cause:
- Notes:

Rubric: answer correctness = CORRECT / PARTIAL / INCORRECT; grounding = GROUNDED / PARTIALLY_GROUNDED / UNSUPPORTED; citation quality = COMPLETE / PARTIAL / MISSING / INCORRECT / N/A; primary cause = NONE / ROUTING / RETRIEVAL / RERANK / PROMPT_SELECTION / GENERATION / CITATION / DISTRACTOR_ATTRIBUTION / EVALUATOR_FALSE_NEGATIVE / OTHER.

## resume_001

Review reason: Both resume sources are now cited; verify version attribution.

Question:
~~~text
Which version of my resume includes the DriveMind project?
~~~

Gold expectations:

- Expected route: `GROUNDED_RAG`
- Expected files: `["Resume_v1.txt", "Resume_v2.txt"]`
- Should answer: `true`
- Must include: `["Resume Version 2", "DriveMind"]`
- Must not include: `["Resume Version 1 includes DriveMind as a project"]`

Reference answer:
~~~text
DriveMind is included in Resume Version 2 and is not included as a project in Resume Version 1.
~~~

### EXP-01

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["Resume_v1.txt #0", "Resume_v2.txt #0", "DriveMind_AI_Implementation_Guide #0"]`
- Unexpected prompt sources according to Gold: `["DriveMind_AI_Implementation_Guide"]`
- Final citations (marker and file): `["[1] Resume_v2.txt"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 66.67%
- Must-include lexical coverage: 100.00%
- Must-not lexical flags: `[]`
- Citation expected-source recall: 50.00%

Final answer (complete):
~~~text
The **DriveMind project** is included in **Resume Version 2**.

### Details
The resume states:
- **DriveMind** is described as a Google Drive retrieval-augmented generation assistant.
- It utilizes several technologies, including:
  - **FastAPI**
  - **PostgreSQL**
  - **Qdrant**
  - **Google Drive APIs**
  - **OpenAI embeddings**
  - **hybrid retrieval**
  - **LangGraph**

### Summary of DriveMind's Functionality
- DriveMind retrieves evidence from indexed Drive files and generates grounded answers with citations.
- It connects to a user's Google Drive, indexes various file types, and enables natural-language search functionalities, thus enhancing the search capabilities beyond basic text search.

Controlled facts about **Resume Version 2** also note that it:
- Has an expected graduation date of **January 2027**.
- Lists the **CGPA** as **2.70**.
- Includes prior internships and projects like **CoreChain**, which received recognition at the GIKI Industrial Open House 2026.

This information is not present in **Resume Version 1**, which explicitly states that DriveMind is **not included**. Therefore, the inclusion of the DriveMind project can only be found in **Resume Version 2** [1].
~~~

### EXP-02

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["Resume_v1.txt #0", "Resume_v2.txt #0", "DriveMind_AI_Implementation_Guide #0"]`
- Unexpected prompt sources according to Gold: `["DriveMind_AI_Implementation_Guide"]`
- Final citations (marker and file): `["[1] Resume_v2.txt", "[2] Resume_v1.txt"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 66.67%
- Must-include lexical coverage: 100.00%
- Must-not lexical flags: `[]`
- Citation expected-source recall: 100.00%

Final answer (complete):
~~~text
The version of your resume that includes the **DriveMind project** is **Resume Version 2**.

### Details
- **DriveMind**: This project is described in Resume Version 2 as a **Google Drive retrieval-augmented generation assistant**. It uses several technologies including:
  - **FastAPI**
  - **PostgreSQL**
  - **Qdrant**
  - **Google Drive APIs**
  - **OpenAI embeddings**
  - **Hybrid retrieval**
  - **LangGraph**

- The resume states that DriveMind retrieves evidence from indexed Drive files and generates grounded answers with citations.

Controlled Resume Facts specific to Resume Version 2:
- **Expected graduation**: January 2027
- **CGPA**: 2.70
- **CoreChain** is included
- **DriveMind** is included
- **PTCL / Ufone internship** is included
- **Pakistan Institute of Education internship** is included
- **LangGraph** is listed as a skill
- **Qdrant** is listed as a database/vector store
- **n8n** is listed as a tool[1].

Resume Version 1 does NOT include the DriveMind project, as it only features **CoreChain** and various internships but explicitly states that DriveMind is absent [2].
~~~

### Reviewer fields

- Answer correctness:
- Grounding:
- Citation quality:
- Primary failure cause:
- Notes:

Rubric: answer correctness = CORRECT / PARTIAL / INCORRECT; grounding = GROUNDED / PARTIALLY_GROUNDED / UNSUPPORTED; citation quality = COMPLETE / PARTIAL / MISSING / INCORRECT / N/A; primary cause = NONE / ROUTING / RETRIEVAL / RERANK / PROMPT_SELECTION / GENERATION / CITATION / DISTRACTOR_ATTRIBUTION / EVALUATOR_FALSE_NEGATIVE / OTHER.

## resume_002

Review reason: Both resume sources are now cited; verify CGPA attribution.

Question:
~~~text
How did the CGPA change between my two resume versions?
~~~

Gold expectations:

- Expected route: `GROUNDED_RAG`
- Expected files: `["Resume_v1.txt", "Resume_v2.txt"]`
- Should answer: `true`
- Must include: `["2.40", "2.70"]`
- Must not include: `["Either resume lists a CGPA of 3.50"]`

Reference answer:
~~~text
Resume Version 1 lists a CGPA of 2.40, while Resume Version 2 lists 2.70, an increase of 0.30.
~~~

### EXP-01

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["Resume_v2.txt #0", "Resume_v1.txt #0", "Untitled document #0"]`
- Unexpected prompt sources according to Gold: `["Untitled document"]`
- Final citations (marker and file): `["[1] Resume_v2.txt"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 66.67%
- Must-include lexical coverage: 100.00%
- Must-not lexical flags: `[]`
- Citation expected-source recall: 50.00%

Final answer (complete):
~~~text
The **CGPA** increased from **2.40** in Resume Version 1 to **2.70** in Resume Version 2.

### Details
- In **Resume Version 1**:
  - **CGPA:** 2.40
  - **Expected Graduation:** December 2026

- In **Resume Version 2**:
  - **CGPA:** 2.70
  - **Expected Graduation:** January 2027

Comparison notes:
- The change in CGPA reflects an improvement and is part of an overall update that includes additional skills and experiences between the two versions. This change in CGPA was noted as a significant difference between the two resumes:
  - "CGPA changed from 2.40 to 2.70" [1].

### Gap
No additional specific information was requested regarding the cause or context of the CGPA change.
~~~

### EXP-02

- Observed route: `GROUNDED_RAG`
- Outcome: `ANSWERED`
- Prompt chunks in order: `["Resume_v2.txt #0", "Resume_v1.txt #0", "Untitled document #0"]`
- Unexpected prompt sources according to Gold: `["Untitled document"]`
- Final citations (marker and file): `["[1] Resume_v1.txt", "[2] Resume_v2.txt"]`
- Prompt expected-file recall: 100.00%
- Prompt expected-source precision: 66.67%
- Must-include lexical coverage: 100.00%
- Must-not lexical flags: `[]`
- Citation expected-source recall: 100.00%

Final answer (complete):
~~~text
The **CGPA** changed from **2.40** in Resume Version 1 to **2.70** in Resume Version 2.

### Details
- In **Resume Version 1**, the CGPA is noted as **2.40** while the expected graduation date is **December 2026** [1].
- In **Resume Version 2**, the CGPA increased to **2.70** and the expected graduation date was shifted to **January 2027** [2].
- This indicates an improvement in academic performance reflected in the updated resume.

### Gap
No further specifics on the change in CGPA or reasons for the improvement were found in the provided excerpts.
~~~

### Reviewer fields

- Answer correctness:
- Grounding:
- Citation quality:
- Primary failure cause:
- Notes:

Rubric: answer correctness = CORRECT / PARTIAL / INCORRECT; grounding = GROUNDED / PARTIALLY_GROUNDED / UNSUPPORTED; citation quality = COMPLETE / PARTIAL / MISSING / INCORRECT / N/A; primary cause = NONE / ROUTING / RETRIEVAL / RERANK / PROMPT_SELECTION / GENERATION / CITATION / DISTRACTOR_ATTRIBUTION / EVALUATOR_FALSE_NEGATIVE / OTHER.
