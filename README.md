# 緣結 YouTube 自動通知

緣結開台 / 上新片 → 自動發到 Discord，**免費、跑在 GitHub Actions、不用開電腦**。

- `notify.py`：用 YouTube 公開 RSS 偵測新片、用 `/live` 頁偵測開台，發到 Discord Webhook。
- `.github/workflows/notify.yml`：每 5 分鐘自動跑（GitHub 排程可能延遲幾分鐘）。
- `state.json`：記住上次看到的影片/直播，避免重複通知。

## 設定（密鑰，存在 repo Settings → Secrets）
| 名稱 | 內容 |
|---|---|
| `YT_CHANNEL_ID` | 緣結 YouTube 頻道 ID |
| `WEBHOOK_LIVE` | 開台通知頻道的 Discord Webhook |
| `WEBHOOK_UPLOAD` | 新片通知頻道的 Discord Webhook |
| `PING_LIVE` | 開台要 tag 的身分組，如 `<@&角色ID>`（可留空）|

## 注意
- **開台偵測是靠抓 YouTube 頁面**，YouTube 改版可能需要微調（這是免費方案的代價）。
- GitHub 排程不保證準時，**開台通知可能慢 5～15 分鐘**。要即時就得付費服務或自有主機。
- 想改通知文字 → 編輯 `notify.py` 裡的 `post(...)` 那幾行。
