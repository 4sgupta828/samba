# Updates to Match batch_rca_discovery.py Style

## Summary of Changes

The analysis code has been updated to match the output style and marker processing from `batch_rca_discovery.py`.

## New Features

### 1. Marker File System
- **RCAInvestigated.marker**: Created when ground truth is found in top-K candidates
  - Contains JSON with rank and top_k information
  - Allows the system to skip already-processed episodes on subsequent runs

- **RCAFailed.marker**: Created when analysis encounters an error
  - Contains error message, error type, and full traceback
  - Episodes with this marker are skipped on subsequent runs

### 2. Smart Episode Processing
- Automatically detects and skips already-processed episodes
- Shows counts of investigated/failed/to-process episodes
- Processes only new or unfinished episodes

### 3. JSON Output per Episode
- Saves detailed results to `rca_analysis.json` in each episode directory
- Includes:
  - Ground truth and top-K candidates
  - Rank of ground truth (if found)
  - Full candidate list with scores and symptoms
  - Causal narratives

### 4. Enhanced Output Formatting
- Professional 80-character separator lines
- Progress tracking: `[N/Total]` for each episode
- Clear status indicators:
  - ✅ Success (found in top-K)
  - ❌ Not in top-K
  - ⚠️  No anomalies detected
  - 🔥 Errors

### 5. Comprehensive Summary Statistics
- Shows total episodes found and processing status
- Breaks down results by:
  - Success rate (found in top-K)
  - Not found in top-K
  - No anomalies detected
  - Errors encountered
- Displays overall success rate including previously investigated episodes
- Lists episodes with errors for easy debugging

### 6. Top-K Configuration
- Configurable via command line: `python3 run_rca_batch.py <dir> <top_k>`
- Default: 5 candidates
- Matches batch_rca_discovery.py behavior

### 7. Nested Directory Support
- Automatically handles both structures:
  - Direct: `data_dir/ep_*/`
  - Nested: `batch_run/data_*/ep_*/`
- Single script handles all cases

## Usage Examples

### Run on single dataset:
```bash
python3 run_rca_batch.py ../data/batch_run/data_20251212_135332/ 5
```

### Run on entire batch:
```bash
python3 run_rca_batch.py ../data/batch_run 5
```

### Or use wrapper script:
```bash
./run_batch_analysis.sh ../data/batch_run 5
```

### Re-run (will skip already processed):
```bash
# Only processes episodes without markers
python3 run_rca_batch.py ../data/batch_run 5
```

### Force re-process using --reprocess flag:
```bash
# Clear all markers and outputs, then reprocess everything
python3 run_rca_batch.py ../data/batch_run 5 --reprocess
```

### Or manually clear markers:
```bash
# Remove all markers to force reprocessing
find ../data/batch_run -name "RCA*.marker" -delete
find ../data/batch_run -name "rca_analysis.json" -delete
python3 run_rca_batch.py ../data/batch_run 5
```

## Output Files Created

For each episode directory:
- `rca_analysis.json` - Detailed analysis results (always created)
- `RCAInvestigated.marker` - Created only if ground truth found in top-K
- `RCAFailed.marker` - Created only on errors

## Comparison with batch_rca_discovery.py

| Feature | batch_rca_discovery.py | run_rca_batch.py (Updated) |
|---------|------------------------|---------------------------|
| Marker files | ✅ | ✅ |
| Skip processed episodes | ✅ | ✅ |
| JSON output per episode | ✅ | ✅ |
| Progress tracking | ✅ | ✅ |
| Error handling | ✅ | ✅ |
| Summary statistics | ✅ | ✅ |
| Top-K configuration | ✅ | ✅ |
| Nested directory support | ✅ | ✅ |
| Output style | ✅ Matched | ✅ Matched |

## Files Modified

1. `run_rca_batch.py` - Main batch processor
   - Added marker file functions
   - Enhanced episode processing with error handling
   - Updated output formatting
   - Added comprehensive summary statistics
   - Added nested directory support

2. `run_batch_analysis.sh` - Wrapper script
   - Simplified (now just calls run_rca_batch.py)
   - Added top_k parameter support

3. `README.md` - Documentation
   - Updated usage examples
   - Added feature list
   - Updated example output

## Testing

All features tested and verified:
- ✅ Marker file creation
- ✅ Skip logic for processed episodes
- ✅ JSON output generation
- ✅ Progress tracking
- ✅ Error handling and recovery
- ✅ Summary statistics accuracy
- ✅ Nested directory processing
- ✅ Top-K configuration
