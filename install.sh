#!/bin/bash
set -e

# Colored Output Tokens
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}"
echo "  _____                          _             _   _____      _ _ "
echo " |_   _|                        |_|           | | |_   _|    | | |"
echo "   | |  ___ _ __ _ __ ___  |_| _ __   __ _| |   | |  __ _| | | __"
echo "   | | / _ \ '__| '_ \` _ \ / _ \| '_ \ / _\` | |   | | / _\` | | |/ /"
echo "   | ||  __/ |  | | | | | |  __/ | | | (_| | |   | || (_| | |   < "
echo "   \_/ \___|_|  |_| |_| |_|\___|_| |_|\__,_|_|   \_/ \__,_|_|_|\_\\"
echo -e "${NC}"
echo -e "${YELLOW}📡 Bluetooth Terminal Chat Auto-Installer${NC}\n"

INSTALL_DIR="$HOME/.terminal-talk"
APP_DIR="$INSTALL_DIR/app"
VENV_DIR="$INSTALL_DIR/venv"

echo -e "${BLUE}[1/5] Checking system environment...${NC}"
OS="$(uname -s)"
echo -e "Detected OS: ${CYAN}$OS${NC}"

# Check for Python 3
INSTALL_PYTHON=false
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}Python 3 is not installed on this device.${NC}"
    INSTALL_PYTHON=true
else
    PYTHON_VER=$(python3 -c 'import sys; print(sys.version_info[0])')
    if [ "$PYTHON_VER" -lt 3 ]; then
        echo -e "${YELLOW}Python version is less than 3.${NC}"
        INSTALL_PYTHON=true
    else
        echo -e "${GREEN}✓ Python 3 is already installed: $(python3 --version)${NC}"
    fi
fi

# Auto-install Python 3 if missing
if [ "$INSTALL_PYTHON" = true ]; then
    echo -e "${YELLOW}[2/5] Automatically installing Python 3...${NC}"
    if [ "$OS" = "Darwin" ]; then
        # macOS
        if command -v brew &> /dev/null; then
            echo -e "${BLUE}Installing Python 3 via Homebrew...${NC}"
            brew install python3
        else
            echo -e "${BLUE}Installing Homebrew and Python 3...${NC}"
            NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)"
            brew install python3
        fi
    elif [ "$OS" = "Linux" ]; then
        # Linux
        if command -v apt-get &> /dev/null; then
            echo -e "${BLUE}Installing Python 3 via apt-get...${NC}"
            sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv
        elif command -v dnf &> /dev/null; then
            echo -e "${BLUE}Installing Python 3 via dnf...${NC}"
            sudo dnf install -y python3 python3-pip
        elif command -v pacman &> /dev/null; then
            echo -e "${BLUE}Installing Python 3 via pacman...${NC}"
            sudo pacman -Sy --noconfirm python python-pip
        else
            echo -e "${RED}Error: Unable to auto-install Python on your Linux distribution. Please install python3 manually.${NC}"
            exit 1
        fi
    fi
fi

echo -e "${BLUE}[3/5] Setting up Terminal Talk directory and virtual environment...${NC}"
mkdir -p "$INSTALL_DIR"
mkdir -p "$APP_DIR"

# Copy source files to APP_DIR if running from local folder
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" 2>/dev/null || echo "." )" && pwd )"
if [ -f "$SCRIPT_DIR/main.py" ]; then
    echo -e "${BLUE}Copying local source files to $APP_DIR...${NC}"
    cp -R "$SCRIPT_DIR/"* "$APP_DIR/"
else
    # Remote execution fallback: download repository archive or files
    echo -e "${BLUE}Downloading application components from GitHub...${NC}"
    # Default repository URL (can be customized by setting REPO_RAW_URL environment variable)
    REPO_RAW_URL="${REPO_RAW_URL:-https://raw.githubusercontent.com/sota/terminal-talk/main}"
    
    mkdir -p "$APP_DIR"
    FILES=("main.py" "ble_manager.py" "ui.py" "config.py" "share.py" "requirements.txt" "README.md")
    for file in "${FILES[@]}"; do
        echo -e "Fetching $file..."
        curl -fsSL "$REPO_RAW_URL/$file" -o "$APP_DIR/$file" || {
            echo -e "${RED}Failed to download $file from $REPO_RAW_URL${NC}"
        }
    done
fi

# Create Virtual Environment
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${BLUE}Creating Python isolated environment...${NC}"
    python3 -m venv "$VENV_DIR"
fi

echo -e "${BLUE}[4/5] Installing Bluetooth & TUI dependencies...${NC}"
"$VENV_DIR/bin/python3" -m pip install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" --quiet

echo -e "${BLUE}[5/5] Registering 'terminal-talk' launcher binary...${NC}"

LAUNCHER="$INSTALL_DIR/terminal-talk"
cat << 'EOF' > "$LAUNCHER"
#!/bin/bash
INSTALL_DIR="$HOME/.terminal-talk"
APP_DIR="$INSTALL_DIR/app"
VENV_DIR="$INSTALL_DIR/venv"
exec "$VENV_DIR/bin/python3" "$APP_DIR/main.py" "$@"
EOF

chmod +x "$LAUNCHER"

# Create symlink in user PATH (~/.local/bin or /usr/local/bin)
TARGET_BIN_DIR="$HOME/.local/bin"
mkdir -p "$TARGET_BIN_DIR"
ln -sf "$LAUNCHER" "$TARGET_BIN_DIR/terminal-talk"

# Ensure ~/.local/bin is in PATH for bash/zsh
SHELL_CONFIG=""
if [ -n "$ZSH_VERSION" ] || [ -f "$HOME/.zshrc" ]; then
    SHELL_CONFIG="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_CONFIG="$HOME/.bashrc"
fi

if [ -n "$SHELL_CONFIG" ]; then
    if ! grep -q "$TARGET_BIN_DIR" "$SHELL_CONFIG"; then
        echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$SHELL_CONFIG"
    fi
fi

export PATH="$HOME/.local/bin:$PATH"

echo -e "\n${GREEN}=====================================================${NC}"
echo -e "${GREEN}🎉 Terminal Talk installed successfully!${NC}"
echo -e "You can now run: ${CYAN}terminal-talk${NC}"
echo -e "${GREEN}=====================================================${NC}\n"

# Prompt to run now
echo -e "Starting Terminal Talk..."
"$LAUNCHER"
