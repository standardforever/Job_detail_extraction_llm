# Job Detail Extraction LLM

Incremental job scraping workflow built around LangGraph-style nodes.

## Current scope

Node 1 does two things:

1. Connects to a Selenium Grid and confirms a browser session exists.
2. Prepares one browser tab per parallel agent.

This gives us a safe base to keep adding nodes gradually and testing each one before moving on.

## Project structure

```text
.
├── pyproject.toml
├── src/
│   └── job_detail_extraction_llm/
│       ├── config.py
│       ├── graph.py
│       ├── run_node1.py
│       ├── state.py
│       ├── nodes/
│       │   └── session_bootstrap.py
│       └── services/
│           ├── grid_session.py
│           └── tab_manager.py
└── tests/
    ├── test_grid_session.py
    ├── test_session_node.py
    └── test_tab_manager.py
```

## Node 1 behavior

- `grid_session.py`
  - Normalizes the Selenium Grid URL.
  - Reuses an active session when one already exists.
  - Creates a new session when needed.
  - Builds the `cdp_url` we will use in later nodes.

- `tab_manager.py`
  - Ensures `agent_count` tabs are available.
  - If we reused an existing session without a live `WebDriver` handle, tabs are marked as pending so we can attach through CDP in the next step.

- `session_bootstrap.py`
  - Acts as the first workflow node.
  - Returns state containing `session_established`, `session_id`, `cdp_url`, and `agent_tabs`.

## Run Node 1

```bash
PYTHONPATH=src python3 -m job_detail_extraction_llm.run_node1 --agent-count 3
```

Optional environment variable:

```bash
export SELENIUM_REMOTE_URL=http://127.0.0.1:4445/wd/hub
```

## Run tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Next nodes we can add

1. Attach to each agent tab through CDP.
2. Assign one target job URL to each agent.
3. Scrape page content.
4. Extract structured job details with the LLM.
