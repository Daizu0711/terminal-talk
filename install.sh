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
    echo -e "${BLUE}Downloading application components...${NC}"
    
    # Auto-detect if downloaded from local HTTP server or fallback to GitHub
    if [ -n "$HTTP_SHARE_URL" ]; then
        BASE_URL="$HTTP_SHARE_URL"
    else
        BASE_URL="${REPO_RAW_URL:-https://raw.githubusercontent.com/Daizu0711/terminal-talk/main}"
    fi
    
    mkdir -p "$APP_DIR"
    FILES=("main.py" "ble_manager.py" "ui.py" "config.py" "share.py" "requirements.txt" "terminal-talk.spec" "README.md")
    for file in "${FILES[@]}"; do
        echo -e "Fetching $file..."
        curl -fsSL "$BASE_URL/$file" -o "$APP_DIR/$file" || {
            echo -e "${RED}Warning: Could not fetch $file from $BASE_URL${NC}"
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
if [ "$OS" = "Darwin" ]; then
    echo -e "${BLUE}Building macOS app bundle with Bluetooth permission metadata...${NC}"
    "$VENV_DIR/bin/pyinstaller" --clean --noconfirm "$APP_DIR/terminal-talk.spec" --distpath "$APP_DIR/dist" --workpath "$APP_DIR/build"
    APP_EXECUTABLE="$APP_DIR/dist/terminal-talk.app/Contents/MacOS/terminal-talk"
else
    APP_EXECUTABLE=""
fi

if [ "$OS" = "Darwin" ]; then
    cat << EOF > "$LAUNCHER"
#!/bin/bash
exec "$APP_EXECUTABLE" "\$@"
EOF
else
    cat << EOF > "$LAUNCHER"
#!/bin/bash
exec "$VENV_DIR/bin/python3" "$APP_DIR/main.py" "\$@"
EOF
fi

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

# Launch application safely if running directly from terminal
if [ -t 0 ] && [ -f "${BASH_SOURCE[0]}" ] && [ "${BASH_SOURCE[0]}" != "$0" ]; then
    echo -e "${YELLOW}Starting Bluetooth Talk...${NC}"
    "$LAUNCHER"
else
    echo -e "${GREEN}Setup complete! Run ${CYAN}terminal-talk${NC} ${GREEN}to start chatting.${NC}\n"
fi
