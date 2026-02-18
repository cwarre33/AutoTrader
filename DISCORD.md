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

- **Token**: The gateway uses the Discord token from `openclaw-config/openclaw.json` (`channels.discord.token`). Your `.env` can override with `DISCORD_BOT_TOKEN`; the gateway now receives that env var.
- **Logs**: After restart, watch gateway logs for Discord errors:
  ```bash
  docker compose logs -f openclaw-gateway
  ```
  Send a message in #general and see if any Discord-related errors appear (e.g. 401, intents, or connection).

## 4. Optional: Restrict to @mentions again

Once the bot is receiving and replying, to make it answer only when @mentioned:

In `openclaw-config/openclaw.json`, under `channels.discord.guilds["1473759045197500516"]` and under the channel `1473759046073843714`, set `"requireMention": true`, then restart the gateway.
