#!/bin/bash
# Helper script to prepare and push Terminal Talk to GitHub

echo "📡 Preparing Terminal Talk repository for GitHub upload..."

if [ ! -d ".git" ]; then
    git init
    git branch -M main
fi

git add .
git commit -m "Initial commit of Terminal Talk" || true

echo ""
echo "=================================================================="
echo "🚀 GitHubへのアップロード準備が完了しました！"
echo "=================================================================="
echo "以下の3つのコマンドを実行してGitHubにリポジトリを作成・プッシュしてください："
echo ""
echo "1. GitHubで新規リポジトリ名「terminal-talk」をパブリック(Public)で作成"
echo "2. ターミナルで以下を実行（YOUR_USERNAMEをご自身のGitHubユーザー名に変更）："
echo ""
echo "   git remote add origin https://github.com/YOUR_USERNAME/terminal-talk.git"
echo "   git push -u origin main"
echo ""
echo "=================================================================="
echo "🎉 プッシュ完了後、友達に送る1行ダウンロードコマンド："
echo "=================================================================="
echo ""
echo "curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/terminal-talk/main/install.sh | bash"
echo ""
echo "=================================================================="
