# ProjectOS Demo

## Setup (2 minutes)
1. Clone and install
2. Set GEMINI_API_KEY
3. Point at any Python project

## Demo Sequence (5 minutes)

### Step 1: Index the project
projectos index rebuild
[Expected output: N files indexed]

### Step 2: Trigger a code review  
projectos review src/main.py
[Expected output: review report with issues]

### Step 3: View decisions
projectos decisions --tail 5
[Expected output: 5 recent agent decisions]

### Step 4: Check quality metrics
projectos quality status
[Expected output: per-agent quality scores]

### Step 5: Run the daemon
projectos run --dashboard
[Expected output: live terminal dashboard]
