# Pipeline Separation Design

## Goal
Improve the processing pipeline by strictly separating the transcription phase from the LLM phases. In the automated schedule, all available files should be transcribed first before any LLM processing begins. There should also be an option to manually trigger LLM processing for a single transcribed file.

## Architecture

The pipeline will be restructured to run in horizontal batches rather than processing single files end-to-end. This maximizes efficiency by grouping similar workloads (e.g., all GPU transcription tasks, then all LLM tasks) and allows for a clearer separation of concerns.

### 1. Automated Scheduled Job (`process_pending_files`)
Instead of running `run_pipeline` for each pending file sequentially through all stages, the scheduler will:
- **Phase A: Transcription Batch**
  - Query all files with `status="pending"`.
  - For each, run only the transcription stage (marking them `processing` then `transcribed` or `failed`).
- **Phase B: LLM Translation Batch**
  - Query all files with `status="transcribed"`.
  - For each, run only the translation stage (marking them `translated`).
- **Phase C: LLM Summarization Batch**
  - Query all files with `status="translated"`.
  - For each, run only the summarization stage (marking them `summarized`).
- **Phase D: LLM Extraction & Finalization Batch**
  - Query all files with `status="summarized"`.
  - For each, run extraction, embedding, and Nextcloud upload (marking them `done`).

### 2. Manual Trigger for Single File
A new endpoint `POST /api/process/{file_id}` will be added to `app/routes/process.py` (or a similar location).
- This endpoint will take a `file_id`.
- It will forcefully push that specific file through the remaining LLM stages (Translation -> Summarization -> Extraction) synchronously.
- If the file is still `pending`, it will transcribe it first, then run the LLM stages, acting as a manual override for immediate end-to-end processing.

### 3. Pipeline Service Refactoring (`app/services/pipeline.py`)
`run_pipeline(record)` currently runs all stages. It will be refactored into smaller, composable functions:
- `run_transcription(record)`
- `run_translation(record)`
- `run_summarization(record)`
- `run_extraction_and_finalize(record)`

The batch processor (`process_pending_files`) will iterate over these specific functions in sequence. The manual endpoint will call them sequentially for a single file.

### 4. Token Counting (Future Proofing)
The code will be structured to allow inserting a token-counting utility before the `run_translation` and `run_summarization` steps in the future, checking if the text exceeds 4096 tokens. Comments will be added indicating where this logic should go.

## Data Flow
1. File uploaded -> `status="pending"`
2. Scheduler runs:
   - Finds pending files -> runs `run_transcription` -> `status="transcribed"`
   - Finds transcribed files -> runs `run_translation` -> `status="translated"`
   - Finds translated files -> runs `run_summarization` -> `status="summarized"`
   - Finds summarized files -> runs `run_extraction_and_finalize` -> `status="done"`

## Error Handling
- If `run_transcription` fails, the file is marked `failed`.
- If an LLM stage fails, the file remains in its current state (e.g., `transcribed`), and the batch loop continues to the next file. The failed file will be picked up in the next scheduled run.

## Testing
- Tests in `tests/test_pipeline.py` will need updating to reflect horizontal batching instead of vertical processing.
- New test required for the manual `/api/process/{file_id}` endpoint.
