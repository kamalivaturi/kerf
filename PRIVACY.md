# Privacy

Kerf runs on your computer. It has no account, no analytics and no server of its own.

The full policy, with the data table, your rights and contact details, is on the website:
**https://kamalivaturi.github.io/kerf/privacy.html** (also in this repository: [`docs/privacy.html`](docs/privacy.html)).
The cookie policy, terms and refund policy are beside it in [`docs/`](docs/).

## What Kerf keeps on your computer

A `.kerf` folder in your user folder: settings, an access token, caches, downloaded models, presets, a custom
vocabulary and a log of the last 50 engine errors (home folder shortened to `~`). API keys you enter are stored there
as plain text in `settings.json`. The local engine listens only on `127.0.0.1`, and every request needs the token.

## What leaves your computer, and only when you use the feature

| Feature | Goes to | What is sent |
|---|---|---|
| Update check, automatic updates | GitHub | An ordinary web request (your IP address) |
| One-time model downloads | GitHub releases, Hugging Face Hub | An ordinary web request for the model file |
| Downloader (yt-dlp) | The site whose link you paste | What a browser sends; browser cookies only if you choose that option |
| AI prompt edits and text features | The provider you set up (Anthropic, OpenAI, Google, or your own local model address) | Your prompt, a timeline summary, and for some features transcript text. Not your video or audio |
| Stock footage (B-roll) | Pexels | Search words and your Pexels key |
| Studio voice cleanup, translate and dub | ElevenLabs | Audio from the tracks you choose, and your key |
| Voiceover speech server | The address you set (default: your own computer) | The text to speak |
| Report a bug | GitHub issue form in your browser | Pre-filled version, OS and recent errors; nothing is sent until you submit |
| Licence key (optional, unused by the free version) | Lemon Squeezy | The key and your computer's name |

Libraries Kerf uses (the AI provider kits, the model downloader) add their usual client details, such as library
version and operating system, to their own requests.

## Website

The website sets no cookies and uses no analytics. GitHub Pages hosts it and logs visitor IP addresses. One browser
setting, the light or dark theme, stays on your device.

## Questions

Do not put personal information in a public issue. Use the contact on the
[privacy policy page](https://kamalivaturi.github.io/kerf/privacy.html).

*Draft. Not legal advice.*
