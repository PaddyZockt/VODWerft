# VODWerft – User guide

VODWerft turns your game recordings into finished episodes: it cuts them, writes titles and descriptions, creates thumbnails and schedules the upload to YouTube. Processing runs on your Windows PC. Uploading runs **by hand** (simplest, no Google project needed), **directly from the PC**, or on a small **Docker server** (for round-the-clock operation).

> **Beginners:** choose "Von Hand hochladen" (upload by hand) in the installer. You need no Google project; VODWerft prepares each episode (see [Manual upload](#manual-upload-no-youtube-project)).

> **Read first (automatic upload only):** YouTube forces videos uploaded through the API by an **unaudited** Google project (created after 28 July 2020) to **private** until the project passes a compliance audit. See [YouTube access](#5-youtube-sign-in-and-approval).

## 1. Requirements

- Windows PC with an NVIDIA GPU, **16 GB VRAM** recommended; about 30 GB free disk space
- *Optional:* a Linux server or NAS with **Docker** and a network share between PC and server
- A YouTube channel and a Google account

The installer checks for **uv**, **ffmpeg** and **Ollama** and offers to install missing ones with `winget`. Nothing is installed without your consent.

## 2. Install on the PC

1. Download **`VODWerft-Setup.exe`** from the Releases page and double-click it.
2. **Windows will warn you.** The installer is not code-signed yet, so Edge or SmartScreen shows "Windows protected your PC" or "not commonly downloaded". That is expected for a beta. Click **More info**, then **Run anyway** (in Edge: the three dots next to the download, **Keep**, then **Keep anyway**). Then accept the administrator prompt.
3. **Installer questions:** target folder, mode (this PC only or with a server), data folder, and which missing programs (uv, ffmpeg, Ollama) to install. Nothing is installed without a tick.
4. **Progress:** the install page shows a list of steps (waiting, running, done) and a progress bar. While the AI models download, the bar shows real progress in percent.
5. **Duration:** without models it takes a few minutes. The AI models are about **25 GB**; depending on your connection that is **30 minutes to several hours**. Keep the window open and do not let the PC go to sleep.
6. At the end the **setup assistant** opens (chapter 3). There is a **VODWerft** entry in the Start menu, optionally on the desktop and in autostart.

**Something failed?** At the end the installer tells you what did not work. Details are in `%TEMP%\vodwerft-setup.log` (Windows key + R, enter the path). Missing AI models are fetched on first start. You can run the installer again at any time.

## Uninstall

1. **Settings → Apps → Installed apps → VODWerft → Uninstall.**
2. You can also remove **uv, ffmpeg, Ollama** and **VODWerft's AI models**. Nothing is ticked by default; leave the boxes empty if you need those programs for something else.
3. **Your data always stays** (videos, settings, YouTube sign-in) in `%LOCALAPPDATA%\VODWerft`. Delete that folder by hand if you want it gone too.

## 3. First-run setup

On first start the setup assistant opens by itself (later: tray icon → right-click → *Einrichtung öffnen*).

0. **Upload mode** – "Directly from this PC" (recommended to start) or "Via a server".
1. **Check PC** – shows whether ffmpeg, Ollama and the GPU were found.
2. **Folders** – data folder, the **server share** (it must contain `.upload`, `Fertig`, `Pruefen`), recordings folder, ffmpeg folder, Ollama, your channel link.
3. **Games** – pick from the library or type your own name (no `: / \ ? * " < > |`). Set episode length and publishing weekdays per game; put your recordings into that game's folder.
4. **Save** – the services start immediately.

**Safe defaults:** every episode waits for your approval before upload, and uploading stays locked until the file `upload-freigabe.flag` exists in the data folder.

## 4. Upload server (Docker, optional)

Only needed if you chose "Via a server". In direct mode go straight to chapter 5.

The `server` folder is in the package. The ready-made server image is built automatically for every release and pulled from GitHub; you do not build anything yourself.

1. Create a folder on the server and copy `docker-compose.yml` and `.env.example` into it. Rename `.env.example` to `.env` and set your paths.
2. Create `.upload`, `Fertig`, `Pruefen` and `.status` in the shared folder and share it with your PC.
3. Copy `config-example/description-footer.txt` as `description-footer.txt` into the server's program folder (`UPLOADER_DIR`) and edit it (`${game}` and `${developer}` are available).
4. Start with `docker compose up -d`. To update: `docker compose pull && docker compose up -d`.

The server reports its version to the PC; if they do not match, the tray icon warns you.

## Manual upload (no YouTube project)

The simplest way, with **no** sign-in and **no** Google project. VODWerft cuts, writes title and description and creates the thumbnail. You do the upload in YouTube Studio yourself, about a minute per episode. Your video is not forced to private.

1. Right-click the tray icon → **Manuell hochladen**. (The entry only appears in this mode.)
2. Pick a finished episode on the left. Only approved, finished episodes are listed.
3. Open **YouTube Studio** and drag the video in; **Video im Ordner zeigen** finds the file.
4. Copy the **title**, then the **description** and **tags**, and paste them into YouTube.
5. Upload the thumbnail as the custom thumbnail (**Vorschaubild zeigen**).
6. If a **scheduled time** is shown, set it in YouTube under Visibility → Schedule.
7. Finally **Als hochgeladen markieren**. The episode moves to the "Fertig" folder and disappears from the list.

You can switch to automatic upload later via the setup assistant (tray menu, "Einrichtung öffnen").

## 5. YouTube sign-in and approval

You do this once, yourself; VODWerft never asks for your Google password.

**Direct mode:** at the end of the setup assistant, pick your `client_secrets.json` and click "Bei YouTube anmelden". Your browser opens the Google sign-in and you are done. You can also do this later via the tray menu ("Einrichtung öffnen"). Uploading stays locked until you are signed in.

**Server mode:** follow steps 4 and 5 below.

**You need your own Google project.** The author of VODWerft does not share his own project, and `client_secrets.json` is tied to one project. Everybody creates their own project (free; steps below). YouTube's quota and the limits described below then apply to your project. If that is too much effort, use "Von Hand hochladen" (manual upload) instead.

1. Create a project in the Google Cloud Console and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen and add yourself as a test user.
3. Create an OAuth client of type *Desktop app* and download `client_secrets.json`.
4. Put it into the secrets folder (`SECRETS_DIR` in `.env`). Never commit it or put it on a share.
5. Confirm the sign-in once in the browser; this creates `request.token`.

**Limits to know:** unaudited projects can only upload private videos (publish them yourself in YouTube Studio, or apply for the audit; locked videos cannot be appealed). While the consent screen is in testing mode, sign-ins expire after about seven days.

## 6. Daily use and troubleshooting

Drop recordings into the game's folder; the watcher waits until files are complete and processes them in file-name order. The tray icon shows the status; double-click opens the dashboard. Files the server cannot upload end up in `Pruefen`. For logs open the data folder and read `production\watcher.log`. 

### More features

- **Review the plan (optional):** switch it on under *Settings → Cut* or per game profile. The job stops after the analysis ("Wartet auf dich"). "Plan prüfen öffnen" shows what was removed automatically; remove more ranges or keep some, then confirm. Rendering starts only after that.
- **YouTube details per game:** *Game profiles → YouTube*: playlist, fixed tags and collab partners. The playlist needs an extra permission: tick "Auch Playlists zuordnen" when you sign in in the setup assistant. If you are already set up, sign in once more: open a command prompt in the program folder (`C:\Program Files\VODWerft`) and run `venv\Scripts\python.exe vodwerft\youtube_login.py "%LOCALAPPDATA%\VODWerft\uploader\secrets" --playlists`, then confirm in the browser (in server mode do the same in the folder holding `client_secrets.json`). Inviting a collab partner and the game title can only be set in YouTube Studio; the job details remind you.
- **Use of AI:** YouTube asks for every video whether AI created or changed content. VODWerft does not declare anything by default, so you answer it in Studio. *Settings → YouTube* can send "No" with every upload.
- **Transitions at cuts:** *Settings* or game profile: hard (default), fade, blur, white flash, zoom, pixelate. The episode length stays the same.
- **Stop a job and remaining time:** the "Auftrag stoppen" button in the job list ends a running job; "Verlauf → Export erneut versuchen" continues it. Steps with a counter show "noch etwa 12 Min." in the job details.
- **Library (server mode):** next to `Fertig` a folder `Bibliothek\<game>` holds a link per uploaded episode (double-click opens the video on YouTube).
- **Notifications and disk space:** Windows tells you when a job waits for you or is finished (*Settings → Appearance* switches it off). If the work drive is too full, the dashboard and the job history warn you.

## Common problems

| Problem | Fix |
|---|---|
| Windows warns about the installer | Expected, it is not signed yet. "More info", "Run anyway" (chapter 2) |
| The installer says Ollama or a model is missing | Install Ollama from ollama.com and run the installer again. VODWerft fetches missing models on first start |
| The model download stops or is very slow | Check your connection and run the installer again. Ollama usually resumes a started download |
| No tray icon | Start "VODWerft" from the Start menu and check the hidden icons next to the clock |
| The setup assistant does not open | Tray menu, "Einrichtung öffnen" |
| Nothing happens although installed | Open the data folder (tray menu), read `production\watcher.log` and report it as an issue in the public repo without paths or credentials |
| Videos stay private | See chapter 5, first limitation |

## Update

VODWerft checks GitHub for a newer version at start and every six hours. When there is one, the dashboard shows "Update available". One click shows what is new first; only "Install now" downloads and installs (the checksum is verified). If a job is running, the update can wait for it. You can also run the installer by hand: run the new `VODWerft-Setup.exe` over the existing installation. Your setup and data are kept. Quit VODWerft first via the tray menu ("Beenden").
