# Discord: Bot not receiving or responding to messages

If the bot never replies to you in the channel (cron scan messages are from the scheduler, not from your @mentions), the gateway is almost certainly **not receiving** your channel messages. Fix it in this order.

## 1. Enable Message Content Intent (required)

Discord does not send guild channel message content to the bot unless this is on.

1. Go to [Discord Developer Portal](https://discord.com/developers/applications) → your application (AutoTrader).
2. Open **Bot** in the left sidebar.
3. Scroll to **Privileged Gateway Intents**.
4. Turn **Message Content Intent** **ON**.
5. Save.

Then **restart the gateway** so it reconnects with the new intent:

```bash
docker compose restart openclaw-gateway
```

Wait ~30 seconds, then send a message in #general. If the bot still does not reply, continue below.

## 2. Test without mention requirement

Right now the config is set so the bot responds to **every** message in #general (`requireMention: false`). That is only for testing.

- If the bot **starts** replying to normal messages after step 1 + restart → Message Content Intent was the problem. You can set `requireMention: true` again in `openclaw-config/openclaw.json` under the guild and channel if you want replies only when @mentioned.
- If the bot **still** never replies → check step 3.

## 3. Confirm token and logs

- **Token**: Do **not** put the Discord bot token in `openclaw.json`. Set `DISCORD_BOT_TOKEN` in your `.env`; the gateway receives it via docker-compose and OpenClaw uses it when `channels.discord.token` is empty.
- **Logs**: After restart, watch gateway logs for Discord errors:
  ```bash
  docker compose logs -f openclaw-gateway
  ```
  Send a message in #general and see if any Discord-related errors appear (e.g. 401, intents, or connection).

## 4. Optional: Restrict to @mentions again

Once the bot is receiving and replying, to make it answer only when @mentioned:

In `openclaw-config/openclaw.json`, under `channels.discord.guilds["1473759045197500516"]` and under the channel `1474502611393581267`, set `"requireMention": true`, then restart the gateway.

## 5. "channels unresolved" in logs

If you see `channels unresolved: <guildId>/<channelId>`:

- **Verify IDs**: In Discord, enable Developer Mode (Settings → Advanced), right-click the channel → Copy ID. Ensure `openclaw-config/openclaw.json` has the correct guild and channel IDs under `channels.discord.guilds`.
- **Bot permissions**: The bot must have "View Channel" and "Read Message History" in that channel.
- **Restart**: After fixing config, run `docker compose restart openclaw-gateway`.

## 6. "Action send requires a target"

If you see `⚠️ ✉️ Message: send failed: Action send requires a target` in Discord:

- This usually means the cron/heartbeat delivery can't resolve the channel. It's related to "channels unresolved" in the logs.
- **Fix**: Verify guild and channel IDs in `openclaw-config/openclaw.json` and in the cron job's `delivery.to` field (`channel:1474502611393581267`).
- Ensure the bot is in the server and has access to that channel. Restart the gateway after fixing.

## 7. Config errors that block Discord

- **"Unrecognized key: botToken"**  
  OpenClaw expects `channels.discord.token`, not `botToken`. If your config has `botToken` (e.g. after an older setup or doctor), run **`openclaw doctor --fix`** so it removes the invalid key. Keep using `DISCORD_BOT_TOKEN` in the environment; do not put the token in the JSON file.

- **"Channel is required (no configured channels detected)"** / **"Ambiguous Discord recipient"**  
  Replies must target the channel explicitly. Ensure the Discord channel is listed under `channels.discord.guilds.<guildId>.channels.<channelId>` with `allow: true`. If delivery recovery fails with "Use user:... or channel:...", the runtime config should use the channel (not the user ID alone) for sending; restart the gateway after fixing the config.
