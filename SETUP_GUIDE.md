# Grafana MCP セットアップガイド（SSE接続版）

このガイドでは、Grafana MCPサンプル（SSE接続版）を動作させるための詳細な手順を説明します。

## 前提条件

- Python 3.13以上がインストールされていること
- Dockerがインストールされていること
- OpenAI APIキーを持っていること
- Grafanaインスタンスへのアクセス権限があること

## ステップ1: Grafana Service Account Tokenの取得

1. Grafanaにログイン
2. 左側のメニューから **Administration** > **Service accounts** を選択
3. **Add service account** をクリック
4. 以下の情報を入力：
   - **Display name**: `MCP Integration` (任意の名前)
   - **Role**: `Admin` (推奨) または `Viewer` (読み取り専用の場合)
5. **Create** をクリック
6. **Add service account token** をクリック
7. トークンをコピーして安全な場所に保存

## ステップ2: プロジェクトのセットアップ

```bash
# リポジトリのクローン（または作業ディレクトリへ移動）
cd /path/to/owncall

# 仮想環境の作成
python3 -m venv .venv

# 仮想環境の有効化
source .venv/bin/activate  # Linux/Mac
# または
.venv\Scripts\activate     # Windows

# パッケージのインストール（開発用依存含む）
pip install -e ".[dev]"
```

## ステップ3: 設定ファイルの作成

```bash
cp config.example.yml config.yml
```

`config.yml` を編集します。Slackトークンは環境変数で渡すことを推奨します：

```yaml
llm:
  model: "gpt-5.4-mini"

agent:
  system_prompt: |
    You are an SRE assistant. Use MCP tools to investigate Grafana alerts.
  constraints:
    - "Search only the last 3 hours unless a time range is specified."

mcp_servers:
  - name: "grafana"
    type: "sse"
    url: "http://localhost:8000/sse"
    enabled: true

alert_detection:
  enabled: true
  channels: []
  rules:
    - type: "bot_name"
      pattern: "(?i)grafana|alertmanager|prometheus"

# メンション応答を特定チャンネルに制限する場合に設定
# 未設定の場合は全チャンネルで応答
mention:
  channels: []
```

## ステップ4: 環境変数の設定

```bash
export OPENAI_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxx"
export SLACK_BOT_TOKEN="xoxb-..."
export SLACK_APP_TOKEN="xapp-..."
```

### 環境変数の永続化（オプション）

`~/.zshrc` や `~/.bashrc` に追加する方法：

```bash
echo 'export OPENAI_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxx"' >> ~/.zshrc
source ~/.zshrc
```

## ステップ5: Grafana MCPサーバーの起動

別のターミナルを開いて、以下のコマンドでGrafana MCPサーバーを起動します：

```bash
docker run --rm -p 8000:8000 -i \
  -e GRAFANA_URL=https://your-grafana-instance.com \
  -e GRAFANA_SERVICE_ACCOUNT_TOKEN=glsa_xxxxxxxxxxxxxxxxxxxxx \
  grafana/mcp-grafana -t sse
```

**重要なポイント：**
- `-t sse` オプションを必ず指定してください（SSEモードで起動）
- `GRAFANA_URL` には末尾のスラッシュ不要
- `GRAFANA_SERVICE_ACCOUNT_TOKEN` はGrafanaで生成したトークン

サーバーが起動すると、以下のようなログが表示されます：

```
time=2026-04-23T00:00:00.000Z level=INFO msg="Starting Grafana MCP server using SSE transport"
```

## ステップ6: ボットの起動

```bash
owncall -c config.yml
```

### Docker Compose（all-in-one）

```bash
cp config.example.yml config.yml
export OPENAI_API_KEY=sk-...
export SLACK_BOT_TOKEN=xoxb-...
export SLACK_APP_TOKEN=xapp-...
export GRAFANA_URL=https://your-grafana.example.com
export GRAFANA_SERVICE_ACCOUNT_TOKEN=your-token
docker compose up
```

## ステップ7: 動作確認

環境変数の確認：

```bash
python3 -c "import os; print('OPENAI_API_KEY:', 'OK' if os.getenv('OPENAI_API_KEY') else 'NOT SET')"
```

MCPサーバーへの接続確認：

```bash
curl http://localhost:8000/sse
```

正常に動作している場合、以下のようなレスポンスが返ります：

```
event: endpoint
data: /message?sessionId=...
```

## よくある問題と解決方法

### 1. `zsh: command not found: owncall`

**原因**: パッケージがインストールされていない、または仮想環境が有効化されていない

**解決方法**:
```bash
source .venv/bin/activate
owncall -c config.yml

# または直接パスを指定
.venv/bin/owncall -c config.yml
```

### 2. `ModuleNotFoundError: No module named 'agents'`

**原因**: openai-agentsがインストールされていない

**解決方法**:
```bash
pip install -e ".[dev]"
```

### 3. `ValueError: OPENAI_API_KEY環境変数が設定されていません`

**原因**: 環境変数が設定されていない

**解決方法**:
```bash
export OPENAI_API_KEY="your-api-key"
```

### 4. Grafana接続エラー

**原因**: 
- GRAFANA_URLが間違っている
- Service Account Tokenの権限が不足
- ネットワーク接続の問題

**解決方法**:
1. GRAFANA_URLを確認（末尾のスラッシュは不要）
2. Service Accountに十分な権限があることを確認
3. curlでGrafanaに接続できるか確認：
   ```bash
   curl -H "Authorization: Bearer $GRAFANA_SERVICE_ACCOUNT_TOKEN" $GRAFANA_URL/api/health
   ```

### 5. `Rate limit exceeded`

**原因**: OpenAI APIのレート制限に達した

**解決方法**:
- 数分待ってから再試行
- OpenAI APIの使用量プランを確認

## 次のステップ

1. `config.yml` の `agent.system_prompt` や `constraints` を変更して、エージェントの振る舞いをカスタマイズ
2. `alert_detection.rules` でアラート検知パターンを調整
3. `mention.channels` で応答するチャンネルを制限
4. `channel_namespace_map` でチャンネルとKubernetes namespaceの紐づけを設定

詳細は[README.md](README.md)の「Configuration Reference」セクションを参照してください。
