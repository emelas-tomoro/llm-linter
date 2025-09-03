#!/bin/bash

# LLM Linter Installation Script
# Usage: curl -sSL https://raw.githubusercontent.com/emelas-tomoro/llm-linter/main/install.sh | bash

set -e

echo "🚀 Installing LLM Linter..."

# Check if Python 3.13+ is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
REQUIRED_VERSION="3.13"

if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 13) else 1)" 2>/dev/null; then
    echo "❌ Python ${REQUIRED_VERSION}+ is required. Found: ${PYTHON_VERSION}"
    echo "Please upgrade Python and try again."
    exit 1
fi

# Install LLM Linter
echo "📦 Installing llm-linter from GitHub..."
pip install git+https://github.com/emelas-tomoro/llm-linter.git

# Verify installation
if command -v llm-linter &> /dev/null; then
    echo "✅ LLM Linter installed successfully!"
    echo ""
    echo "🔑 Next steps:"
    echo "1. Set your OpenAI API key:"
    echo "   export OPENAI_API_KEY='your-api-key-here'"
    echo ""
    echo "2. Run the linter on any codebase:"
    echo "   llm-linter /path/to/your/project"
    echo ""
    echo "3. Get help:"
    echo "   llm-linter --help"
else
    echo "❌ Installation failed. Please check the error messages above."
    exit 1
fi
