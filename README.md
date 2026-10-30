# OrionTap setup

OrionTap is a Telegram tap-to-earn points demo: 1 tap costs 1 energy and earns 1 point; energy refills by 1 each minute up to 500. Daily reward is 25 points. Referrer and new user each get 50 points when a valid new referral joins. SQLite stores points, energy, streaks and referrals locally. Points are not a token and have no guaranteed value. There is no deposit, payment, wallet connection or live token.

## Create the Telegram bot

1. In Telegram, open the official `@BotFather`, send `/newbot`, choose the displayed bot name and a unique username ending in `bot`. BotFather returns the bot token. Keep it private.
2. On the backend host, install Python 3.10+ and the packages in `requirements.txt` (`pip install -r requirements.txt`). Put the token in the environment variable `BOT_TOKEN`. Do not paste it into the website or commit it to GitHub. Start the bot with `python bot.py`.
3. Set `BOT_USERNAME` to the username without `@`, and `MINI_APP_URL` to the deployed HTTPS Mini App address. Set `ORIONTAP_DB` to a persistent writable file path on the backend host. If the host's disk is ephemeral, configure persistent storage before using it for live accounts.
4. Telegram requires the web app URL to be HTTPS. In BotFather, use `/setdomain` for the deployed site domain and follow BotFather's Mini App setup to add its URL as the bot's menu button. The `/start` response also includes an Open OrionTap button once `MINI_APP_URL` is set.
5. The bot's API and GitHub Pages are separate origins, so set `WEB_ORIGIN=https://therealorionstar.github.io` on the backend and set the Mini App URL to `https://therealorionstar.github.io/oriontap/?api=https%3A%2F%2FYOUR-BACKEND-HOST`. Replace `YOUR-BACKEND-HOST` with the HTTPS origin of the Python backend. Keep the `api` value URL-encoded. The browser's app requests then use that API host and the backend only permits the configured Pages origin.

## GitHub Pages

The frontend is the static `index.html`, `style.css`, and `app.js` in this repo. Enable GitHub Pages for the repository's `main` branch, root folder. The public URL will be `https://therealorionstar.github.io/oriontap/`. The bot/API needs to run on a separate always-on Python host; GitHub Pages serves static files only. Set `MINI_APP_URL` to the actual Pages URL and serve the Flask endpoints under the same origin, or update the frontend API paths and enable appropriate CORS for your chosen API host. The `/api/health` endpoint can be used to check the backend.

## Commands and features

- `/start` creates the account and accepts referral payloads like `/start ref_123456`.
- `/mine` provides the inline tap button. `/balance`, `/daily`, `/leaderboard` and `/help` are also available.
- Mini App sessions are authenticated by validating Telegram's signed `initData` using `BOT_TOKEN`; requests are rejected when Telegram auth is missing or invalid. The web app itself can display its clock and layout without bot setup, but live server-saved points require the bot token and a reachable backend.
- Daily streak uses Africa/Lagos calendar dates. A missed calendar day resets the streak when the next daily bonus is claimed.
- Only the first referral on account creation is recorded. Self-referrals are rejected. The referred user and existing inviter each receive the referral bonus once.

## Later revenue and token plans

Possible future revenue sources are ad placements through a Mini App provider such as Adsgram and clearly labeled sponsor tasks paid for by advertisers. Those are not integrated yet, and no revenue is currently generated. The roadmap mentions a possible TON jetton only after community growth and real project revenue. Conversion of points, Tonkeeper support and DEX trading through STON.fi or DeDust are future plans only, not live features or promises. No purchase is needed to mine, and no returns are promised.

## Local checks

Use `python bot.py` only after adding `BOT_TOKEN`; without it, the database functions are importable and the Flask API health endpoint can be run for checks, but Telegram commands and authenticated player API cannot operate. The app never puts a bot token in browser code.
