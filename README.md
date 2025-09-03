# LLM Linter

An intelligent multi-agent linting tool powered by large language models that provides comprehensive code analysis beyond traditional static analysis tools.

## 🚀 Quick Start

```bash
# Install directly from GitHub
pip install git+https://github.com/emelas-tomoro/llm-linter.git

# Set your OpenAI API key
export OPENAI_API_KEY="your-api-key-here"

# Lint any codebase
llm-linter /path/to/your/project
```

Or use the one-liner installation script:
```bash
curl -sSL https://raw.githubusercontent.com/emelas-tomoro/llm-linter/main/install.sh | bash
```

## Overview

LLM Linter uses specialized AI agents to analyze your codebase across multiple dimensions:

- **Complexity Analysis** - Identifies overly long files, classes, and functions
- **Type & Documentation** - Checks Python type hints, docstrings, and comment density
- **Error Handling** - Analyzes try/except patterns and error handling quality
- **Code Duplication** - Detects duplicated code blocks across files
- **Class Design** - Evaluates class cohesion and method placement
- **File Structure** - Assesses directory organization and package structure
- **Testing Coverage** - Estimates test coverage by comparing test files to implementation
- **Security** - Flags common security anti-patterns and potential vulnerabilities

## Installation

### Prerequisites

- Python 3.13+
- OpenAI API key (set as `OPENAI_API_KEY` environment variable)

### Install Directly from Repository (Recommended)

Install the latest version directly from GitHub:

```bash
pip install git+https://github.com/emelas-tomoro/llm-linter.git
```

This installs the `llm-linter` command globally, so you can use it from anywhere:

```bash
llm-linter /path/to/any/codebase
```

### Install Specific Version

Install from a specific release or branch:

```bash
# Install from a specific tag/release
pip install git+https://github.com/emelas-tomoro/llm-linter.git@v0.1.0

# Install from a specific branch
pip install git+https://github.com/emelas-tomoro/llm-linter.git@main
```

### Model Configuration

You can customize which OpenAI models to use via environment variables:

```bash
# Set models via environment variables
export LLM_LINTER_SPECIALIST_MODEL="gpt-5-mini-2025-08-07"      # For specialist agents (default)
export LLM_LINTER_TRIAGE_MODEL="gpt-5-2025-08-07"               # For triage agent (default)
export LLM_LINTER_RECOMMENDATIONS_MODEL="gpt-5-mini-2025-08-07" # For recommendations (default)
```

Or add them to your `.env` file:
```
OPENAI_API_KEY=your-api-key-here
LLM_LINTER_SPECIALIST_MODEL=gpt-5-mini-2025-08-07
LLM_LINTER_TRIAGE_MODEL=gpt-5-2025-08-07
LLM_LINTER_RECOMMENDATIONS_MODEL=gpt-5-mini-2025-08-07
```

**Available Models:**
- `gpt-5-2025-08-07` - Latest GPT-5 model (default for triage)
- `gpt-5-mini-2025-08-07` - GPT-5 mini version (default for specialists)
- `gpt-4o` - GPT-4 Omni, very capable

**Model Roles:**
- **Specialist Model**: Used by all analysis agents (complexity, security, etc.)
- **Triage Model**: Used by the coordinating agent in triage mode
- **Recommendations Model**: Used for generating actionable code suggestions

### Package Structure

This package is configured to be pip-installable through several key files:
- **`pyproject.toml`** - Defines package metadata, dependencies, and creates the `llm-linter` command-line tool
- **`MANIFEST.in`** - Controls which files are included in the package distribution
- **`linter/__init__.py`** - Makes the `linter` directory a proper Python package
- **`linter/core.py`** - Contains the main CLI interface that gets exposed as the `llm-linter` command

The `[project.scripts]` section in `pyproject.toml` creates the `llm-linter` command that maps to `linter.core:main`, allowing users to run the tool from anywhere after installation.

### Model Configuration Priority

Models are selected in the following priority order (highest to lowest):

1. **Command Line Arguments**: `--specialist-model`, `--triage-model`, `--recommendations-model`
2. **Environment Variables**: `LLM_LINTER_SPECIALIST_MODEL`, `LLM_LINTER_TRIAGE_MODEL`, `LLM_LINTER_RECOMMENDATIONS_MODEL`
3. **Default Values**: `gpt-5-mini-2025-08-07` (specialists), `gpt-5-2025-08-07` (triage), 'o4-mini-2025-04-16' (recommendation)

This allows for flexible configuration:
- Set defaults in `.env` files
- Override per-project via environment variables
- Override per-run via command line arguments

## Quick Start Examples

### Team/Organization Usage

For teams, you can standardize on a specific version:

```bash
# Install specific commit
pip install git+https://github.com/emelas-tomoro/llm-linter.git@abc1234

# Install specific branch (e.g., for testing new features)
pip install git+https://github.com/emelas-tomoro/llm-linter.git@feature/new-analysis

# Install specific tag/release
pip install git+https://github.com/emelas-tomoro/llm-linter.git@v0.2.0
```

### CI/CD Integration

Add to your CI pipeline:

```yaml
# GitHub Actions example
- name: Install LLM Linter
  run: pip install git+https://github.com/emelas-tomoro/llm-linter.git

- name: Run LLM Linter
  run: llm-linter . --format json --out lint-report.json
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

### Local Development Workflow

```bash
# Install once
pip install git+https://github.com/emelas-tomoro/llm-linter.git

# Use on any project
cd /path/to/project-a
llm-linter .

cd /path/to/project-b  
llm-linter . --format human

# Update when new features are available
pip install --upgrade git+https://github.com/emelas-tomoro/llm-linter.git
```

## Usage

### Basic Usage

Lint a repository with default settings:

```bash
llm-linter /path/to/your/repository
```

You can also use the module form:
```bash
python -m linter /path/to/your/repository
```

### Command Line Options

```bash
llm-linter [OPTIONS] REPO_PATH
```

**Arguments:**
- `REPO_PATH` - Path to the repository root to lint

**Options:**
- `--rules-path DIR` - Directory containing custom .md/.txt best-practice files
- `--prompt-overrides TEXT` - Extra guidance to augment rules
- `--format {json,human}` - Output format (default: json)
- `--mode {parallel,triage}` - Execution mode (default: parallel)
- `--indent INT` - JSON indent when using json format (default: 2)
- `--out FILE` - Write output to file instead of stdout
- `--log-level {DEBUG,INFO,WARNING,ERROR}` - Logging level (default: INFO)
- `--specialist-model MODEL` - Model for specialist agents (overrides env var)
- `--triage-model MODEL` - Model for triage agent (overrides env var)  
- `--recommendations-model MODEL` - Model for recommendations agent (overrides env var)

### Examples

**Basic linting:**
```bash
llm-linter ./my-project
```

**Human-readable output:**
```bash
llm-linter ./my-project --format human
```

**With custom rules:**
```bash
llm-linter ./my-project --rules-path ./coding-standards
```

**Save results to file:**
```bash
llm-linter ./my-project --out lint-report.json
```

**Verbose logging:**
```bash
llm-linter ./my-project --log-level DEBUG
```

**Custom models via CLI:**
```bash
# Use cost-effective models
llm-linter ./my-project --specialist-model gpt-3.5-turbo --triage-model gpt-4o-mini

# Use high-quality models
llm-linter ./my-project --specialist-model gpt-4o --triage-model gpt-4o --recommendations-model gpt-4o

# Mix and match
llm-linter ./my-project --specialist-model gpt-4o-mini --triage-model gpt-5-2025-08-07
```

## Execution Modes

### Parallel Mode (Default)
Runs all specialized agents concurrently for faster execution. Each agent analyzes different aspects of your code simultaneously.

### Triage Mode
Uses a coordinating agent that orchestrates specialized agents sequentially. May provide more coherent analysis but takes longer.

## Custom Rules

You can provide custom coding standards by creating `.md` or `.txt` files in a directory and using the `--rules-path` option. The linter will load all text files and use them to guide the analysis.

Example rules directory structure:
```
coding-standards/
├── python-style.md
├── security-guidelines.txt
└── team-conventions.md
```

## Output Format

### JSON Output (Default)
Structured output with summary statistics and detailed issues:

```json
{
  "summary": {
    "by_agent": {
      "Complexity Lint Agent": {...},
      "Security Lint Agent": {...}
    },
    "total_issues": 42,
    "recommendations": 15
  },
  "issues": [
    {
      "rule": "function_too_long",
      "path": "src/main.py",
      "line_start": 15,
      "line_end": 85,
      "severity": "warning",
      "message": "Function 'process_data' is 71 lines (>50).",
      "recommendation": "Consider breaking this function into smaller, focused functions.",
      "code_suggestion": "def process_data():\n    # Break into: validate_input(), transform_data(), save_results()"
    }
  ]
}
```

### Human-Readable Output
Formatted text output suitable for terminal viewing:

```
=== Lint Summary ===
- total_issues: 42
- recommendations: 15

=== Issues ===
1. [warning] function_too_long - src/main.py (15-85)
   Function 'process_data' is 71 lines (>50).
   Recommendation: Consider breaking this function into smaller, focused functions.
```

## Supported Languages

- **Python** (.py) - Full analysis including AST parsing for type hints, docstrings, classes, functions
- **TypeScript/JavaScript** (.ts, .tsx, .js, .jsx) - File-level analysis, complexity, and duplication detection

## Environment Variables

The linter will automatically load environment variables from a `.env` file in the target repository root. This is useful for setting API keys on a per-project basis.

## Limitations

- Requires internet connection for LLM API calls
- Analysis quality depends on the underlying language model
- Large repositories may take significant time to analyze
- API costs scale with repository size

## Troubleshooting

**"OPENAI_API_KEY is not set" warning:**
- Set the environment variable or create a `.env` file with your API key

**Long execution times:**
- Use `--mode parallel` (default) for faster execution
- Consider analyzing smaller portions of your codebase first

**High API costs:**
- The tool includes built-in limits to prevent excessive API usage
- Monitor your OpenAI API usage dashboard

## Advanced Installation Options

### Install from GitHub Archive

You can also install from a downloaded archive:

```bash
# Install from latest archive
pip install https://github.com/emelas-tomoro/llm-linter/archive/main.tar.gz

# Install from specific release archive
pip install https://github.com/emelas-tomoro/llm-linter/archive/v0.1.0.tar.gz
```

### Docker Container

Create a Dockerfile for containerized usage:

```dockerfile
FROM python:3.13-slim

# Install git (required for pip install git+)
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Install llm-linter directly from repository
RUN pip install git+https://github.com/emelas-tomoro/llm-linter.git

# Set up working directory
WORKDIR /workspace

# Entry point
ENTRYPOINT ["llm-linter"]
```

Build and use:
```bash
docker build -t llm-linter .
docker run -v $(pwd):/workspace llm-linter /workspace
```

### Update Installation

To update to the latest version:

```bash
pip install --upgrade git+https://github.com/emelas-tomoro/llm-linter.git
```

### Uninstall

```bash
pip uninstall llm-linter
```

## Development Setup

For development, clone and install in editable mode:

```bash
git clone https://github.com/emelas-tomoro/llm-linter.git
cd llm-linter
pip install -e ".[dev]"
```

This allows you to make changes to the code and test them immediately.

## Contributing

The linter is built with a modular agent architecture. Each analysis type is handled by a specialized agent with its own prompt and tools. See the `linter/core.py` file for agent definitions and `linter/prompts/` for agent-specific prompts.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

This project uses the OpenAI API and requires an API key. Please ensure you comply with OpenAI's usage policies.
